"""Candidate moments from signal rules (PRD 13, 12.7).

Each detector reads observed tracking and events only, measures the signals the moment type must leave, and
reports their strength as ratios to thresholds. A candidate whose signals all pass is confirmed; one whose
signals reach 70% while the window is still open is speculative, so the broadcast crew can start drafting
before the moment ends (PRD 14.4).
"""

from __future__ import annotations

import numpy as np

from offball.contracts import Candidate, Signal
from offball.core import FRAME_MS, HZ, detected_id
from offball.models.match_data import MatchData
from offball.models.metrics import _zone_cells, zone_control_at
from offball.models.runs import Possession, Run, detect_runs

THRESHOLDS = {
    "defender_displacement_m": 8.0,
    "defender_follow_cosine": 0.6,
    "zone_control_gain_pts": 40.0,
    "pass_into_gap": 1.0,
}
SPECULATIVE_AT = 0.7
WINDOW_FRAMES = 100  # 4 s after the run starts
BASELINE_FRAMES = 15  # the "before" picture of a gap: 0.6 s before the run is detected


def _rect(cx: float, cy: float, half_w: float, half_h: float) -> list[tuple[float, float]]:
    x0, x1 = max(0.0, cx - half_w), min(105.0, cx + half_w)
    y0, y1 = max(0.0, cy - half_h), min(68.0, cy + half_h)
    return [(round(x0, 1), round(y0, 1)), (round(x1, 1), round(y0, 1)), (round(x1, 1), round(y1, 1)),
            (round(x0, 1), round(y1, 1))]


def _inside(xy, zone: list[tuple[float, float]], pad: float) -> bool:
    xs = [p[0] for p in zone]
    ys = [p[1] for p in zone]
    return min(xs) - pad <= xy[0] <= max(xs) + pad and min(ys) - pad <= xy[1] <= max(ys) + pad


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    na, nb = float(np.linalg.norm(a)), float(np.linalg.norm(b))
    if na < 1e-6 or nb < 1e-6:
        return 0.0
    return float(a @ b / (na * nb))


class DecoyRunDetector:
    """A runner drags a goal-side defender away and the vacated space is attacked (PRD 12.7, Decoy run)."""

    type = "decoy_run"

    def __init__(self, md: MatchData) -> None:
        self.md = md
        self.possession = Possession(md)

    def _judge(self, run: Run, i0: int, i_end: int, dcol: int, disp_max: float, follow: float, i_disp: int) -> dict:
        """The signals of the gap one following defender leaves."""
        md, period, club = self.md, run.period, run.club
        pf = md.periods[period]
        # A run is only detected once the runner has accelerated, and by then the defender may be moving too:
        # take the gap and its control from a moment before, while he was still in place.
        i_base = max(i0 - BASELINE_FRAMES, 0)
        p0 = pf.xy[i_base, dcol].astype(float)
        if np.isnan(p0).any():
            p0 = pf.xy[i0, dcol].astype(float)
        goal = np.array([105.0 if md.direction(period, club) > 0 else 0.0, 34.0])  # the goal the runner attacks
        to_goal = (goal - p0) / (np.linalg.norm(goal - p0) or 1.0)
        centre = p0 + to_goal * 1.5
        zone = _rect(float(centre[0]), float(centre[1]), 4.5, 6.0)
        cells = _zone_cells(zone)
        c_start = zone_control_at(md, club, period, i_base, cells).mean()
        gain_open_idx, gain_max = None, -1.0
        for i in range(i0, i_end + 1, 5):
            g = zone_control_at(md, club, period, i, cells).mean() - c_start
            gain_max = max(gain_max, g)
            if gain_open_idx is None and g >= 0.40:
                gain_open_idx = i
        # A pass by the same club into the gap, within 2 s of it opening (or anticipating it).
        t_open = int(pf.t_ms[gain_open_idx]) if gain_open_idx is not None else None
        t_hi = (t_open + 2000) if t_open is not None else int(pf.t_ms[i_end])
        passes = [e for e in md.events_between(period, run.t0_ms, t_hi)
                  if e.type == "pass" and e.team_id == club and e.end_xy and _inside(e.end_xy, zone, 3.0)]
        pass_ev = passes[0] if passes else None
        signals = [
            Signal(name="defender_displacement_m", value=round(disp_max, 1), threshold=8.0, unit="m",
                   evidence_ids=[md.frame_id(period, run.t0_ms), md.frame_id(period, int(pf.t_ms[i_disp]))]),
            Signal(name="defender_follow_cosine", value=round(follow, 2), threshold=0.6, unit="cos",
                   evidence_ids=[md.frame_id(period, int(pf.t_ms[i_disp]))]),
            Signal(name="zone_control_gain_pts", value=round(gain_max * 100, 0), threshold=40.0, unit="pts",
                   evidence_ids=[md.frame_id(period, int(pf.t_ms[gain_open_idx]))] if gain_open_idx else []),
            Signal(name="pass_into_gap", value=1.0 if pass_ev else 0.0, threshold=1.0, unit="bool",
                   evidence_ids=[pass_ev.event_id] if pass_ev else []),
        ]
        strength = float(np.mean([min(sg.value / sg.threshold, 1.25) if sg.threshold else 1.0 for sg in signals]))
        return {"signals": signals, "strength": strength, "dcol": dcol, "zone": zone, "cells": cells, "p0": p0,
                "pass_ev": pass_ev, "gain_open_idx": gain_open_idx}

    def evaluate(self, run: Run, now_idx: int | None = None) -> Candidate | None:
        md, period = self.md, run.period
        pf = md.periods[period]
        club = run.club
        if self.possession.at(period, run.t0_ms) != club:
            return None  # off-ball runs in attack only
        i0 = run.i0
        i_end = min(i0 + WINDOW_FRAMES, pf.n - 1)
        if now_idx is not None:
            i_end = min(i_end, now_idx)
        if i_end - i0 < 10:
            return None
        runner_col = md.players.index(run.player_id)
        opp_cols = md.columns_of(md.other(club))
        start = pf.xy[i0].astype(float)
        followers = []
        for col in opp_cols:
            p = start[col]
            if np.isnan(p).any() or float(np.linalg.norm(p - start[runner_col])) > 9.0:
                continue
            # Goal-side: between the runner and the goal the runner attacks.
            px = md.to_team(period, club, p)[0]
            rx = md.to_team(period, club, start[runner_col])[0]
            if px < rx - 2.0:
                continue
            seg = pf.xy[i0: i0 + 76, col].astype(float)
            disp = np.linalg.norm(seg - p, axis=1)
            k = int(np.nanargmax(disp))
            follow = _cosine(seg[k] - p, pf.xy[i0 + k, runner_col].astype(float) - start[runner_col])
            followers.append((float(np.nanmax(disp)) * max(follow, 0.0), int(col), float(np.nanmax(disp)), follow, i0 + k))
        if not followers:
            return None
        # More than one defender may go with the runner (a midfielder as well as the centre-back): judge the gap
        # each would leave, and keep the strongest.
        judged = [self._judge(run, i0, i_end, *f[1:]) for f in sorted(followers, reverse=True)[:3]]
        judged.sort(key=lambda j: (all(sg.value >= sg.threshold for sg in j["signals"]), j["strength"]), reverse=True)
        j = judged[0]
        signals, strength, dcol, zone, cells, p0 = j["signals"], j["strength"], j["dcol"], j["zone"], j["cells"], j["p0"]
        pass_ev, gain_open_idx = j["pass_ev"], j["gain_open_idx"]
        defender = md.players[dcol]
        all_pass = all(sg.value >= sg.threshold for sg in signals)
        window_closed = now_idx is None or now_idx >= min(i0 + WINDOW_FRAMES, pf.n - 1)
        if all_pass:
            status = "confirmed"
        elif strength >= SPECULATIVE_AT and not window_closed:
            status = "speculative"
        else:
            return None
        # Quick space estimate: the zone's controlled area now, against a ghost of the defender left in place.
        i_meas = pf.index_of(pass_ev.t_ms) if pass_ev else (gain_open_idx or i_end)
        actual = zone_control_at(md, club, period, i_meas, cells)
        ghost = zone_control_at(md, club, period, i_meas, cells, override={dcol: p0})
        space = float(max((actual - ghost).sum(), 0.0))
        evidence = sorted({eid for s in signals for eid in s.evidence_ids})
        return Candidate(
            candidate_id="pending",
            match_id=md.match_id,
            period=period,
            t_start_ms=run.t0_ms,
            t_end_ms=int(pf.t_ms[i_end]),
            type="decoy_run",
            team_id=club,
            creator_id=run.player_id,
            dragged_ids=[defender],
            receiver_id=pass_ev.recipient_id if pass_ev else None,
            gap_zone=zone,
            run_from=(round(float(run.start_xy[0]), 1), round(float(run.start_xy[1]), 1)),
            run_to=(round(float(run.end_xy[0]), 1), round(float(run.end_xy[1]), 1)),
            signals=signals,
            strength=round(strength, 3),
            status=status,
            space_created_m2=round(space, 0),
            evidence_ids=evidence,
        )


def _finish(signals: list[Signal], window_closed: bool) -> tuple[float, str] | None:
    """Strength and status from signals: confirmed when every threshold is met, speculative while the window
    is open and the signals are most of the way there."""
    ratios = [min(s.value / s.threshold, 1.25) if s.threshold else 1.0 for s in signals]
    strength = float(np.mean(ratios))
    if all(s.value >= s.threshold for s in signals):
        return strength, "confirmed"
    if strength >= SPECULATIVE_AT and not window_closed:
        return strength, "speculative"
    return None


def _second_last_x(md: MatchData, period: int, club: str, i: int) -> float:
    """The offside line for `club` at frame i: x' of the opponents' second-last player, in club's frame."""
    pf = md.periods[period]
    xy = pf.xy[i, md.columns_of(md.other(club))].astype(float)
    xy = xy[~np.isnan(xy[:, 0])]
    xs = sorted(md.to_team(period, club, xy)[:, 0], reverse=True)
    return max(float(xs[1]), 52.5) if len(xs) >= 2 else 52.5


def _flank_runner(md: MatchData, run: Run, i0: int, i_end: int, inside: bool) -> tuple | None:
    """A runner from behind a wide teammate on the ball who gets level with him, round the outside or (for an
    underlap) inside him. Returns (carrier column, frame he has the ball, runner column, flank side, frame the
    runner is level, carrier position in the club's frame), or None."""
    period, club = run.period, run.club
    pf = md.periods[period]
    cols = md.columns_of(club)
    rcol = md.players.index(run.player_id)
    # The teammate with the ball at his feet as the run begins, or just after (a pass may be on its way):
    # the ball on the ground within reach of him for a fifth of a second, not a ball leaving his foot.
    carrier, held, last = None, 0, -1
    for i in range(i0, min(i0 + 75, i_end)):
        d = np.linalg.norm(pf.xy[i, cols].astype(float) - pf.ball[i, :2], axis=1)
        if np.isnan(d).all():
            continue
        k = int(np.nanargmin(d))
        at_feet = d[k] < 1.5 and pf.ball[i, 2] < 1.0 and cols[k] != rcol
        held = held + 1 if at_feet and int(cols[k]) == last else int(at_feet)
        last = int(cols[k]) if at_feet else -1
        if held >= 5:
            carrier = (last, i)
            break
    if carrier is None:
        return None
    ccol, ic = carrier

    def team_xy(i: int, col: int) -> np.ndarray:
        return md.to_team(period, club, pf.xy[i, col].astype(float))

    c_t, r_t = team_xy(ic, ccol), team_xy(ic, rcol)
    if not (48 <= c_t[0] <= 84 and abs(c_t[1] - 34) > 11):
        return None  # a wide player on the ball in the attacking half
    side = -1.0 if c_t[1] < 34 else 1.0
    if not (c_t[0] - 26 <= r_t[0] <= c_t[0] - 1 and abs(r_t[1] - c_t[1]) < 18):
        return None  # the runner comes from behind, on the same flank

    def level(i: int) -> bool:
        r, c = team_xy(i, rcol), team_xy(i, ccol)
        if r[0] < c[0] - 1.0:
            return False
        if inside:  # level and inside him, still on that half of the pitch
            return (r[1] - 34) * side <= (c[1] - 34) * side - 2.0 and (r[1] - 34) * side > -4.0
        return (r[1] - 34) * side >= (c[1] - 34) * side - 1.0

    rounded = next((i for i in range(ic, i_end + 1) if level(i)), None)
    if rounded is None:
        return None  # never got level with him
    return ccol, ic, rcol, side, rounded, c_t


def _receipt(md: MatchData, period: int, col: int, i_from: int, frames: int = 100) -> int | None:
    """The first frame after i_from where the ball is at player col's feet."""
    pf = md.periods[period]
    for i in range(i_from, min(i_from + frames, pf.n)):
        if float(np.linalg.norm(pf.ball[i, :2] - pf.xy[i, col])) < 1.5 and pf.ball[i, 2] < 1.5:
            return i
    return None


OVERLAP_WINDOW = 250  # 10 s after the run starts: the overlap, the pass down the line and the delivery


class OverlapDetector:
    """A runner goes round the outside of a teammate on the ball out wide, making two against one on the flank,
    and a cross or cut-back follows (PRD 12.7, Overlap)."""

    type = "overlap"

    def __init__(self, md: MatchData) -> None:
        self.md = md
        self.possession = Possession(md)

    def evaluate(self, run: Run, now_idx: int | None = None) -> Candidate | None:
        md, period, club = self.md, run.period, run.club
        pf = md.periods[period]
        if self.possession.at(period, run.t0_ms) != club:
            return None
        i0 = run.i0
        i_end = min(i0 + OVERLAP_WINDOW, pf.n - 1)
        if now_idx is not None:
            i_end = min(i_end, now_idx)
        if i_end - i0 < 10:
            return None
        found = _flank_runner(md, run, i0, i_end, inside=False)
        if found is None:
            return None
        ccol, ic, rcol, side, rounded, c_t = found
        # The flank channel ahead of the carrier, and who controlled it when the run began.
        centre = md.to_team(period, club, np.array([min(c_t[0] + 12.0, 98.0), 34 + side * 28.0]))
        zone = _rect(float(centre[0]), float(centre[1]), 8.0, 6.0)
        cells = _zone_cells(zone)
        c_start = float(zone_control_at(md, club, period, i0, cells).mean())
        if c_start >= 0.6:
            return None  # the flank was already the attackers'
        # The delivery: a cross or cut-back by the club from the flank, whether or not it reached the box.
        def is_delivery(e) -> bool:
            if e.type != "pass" or e.team_id != club or not e.start_xy or not e.end_xy:
                return False
            start, end = md.to_team(period, club, np.array(e.start_xy)), md.to_team(period, club, np.array(e.end_xy))
            from_flank = abs(start[1] - 34) > 12 and start[0] > 55
            into_box = end[0] > 83 and abs(end[1] - 34) < 20.16
            return from_flank and (into_box or e.subtype in ("cross", "cutback"))

        deliveries = [e for e in md.events_between(period, int(pf.t_ms[rounded]) - 1000, int(pf.t_ms[i_end]))
                      if is_delivery(e)]
        delivery = deliveries[0] if deliveries else None
        i_stop = pf.index_of(delivery.t_ms) if delivery else i_end
        opp = md.columns_of(md.other(club))
        peak, peak_idx, run_s, best_s = c_start, ic, 0.0, 0.0
        for i in range(ic, i_stop + 1, 5):
            ctrl = float(zone_control_at(md, club, period, i, cells).mean())
            if ctrl > peak:
                peak, peak_idx = ctrl, i
            a, b = pf.xy[i, ccol].astype(float), pf.xy[i, rcol].astype(float)
            gap = float(np.linalg.norm(a - b))
            mid = (a + b) / 2
            near = np.linalg.norm(pf.xy[i, opp].astype(float) - mid, axis=1)
            two_v_one = gap <= 18.0 and int(np.nansum(near < max(6.0, gap / 2 + 3.0))) <= 1
            run_s = run_s + 0.2 if two_v_one else 0.0
            best_s = max(best_s, run_s)
        if peak - c_start < 0.15:
            return None  # the flank never turned
        signals = [
            Signal(name="wide_zone_control_pct", value=round(peak * 100, 0), threshold=60.0, unit="pct",
                   evidence_ids=[md.frame_id(period, int(pf.t_ms[ic])), md.frame_id(period, int(pf.t_ms[peak_idx]))]),
            Signal(name="two_v_one_s", value=round(best_s, 1), threshold=1.5, unit="s",
                   evidence_ids=[md.frame_id(period, int(pf.t_ms[rounded]))]),
            Signal(name="delivery_follows", value=1.0 if delivery else 0.0, threshold=1.0, unit="bool",
                   evidence_ids=[delivery.event_id] if delivery else []),
        ]
        window_closed = now_idx is None or now_idx >= min(i0 + OVERLAP_WINDOW, pf.n - 1)
        verdict = _finish(signals, window_closed)
        if verdict is None:
            return None
        strength, status = verdict
        # The defender facing the ball: the nearest opponent to the carrier as the run began.
        d_opp = np.linalg.norm(pf.xy[ic, opp].astype(float) - pf.xy[ic, ccol].astype(float), axis=1)
        dragged = [md.players[int(opp[int(np.nanargmin(d_opp))])]] if not np.isnan(d_opp).all() else []
        # Space estimate: the zone's controlled area at its peak, against the runner left where he started.
        actual = zone_control_at(md, club, period, peak_idx, cells)
        ghost = zone_control_at(md, club, period, peak_idx, cells, override={rcol: pf.xy[ic, rcol].astype(float)})
        return Candidate(
            candidate_id="pending",
            match_id=md.match_id,
            period=period,
            t_start_ms=run.t0_ms,
            t_end_ms=int(pf.t_ms[i_stop]),
            type="overlap",
            team_id=club,
            creator_id=run.player_id,
            dragged_ids=dragged,
            receiver_id=delivery.recipient_id if delivery else None,
            gap_zone=zone,
            run_from=(round(float(run.start_xy[0]), 1), round(float(run.start_xy[1]), 1)),
            run_to=(round(float(run.end_xy[0]), 1), round(float(run.end_xy[1]), 1)),
            signals=signals,
            strength=round(strength, 3),
            status=status,
            space_created_m2=round(float(max((actual - ghost).sum(), 0.0)), 0),
            evidence_ids=sorted({eid for s in signals for eid in s.evidence_ids}),
        )


TIMED_RUN_WINDOW = 150  # 6 s after the run starts


class TimedRunDetector:
    """A runner is found in behind: onside as the pass is played, clear of the line when it arrives
    (PRD 12.7, Timed run in behind)."""

    type = "timed_run_in_behind"
    # A run timed onto a through ball is often a short burst: the ball reaches the runner within a second.
    run_args = {"min_frames": 20, "min_disp": 6.0}

    def __init__(self, md: MatchData) -> None:
        self.md = md
        self.possession = Possession(md)

    def evaluate(self, run: Run, now_idx: int | None = None) -> Candidate | None:
        md, period, club = self.md, run.period, run.club
        pf = md.periods[period]
        if self.possession.at(period, run.t0_ms) != club:
            return None
        forward = md.to_team(period, club, run.end_xy)[0] - md.to_team(period, club, run.start_xy)[0]
        if forward < 5.0:
            return None  # a run in behind goes forward
        i_end = min(run.i0 + TIMED_RUN_WINDOW, pf.n - 1)
        if now_idx is not None:
            i_end = min(i_end, now_idx)
        passes = [e for e in md.events_between(period, run.t0_ms - 500, int(pf.t_ms[i_end]))
                  if e.type == "pass" and e.team_id == club and e.recipient_id == run.player_id]
        if not passes:
            return None
        ev = passes[0]
        rcol = md.players.index(run.player_id)
        i_rel = pf.index_of(ev.t_ms)
        margin = _second_last_x(md, period, club, i_rel) - md.to_team(period, club, pf.xy[i_rel, rcol].astype(float))[0]
        i_rec = None
        for i in range(i_rel + 3, min(i_rel + 100, pf.n)):
            if float(np.linalg.norm(pf.ball[i, :2] - pf.xy[i, rcol])) < 1.5 and pf.ball[i, 2] < 1.5:
                i_rec = i
                break
        if i_rec is None:
            return None
        beyond = md.to_team(period, club, pf.xy[i_rec, rcol].astype(float))[0] - _second_last_x(md, period, club, i_rec)
        signals = [
            Signal(name="onside_at_release", value=1.0 if margin >= -0.3 else 0.0, threshold=1.0, unit="bool",
                   evidence_ids=[ev.event_id, md.frame_id(period, int(pf.t_ms[i_rel]))]),
            Signal(name="beyond_line_on_receipt_m", value=round(beyond, 1), threshold=3.0, unit="m",
                   evidence_ids=[md.frame_id(period, int(pf.t_ms[i_rec]))]),
        ]
        window_closed = now_idx is None or now_idx >= min(run.i0 + TIMED_RUN_WINDOW, pf.n - 1)
        verdict = _finish(signals, window_closed)
        if verdict is None:
            return None
        strength, status = verdict
        receipt = pf.xy[i_rec, rcol].astype(float)
        zone = _rect(float(receipt[0]), float(receipt[1]), 7.0, 6.0)
        opp = md.columns_of(md.other(club))
        d_opp = np.linalg.norm(pf.xy[i_rel, opp].astype(float) - pf.xy[i_rel, rcol].astype(float), axis=1)
        dragged = [md.players[int(opp[int(np.nanargmin(d_opp))])]] if not np.isnan(d_opp).all() else []
        return Candidate(
            candidate_id="pending",
            match_id=md.match_id,
            period=period,
            t_start_ms=run.t0_ms,
            t_end_ms=int(pf.t_ms[i_rec]),
            type="timed_run_in_behind",
            team_id=club,
            creator_id=run.player_id,
            dragged_ids=dragged,
            receiver_id=run.player_id,
            gap_zone=zone,
            run_from=(round(float(run.start_xy[0]), 1), round(float(run.start_xy[1]), 1)),
            run_to=(round(float(run.end_xy[0]), 1), round(float(run.end_xy[1]), 1)),
            signals=signals,
            strength=round(strength, 3),
            status=status,
            evidence_ids=sorted({eid for s in signals for eid in s.evidence_ids}),
        )


class UnderlapDetector:
    """A runner from behind goes inside a teammate on the ball out wide, into the half-space, and is found there
    with room to turn (PRD 12.7, Underlap)."""

    type = "underlap"
    run_args = {"min_speed": 4.0, "min_frames": 20, "min_disp": 6.0}  # a purposeful run inside, seldom a sprint

    def __init__(self, md: MatchData) -> None:
        self.md = md
        self.possession = Possession(md)

    def evaluate(self, run: Run, now_idx: int | None = None) -> Candidate | None:
        md, period, club = self.md, run.period, run.club
        pf = md.periods[period]
        if self.possession.at(period, run.t0_ms) != club:
            return None
        i0 = run.i0
        i_end = min(i0 + OVERLAP_WINDOW, pf.n - 1)
        if now_idx is not None:
            i_end = min(i_end, now_idx)
        if i_end - i0 < 10:
            return None
        found = _flank_runner(md, run, i0, i_end, inside=True)
        if found is None:
            return None
        ccol, ic, rcol, side, rounded, c_t = found
        # The half-space channel ahead of the carrier, inside him, and who controlled it when the run began.
        centre = md.to_team(period, club, np.array([min(c_t[0] + 10.0, 93.0), 34 + side * 12.0]))
        zone = _rect(float(centre[0]), float(centre[1]), 8.0, 5.0)
        cells = _zone_cells(zone)
        c_start = float(zone_control_at(md, club, period, i0, cells).mean())
        if c_start >= 0.6:
            return None  # the half-space was already the attackers'
        # The ball to the runner, and how much room he had when it reached him.
        passes = [e for e in md.events_between(period, int(pf.t_ms[rounded]) - 1000, int(pf.t_ms[i_end]))
                  if e.type == "pass" and e.team_id == club and e.recipient_id == run.player_id]
        pass_ev = passes[0] if passes else None
        i_rec = _receipt(md, period, rcol, pf.index_of(pass_ev.t_ms) + 3) if pass_ev else None
        i_stop = i_rec if i_rec is not None else i_end
        peak, peak_idx = c_start, ic
        for i in range(i0, i_stop + 1, 5):
            ctrl = float(zone_control_at(md, club, period, i, cells).mean())
            if ctrl > peak:
                peak, peak_idx = ctrl, i
        if peak - c_start < 0.15:
            return None  # the half-space never turned
        separation = 0.0
        if i_rec is not None:
            opp = md.columns_of(md.other(club))
            separation = float(np.nanmin(np.linalg.norm(pf.xy[i_rec, opp].astype(float) - pf.xy[i_rec, rcol], axis=1)))
        signals = [
            Signal(name="half_space_control_pct", value=round(peak * 100, 0), threshold=60.0, unit="pct",
                   evidence_ids=[md.frame_id(period, int(pf.t_ms[i0])), md.frame_id(period, int(pf.t_ms[peak_idx]))]),
            Signal(name="receiver_separation_m", value=round(separation, 1), threshold=3.0, unit="m",
                   evidence_ids=([pass_ev.event_id] if pass_ev else [])
                   + ([md.frame_id(period, int(pf.t_ms[i_rec]))] if i_rec is not None else [])),
        ]
        window_closed = now_idx is None or now_idx >= min(i0 + OVERLAP_WINDOW, pf.n - 1)
        verdict = _finish(signals, window_closed)
        if verdict is None:
            return None
        strength, status = verdict
        opp = md.columns_of(md.other(club))
        d_opp = np.linalg.norm(pf.xy[ic, opp].astype(float) - pf.xy[ic, ccol].astype(float), axis=1)
        dragged = [md.players[int(opp[int(np.nanargmin(d_opp))])]] if not np.isnan(d_opp).all() else []
        actual = zone_control_at(md, club, period, peak_idx, cells)
        ghost = zone_control_at(md, club, period, peak_idx, cells, override={rcol: pf.xy[ic, rcol].astype(float)})
        return Candidate(
            candidate_id="pending",
            match_id=md.match_id,
            period=period,
            t_start_ms=run.t0_ms,
            t_end_ms=int(pf.t_ms[i_stop]),
            type="underlap",
            team_id=club,
            creator_id=run.player_id,
            dragged_ids=dragged,
            receiver_id=run.player_id if pass_ev else None,
            gap_zone=zone,
            run_from=(round(float(run.start_xy[0]), 1), round(float(run.start_xy[1]), 1)),
            run_to=(round(float(run.end_xy[0]), 1), round(float(run.end_xy[1]), 1)),
            signals=signals,
            strength=round(strength, 3),
            status=status,
            space_created_m2=round(float(max((actual - ghost).sum(), 0.0)), 0),
            evidence_ids=sorted({eid for s in signals for eid in s.evidence_ids}),
        )


THIRD_MAN_WINDOW = 175  # 7 s after the run starts: the pass to the link, the lay-off and the receipt


class ThirdManRunDetector:
    """A passes to B, who lays it off to C, who was already running and receives beyond the line
    (PRD 12.7, Third-man run)."""

    type = "third_man_run"
    run_args = {"min_frames": 20, "min_disp": 6.0}

    def __init__(self, md: MatchData) -> None:
        self.md = md
        self.possession = Possession(md)

    def evaluate(self, run: Run, now_idx: int | None = None) -> Candidate | None:
        md, period, club = self.md, run.period, run.club
        pf = md.periods[period]
        if self.possession.at(period, run.t0_ms) != club:
            return None
        if md.to_team(period, club, run.end_xy)[0] - md.to_team(period, club, run.start_xy)[0] < 5.0:
            return None  # the third man runs forward, beyond the line
        i_end = min(run.i0 + THIRD_MAN_WINDOW, pf.n - 1)
        if now_idx is not None:
            i_end = min(i_end, now_idx)
        rcol = md.players.index(run.player_id)
        to_runner = [e for e in md.events_between(period, run.t0_ms - 500, int(pf.t_ms[i_end]))
                     if e.type == "pass" and e.team_id == club and e.recipient_id == run.player_id]
        for layoff in to_runner:
            link = layoff.player_id
            if link is None or link not in md.players:
                continue
            feeds = [e for e in md.events_between(period, layoff.t_ms - 4000, layoff.t_ms - 1)
                     if e.type == "pass" and e.team_id == club and e.recipient_id == link]
            if not feeds:
                continue
            feed = feeds[-1]
            i_link = _receipt(md, period, md.players.index(link), pf.index_of(feed.t_ms) + 3) or pf.index_of(layoff.t_ms)
            i_rec = _receipt(md, period, rcol, pf.index_of(layoff.t_ms) + 3)
            if i_rec is None:
                continue
            beyond = (md.to_team(period, club, pf.xy[i_rec, rcol].astype(float))[0]
                      - _second_last_x(md, period, club, i_rec))
            # When the run really began: runs are detected from 2.5 m/s, so trace a burst from a standstill back
            # to where the acceleration started.
            onset = run.i0
            while onset > max(run.i0 - HZ, 1) and 0.8 < pf.speed[onset - 1, rcol] <= pf.speed[onset, rcol] + 0.05:
                onset -= 1
            signals = [
                Signal(name="run_before_link_receives", value=1.0 if onset <= i_link else 0.0,
                       threshold=1.0, unit="bool", evidence_ids=[feed.event_id, md.frame_id(period, run.t0_ms)]),
                Signal(name="line_broken_m", value=round(beyond, 1), threshold=1.0, unit="m",
                       evidence_ids=[layoff.event_id, md.frame_id(period, int(pf.t_ms[i_rec]))]),
            ]
            window_closed = now_idx is None or now_idx >= min(run.i0 + THIRD_MAN_WINDOW, pf.n - 1)
            verdict = _finish(signals, window_closed)
            if verdict is None:
                continue
            strength, status = verdict
            receipt = pf.xy[i_rec, rcol].astype(float)
            opp = md.columns_of(md.other(club))
            i_rel = pf.index_of(layoff.t_ms)
            d_opp = np.linalg.norm(pf.xy[i_rel, opp].astype(float) - pf.xy[i_rel, rcol].astype(float), axis=1)
            dragged = [md.players[int(opp[int(np.nanargmin(d_opp))])]] if not np.isnan(d_opp).all() else []
            return Candidate(
                candidate_id="pending",
                match_id=md.match_id,
                period=period,
                t_start_ms=run.t0_ms,
                t_end_ms=int(pf.t_ms[i_rec]),
                type="third_man_run",
                team_id=club,
                creator_id=run.player_id,
                dragged_ids=dragged,
                receiver_id=run.player_id,
                gap_zone=_rect(float(receipt[0]), float(receipt[1]), 7.0, 6.0),
                run_from=(round(float(run.start_xy[0]), 1), round(float(run.start_xy[1]), 1)),
                run_to=(round(float(run.end_xy[0]), 1), round(float(run.end_xy[1]), 1)),
                signals=signals,
                strength=round(strength, 3),
                status=status,
                evidence_ids=sorted({eid for s in signals for eid in s.evidence_ids}),
            )
        return None


DETECTORS = {"decoy_run": DecoyRunDetector, "overlap": OverlapDetector, "timed_run_in_behind": TimedRunDetector,
             "underlap": UnderlapDetector, "third_man_run": ThirdManRunDetector}


def detect(md: MatchData, period: int | None = None, t_from_ms: int = 0, t_to_ms: int | None = None,
           now_ms: int | None = None) -> list[Candidate]:
    """Candidates in a match (batch), or up to `now_ms` in a live period (speculative allowed)."""
    out: list[Candidate] = []
    detectors = [cls(md) for cls in DETECTORS.values()]
    periods = [period] if period is not None else sorted(md.periods)
    for p in periods:
        pf = md.periods[p]
        i_from = pf.index_of(t_from_ms)
        i_to = pf.n if t_to_ms is None else pf.index_of(t_to_ms) + 1
        now_idx = pf.index_of(now_ms) if now_ms is not None else None
        t_lo = int(pf.t_ms[min(i_from, pf.n - 1)])
        t_hi = int(pf.t_ms[min(i_to, pf.n) - 1])
        events = md.events_between(p, t_lo, t_hi)
        runs: dict[tuple, list[Run]] = {}
        for det in detectors:
            trigger = getattr(det, "trigger", "run")
            if trigger == "run":
                args = getattr(det, "run_args", {})
                key = tuple(sorted(args.items()))
                if key not in runs:
                    runs[key] = detect_runs(md, p, i_from, i_to, **args)
                found = [det.evaluate(run, now_idx) for run in runs[key]]
            elif trigger == "pass":
                found = [det.evaluate_pass(e, now_idx) for e in events if e.type == "pass"
                         and (e.outcome == "complete" or getattr(det, "any_pass", False))]
            elif trigger == "turnover":
                found = [det.evaluate_turnover(e, now_idx) for e in events
                         if e.type in ("interception", "tackle") and e.outcome == "won"]
            else:  # a whole period at once: team moments that play out over minutes
                found = det.evaluate_period(p, now_idx)
            out += [c for c in found if c is not None]
    out = _dedupe(out)
    for k, c in enumerate(sorted(out, key=lambda c: (c.period, c.t_start_ms)), start=1):
        c.candidate_id = detected_id(md.match_id, k)
    return sorted(out, key=lambda c: (c.period, c.t_start_ms))


def _dedupe(cands: list[Candidate]) -> list[Candidate]:
    """One candidate per moment: overlapping candidates of the same type by the same player (by the same team, for
    team moments) keep the strongest. Two players making the same kind of run at once are two moments."""

    def owner(c: Candidate) -> str | None:
        return c.team_id if getattr(DETECTORS.get(c.type), "team_moment", False) else c.creator_id

    cands = sorted(cands, key=lambda c: -c.strength)
    kept: list[Candidate] = []
    for c in cands:
        clash = any(k.type == c.type and k.period == c.period and owner(k) == owner(c)
                    and abs(k.t_start_ms - c.t_start_ms) < 3000 for k in kept)
        if not clash:
            kept.append(c)
    return kept


__all__ = ["DETECTORS", "THRESHOLDS", "detect", "FRAME_MS"]


# Detectors for moments triggered by a pass, a turnover or a stretch of play live in their own module, which
# registers them in DETECTORS when imported.
import offball.models.candidates_extra  # noqa: E402, F401
