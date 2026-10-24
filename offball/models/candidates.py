"""Candidate moments from signal rules (PRD 13, 12.7).

Each detector reads observed tracking and events only, measures the signals the moment type must leave, and
reports their strength as ratios to thresholds. A candidate whose signals all pass is confirmed; one whose
signals reach 70% while the window is still open is speculative, so the broadcast crew can start drafting
before the moment ends (PRD 14.4).
"""

from __future__ import annotations

import numpy as np

from offball.contracts import Candidate, Signal
from offball.core import FRAME_MS, detected_id
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
        best = None
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
            score = float(np.nanmax(disp)) * max(follow, 0.0)
            if best is None or score > best[0]:
                best = (score, col, float(np.nanmax(disp)), follow, i0 + k)
        if best is None:
            return None
        _, dcol, disp_max, follow, i_disp = best
        defender = md.players[dcol]
        p0 = start[dcol]
        goal = np.array([105.0 if md.direction(period, club) > 0 else 0.0, 34.0])  # the goal the runner attacks
        to_goal = (goal - p0) / (np.linalg.norm(goal - p0) or 1.0)
        centre = p0 + to_goal * 1.5
        zone = _rect(float(centre[0]), float(centre[1]), 4.5, 6.0)
        cells = _zone_cells(zone)
        c_start = zone_control_at(md, club, period, i0, cells).mean()
        gain_open_idx, gain_max = None, -1.0
        for i in range(i0, i_end + 1, 5):
            g = zone_control_at(md, club, period, i, cells).mean() - c_start
            gain_max = max(gain_max, g)
            if gain_open_idx is None and g >= 0.40:
                gain_open_idx = i
        # A pass by the same club into the gap, within 2 s of it opening (or anticipating it).
        t_open = int(pf.t_ms[gain_open_idx]) if gain_open_idx is not None else None
        t_lo = run.t0_ms
        t_hi = (t_open + 2000) if t_open is not None else int(pf.t_ms[i_end])
        passes = [e for e in md.events_between(period, t_lo, t_hi)
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
        ratios = [min(s.value / s.threshold, 1.25) if s.threshold else 1.0 for s in signals]
        strength = float(np.mean(ratios))
        all_pass = all(s.value >= s.threshold for s in signals)
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


DETECTORS = {"decoy_run": DecoyRunDetector}


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
        for run in detect_runs(md, p, i_from, i_to):
            for det in detectors:
                cand = det.evaluate(run, now_idx)
                if cand is not None:
                    out.append(cand)
    out = _dedupe(out)
    for k, c in enumerate(sorted(out, key=lambda c: (c.period, c.t_start_ms)), start=1):
        c.candidate_id = detected_id(md.match_id, k)
    return sorted(out, key=lambda c: (c.period, c.t_start_ms))


def _dedupe(cands: list[Candidate]) -> list[Candidate]:
    """One candidate per moment: overlapping candidates of the same type keep the strongest."""
    cands = sorted(cands, key=lambda c: -c.strength)
    kept: list[Candidate] = []
    for c in cands:
        clash = any(k.type == c.type and k.period == c.period and abs(k.t_start_ms - c.t_start_ms) < 3000 for k in kept)
        if not clash:
            kept.append(c)
    return kept


__all__ = ["DETECTORS", "THRESHOLDS", "detect", "FRAME_MS"]
