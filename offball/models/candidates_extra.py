"""More candidate detectors (PRD 13, 12.7): moments triggered by a pass, a turnover or a stretch of play rather than
by a single run. Like the run detectors, they read observed tracking and events only."""

from __future__ import annotations

import numpy as np

from offball.contracts import Candidate, Signal
from offball.models.candidates import DETECTORS, _finish, _receipt, _rect
from offball.models.match_data import MatchData
from offball.models.metrics import _zone_cells, zone_control_at
from offball.models.runs import Possession


class _EventDetector:
    """Shared plumbing: team frames, goalkeepers, space around a player, candidates."""

    def __init__(self, md: MatchData) -> None:
        self.md = md
        self.possession = Possession(md)
        self.keepers = {e.player_id for sheet in (md.info.home, md.info.away) for e in sheet.lineup if e.role == "GK"}

    def team_xy(self, period: int, club: str, xy) -> np.ndarray:
        return self.md.to_team(period, club, np.asarray(xy, dtype=float))

    def outfield(self, club: str) -> np.ndarray:
        md = self.md
        return np.array([c for c in md.columns_of(club) if md.players[c] not in self.keepers])

    def space(self, period: int, i: int, col: int, club: str) -> float:
        pf = self.md.periods[period]
        opp = self.md.columns_of(self.md.other(club))
        d = np.linalg.norm(pf.xy[i, opp].astype(float) - pf.xy[i, col].astype(float), axis=1)
        return float(np.nanmin(d)) if not np.isnan(d).all() else 99.0

    def nearest_opponent(self, period: int, i: int, col: int, club: str) -> list[str]:
        pf = self.md.periods[period]
        opp = self.md.columns_of(self.md.other(club))
        d = np.linalg.norm(pf.xy[i, opp].astype(float) - pf.xy[i, col].astype(float), axis=1)
        return [] if np.isnan(d).all() else [self.md.players[int(opp[int(np.nanargmin(d))])]]

    def candidate(self, type_: str, period: int, club: str, t0: int, t1: int, creator: str, signals: list[Signal],
                  verdict: tuple[float, str], dragged: list[str], receiver: str | None, zone) -> Candidate:
        strength, status = verdict
        return Candidate(candidate_id="pending", match_id=self.md.match_id, period=period, t_start_ms=t0, t_end_ms=t1,
                         type=type_, team_id=club, creator_id=creator, dragged_ids=dragged, receiver_id=receiver,
                         gap_zone=zone, signals=signals, strength=round(strength, 3), status=status,
                         evidence_ids=sorted({eid for s in signals for eid in s.evidence_ids}))

    def receipt(self, e) -> tuple[int, int, int] | None:
        """(release frame, recipient column, receipt frame) of a completed pass, or None."""
        md = self.md
        if e.recipient_id is None or e.recipient_id not in md.players or not e.start_xy or not e.end_xy:
            return None
        pf = md.periods[e.period]
        rcol = md.players.index(e.recipient_id)
        i_rel = pf.index_of(e.t_ms)
        i_rec = _receipt(md, e.period, rcol, i_rel + 3)
        return None if i_rec is None else (i_rel, rcol, i_rec)


class SwitchOfPlayDetector(_EventDetector):
    """The ball goes across quickly, the block lags behind it, and the far player receives with room (PRD 12.7)."""

    type = "switch_of_play"
    trigger = "pass"

    def evaluate_pass(self, e, now_idx: int | None = None) -> Candidate | None:
        md, period, club = self.md, e.period, e.team_id
        got = self.receipt(e)
        if got is None or club is None:
            return None
        i_rel, rcol, i_rec = got
        if now_idx is not None and i_rec > now_idx:
            return None
        s, t = self.team_xy(period, club, e.start_xy), self.team_xy(period, club, e.end_xy)
        if abs(t[1] - s[1]) < 28.0 or abs(t[0] - s[0]) > 35.0:
            return None  # not across the pitch
        pf = md.periods[period]
        i_end = min(i_rec + 75, pf.n - 1)
        opp = self.outfield(md.other(club))
        ball_y = pf.ball[i_rel: i_end + 1, 1].astype(float)
        block_y = np.nanmean(pf.xy[i_rel: i_end + 1, opp, 1].astype(float), axis=1)
        k_rec = i_rec - i_rel
        ball_move, block_move = ball_y[k_rec] - ball_y[0], block_y[-1] - block_y[0]
        lag = 0.0
        if abs(ball_move) >= 1.0 and block_move * ball_move > 0:
            k_ball = int(np.argmax(np.abs(ball_y[: k_rec + 1] - ball_y[0]) >= 0.5 * abs(ball_move)))
            moved = (block_y - block_y[0]) * np.sign(block_move) >= 0.5 * abs(block_move)
            k_block = int(np.argmax(moved)) if moved.any() else len(block_y) - 1
            lag = (k_block - k_ball) / 25.0
        space = self.space(period, i_rec, rcol, club)
        signals = [
            Signal(name="block_shift_lag_s", value=round(lag, 1), threshold=1.5, unit="s",
                   evidence_ids=[e.event_id, md.frame_id(period, int(pf.t_ms[i_end]))]),
            Signal(name="winger_space_m", value=round(space, 1), threshold=5.0, unit="m",
                   evidence_ids=[md.frame_id(period, int(pf.t_ms[i_rec]))]),
        ]
        verdict = _finish(signals, now_idx is None)
        if verdict is None:
            return None
        rxy = pf.xy[i_rec, rcol].astype(float)
        return self.candidate(self.type, period, club, e.t_ms, int(pf.t_ms[i_rec]), e.recipient_id, signals, verdict,
                              self.nearest_opponent(period, i_rec, rcol, club), e.recipient_id,
                              _rect(float(rxy[0]), float(rxy[1]), 7.0, 7.0))


class PressBrokenDetector(_EventDetector):
    """A press commits four or more players near the ball, and one pass from inside it beats most of the team
    and leaves the attack outnumbering what is left (PRD 12.7)."""

    type = "press_broken"
    trigger = "pass"

    def evaluate_pass(self, e, now_idx: int | None = None) -> Candidate | None:
        md, period, club = self.md, e.period, e.team_id
        got = self.receipt(e)
        if got is None or club is None or e.player_id not in md.players:
            return None
        i_rel, rcol, i_rec = got
        if now_idx is not None and i_rec > now_idx:
            return None
        if self.team_xy(period, club, e.start_xy)[0] >= 52.5:
            return None  # breaking a press starts in our own half
        pf = md.periods[period]
        pcol = md.players.index(e.player_id)
        opp = self.outfield(md.other(club))
        d = np.linalg.norm(pf.xy[i_rel, opp].astype(float) - pf.xy[i_rel, pcol].astype(float), axis=1)
        committed = int(np.nansum(d < 22.0))
        ball = pf.ball[i_rec, :2].astype(float)
        bx = self.team_xy(period, club, ball)[0]
        opp_xy = pf.xy[i_rec, opp].astype(float)
        ok = ~np.isnan(opp_xy[:, 0])
        goal_side = self.team_xy(period, club, opp_xy[ok])[:, 0] > bx
        bypassed = int(ok.sum() - goal_side.sum())
        mine = pf.xy[i_rec, self.outfield(club)].astype(float)
        mine = mine[~np.isnan(mine[:, 0])]
        ahead = int(np.sum((self.team_xy(period, club, mine)[:, 0] >= bx - 2.0)
                           & (np.linalg.norm(mine - ball, axis=1) < 25.0)))
        near_def = int(np.sum(goal_side & (np.linalg.norm(opp_xy[ok] - ball, axis=1) < 25.0)))
        signals = [
            Signal(name="pressers_committed", value=float(committed), threshold=4.0, unit="players",
                   evidence_ids=[e.event_id, md.frame_id(period, int(pf.t_ms[i_rel]))]),
            Signal(name="defenders_bypassed", value=float(bypassed), threshold=6.0, unit="players",
                   evidence_ids=[md.frame_id(period, int(pf.t_ms[i_rec]))]),
            Signal(name="transition_2v3", value=1.0 if ahead >= 2 and near_def <= 3 else 0.0, threshold=1.0,
                   unit="bool", evidence_ids=[md.frame_id(period, int(pf.t_ms[i_rec]))]),
        ]
        verdict = _finish(signals, now_idx is None)
        if verdict is None:
            return None
        rxy = pf.xy[i_rec, rcol].astype(float)
        dragged = [md.players[int(opp[k])] for k in np.argsort(np.nan_to_num(d, nan=99.0))[:4]]
        return self.candidate(self.type, period, club, e.t_ms, int(pf.t_ms[i_rec]), e.recipient_id, signals, verdict,
                              dragged, e.recipient_id, _rect(float(rxy[0]), float(rxy[1]), 6.0, 6.0))


class PinningDetector(_EventDetector):
    """A teammate held two defenders for two seconds or more just before the pass, and the receiver got the ball
    with room (PRD 12.7)."""

    type = "pinning"
    trigger = "pass"

    def evaluate_pass(self, e, now_idx: int | None = None) -> Candidate | None:
        md, period, club = self.md, e.period, e.team_id
        got = self.receipt(e)
        if got is None or club is None:
            return None
        i_rel, rcol, i_rec = got
        if now_idx is not None and i_rec > now_idx:
            return None
        space = self.space(period, i_rec, rcol, club)
        if space < 3.0:
            return None
        pf = md.periods[period]
        opp = md.columns_of(md.other(club))
        passer = md.players.index(e.player_id) if e.player_id in md.players else -1
        best = (0.0, -1, -1)
        for col in self.outfield(club):
            if col in (rcol, passer):
                continue
            run = longest = 0
            end = -1
            for i in range(max(i_rel - 100, 0), i_rel + 1, 5):
                d = np.linalg.norm(pf.xy[i, opp].astype(float) - pf.xy[i, col].astype(float), axis=1)
                run = run + 1 if np.nansum(d < 5.0) >= 2 else 0
                if run > longest:
                    longest, end = run, i
            if longest * 0.2 > best[0] and end >= i_rel - 25:
                best = (longest * 0.2, int(col), end)
        pinned, pcol, end = best
        if pcol < 0:
            return None
        signals = [
            Signal(name="pinned_s", value=round(pinned, 1), threshold=2.0, unit="s",
                   evidence_ids=[md.frame_id(period, int(pf.t_ms[end]))]),
            Signal(name="receiver_space_m", value=round(space, 1), threshold=5.0, unit="m",
                   evidence_ids=[e.event_id, md.frame_id(period, int(pf.t_ms[i_rec]))]),
        ]
        verdict = _finish(signals, now_idx is None)
        if verdict is None:
            return None
        d = np.linalg.norm(pf.xy[end, opp].astype(float) - pf.xy[end, pcol].astype(float), axis=1)
        dragged = [md.players[int(opp[k])] for k in np.argsort(np.nan_to_num(d, nan=99.0))[:2]]
        rxy = pf.xy[i_rec, rcol].astype(float)
        t0 = int(pf.t_ms[max(end - int(pinned * 25), 0)])
        return self.candidate(self.type, period, club, t0, int(pf.t_ms[i_rec]), md.players[pcol], signals, verdict,
                              dragged, e.recipient_id, _rect(float(rxy[0]), float(rxy[1]), 6.0, 6.0))


class RestDefenceDetector(_EventDetector):
    """The ball is won with fewer than three of the other team behind it, and within 3 s the counter outnumbers
    them in a half-space (PRD 12.7, Rest defence exposed). The ball-winner is the creator."""

    type = "rest_defence_exposed"
    trigger = "turnover"

    def _in_half_space(self, period: int, club: str, xy: np.ndarray, bx: float, side: float) -> int:
        """Players in the half-space on one side, from just ahead of the ball to 26 m ahead of it."""
        xy = xy.astype(float)
        p = self.team_xy(period, club, xy[~np.isnan(xy[:, 0])])
        lateral = (p[:, 1] - 34.0) * side
        return int(np.sum((p[:, 0] >= bx + 2) & (p[:, 0] <= bx + 26) & (lateral >= 7) & (lateral <= 21)))

    def evaluate_turnover(self, e, now_idx: int | None = None) -> Candidate | None:
        md, period, club = self.md, e.period, e.team_id
        if club is None or e.player_id not in md.players:
            return None
        pf = md.periods[period]
        i = pf.index_of(e.t_ms)
        if now_idx is not None and i + 75 > now_idx:
            return None
        ball = pf.ball[i, :2].astype(float)
        bx = self.team_xy(period, club, ball)[0]
        if bx > 88:
            return None
        opp = self.outfield(md.other(club))
        opp_xy = pf.xy[i, opp].astype(float)
        opp_xy = opp_xy[~np.isnan(opp_xy[:, 0])]
        behind = int(np.sum(self.team_xy(period, club, opp_xy)[:, 0] > bx))
        mine_cols, opp_cols = md.columns_of(club), md.columns_of(md.other(club))
        overload, at = -9, i
        for k in range(i, min(i + 76, pf.n), 5):
            for side in (-1.0, 1.0):
                diff = (self._in_half_space(period, club, pf.xy[k, mine_cols], bx, side)
                        - self._in_half_space(period, club, pf.xy[k, opp_cols], bx, side))
                if diff > overload:
                    overload, at = diff, k
        signals = [
            Signal(name="cover_short", value=float(3 - behind), threshold=1.0, unit="players",
                   evidence_ids=[e.event_id, md.frame_id(period, e.t_ms)]),
            Signal(name="half_space_overload", value=float(max(overload, 0)), threshold=1.0, unit="players",
                   evidence_ids=[md.frame_id(period, int(pf.t_ms[at]))]),
        ]
        verdict = _finish(signals, now_idx is None)
        if verdict is None:
            return None
        return self.candidate(self.type, period, club, e.t_ms, int(pf.t_ms[min(i + 75, pf.n - 1)]), e.player_id,
                              signals, verdict, [], None, _rect(float(ball[0]), float(ball[1]), 13.0, 8.0))


VIEW_CONE = np.radians(70.0)
FULL_BACKS = ("RB", "LB", "RWB", "LWB")


def _angle(a: np.ndarray, b: np.ndarray) -> float:
    na, nb = float(np.linalg.norm(a)), float(np.linalg.norm(b))
    if na < 1e-6 or nb < 1e-6:
        return 0.0
    return float(np.arccos(np.clip(a @ b / (na * nb), -1.0, 1.0)))


def lane_probability(xy: np.ndarray, a: int, b: int, defenders: np.ndarray) -> float:
    """Chance a pass from column a reaches column b along the ground, from positions alone: a race between the
    ball (14 m/s) and each defender (6.5 m/s after a 0.3 s reaction) to points along the lane."""
    pa, pb = xy[a].astype(float), xy[b].astype(float)
    if np.isnan(pa).any() or np.isnan(pb).any():
        return 0.0
    dist = float(np.linalg.norm(pb - pa))
    fracs = np.linspace(0.15, 0.95, 9)
    pts = pa + fracs[:, None] * (pb - pa)
    t_ball = fracs * dist / 14.0
    p = 1.0
    for d in defenders:
        q = xy[d].astype(float)
        if np.isnan(q).any():
            continue
        t_def = 0.3 + np.linalg.norm(pts - q, axis=1) / 6.5
        p_int = float(np.max(1.0 / (1.0 + np.exp(-((t_ball - t_def) - 0.1) / 0.15))))
        p *= 1.0 - 0.9 * p_int
    return p


class BlindSideRunDetector(_EventDetector):
    """A runner starts outside a nearby defender's view cone, judged from the defender's body orientation, and
    gets three metres away from him within 1.5 s (PRD 12.7, Blind-side run)."""

    type = "blind_side_run"
    run_args = {"min_speed": 3.0, "min_frames": 15, "min_disp": 4.0}  # often a jog across his back, not a sprint

    def evaluate(self, run, now_idx: int | None = None) -> Candidate | None:
        md, period, club = self.md, run.period, run.club
        pf = md.periods[period]
        if self.possession.at(period, run.t0_ms) != club:
            return None
        i0 = max(run.i0 - 10, 0)  # just before he was moving fast enough to be detected
        i15 = i0 + 37
        if i15 >= pf.n or (now_idx is not None and i15 > now_idx):
            return None
        rcol = md.players.index(run.player_id)
        c0, c15 = pf.xy[i0, rcol].astype(float), pf.xy[i15, rcol].astype(float)
        ball = pf.ball[i0, :2].astype(float)
        best = None
        for col in self.outfield(md.other(club)):
            p0 = pf.xy[i0, col].astype(float)
            if np.isnan(p0).any() or not 1.5 <= float(np.linalg.norm(c0 - p0)) <= 8.0:
                continue
            facing = np.array([np.cos(pf.ori[i0, col]), np.sin(pf.ori[i0, col])])
            if _angle(facing, ball - p0) > np.radians(50.0):
                continue  # not watching the ball
            cone = _angle(facing, c0 - p0)
            growth = float(np.linalg.norm(c15 - pf.xy[i15, col].astype(float)) - np.linalg.norm(c0 - p0))
            if cone > VIEW_CONE and (best is None or growth > best[0]):
                best = (growth, int(col), cone)
        if best is None:
            return None
        growth, dcol, cone = best
        signals = [
            Signal(name="start_outside_view_cone", value=1.0, threshold=1.0, unit="bool",
                   evidence_ids=[md.frame_id(period, int(pf.t_ms[i0]))]),
            Signal(name="separation_growth_m", value=round(growth, 1), threshold=3.0, unit="m",
                   evidence_ids=[md.frame_id(period, int(pf.t_ms[i15]))]),
        ]
        verdict = _finish(signals, True)
        if verdict is None:
            return None
        return self.candidate(self.type, period, club, run.t0_ms, int(pf.t_ms[i15]), run.player_id, signals, verdict,
                              [md.players[dcol]], None, _rect(float(c15[0]), float(c15[1]), 6.0, 6.0))


class FalseNineDetector(_EventDetector):
    """A forward drops towards his own goal, the defender who was goal-side of him steps up with him, and the
    attackers' control of the space behind that defender grows (PRD 12.7, False 9 drop)."""

    type = "false_9_drop"
    run_args = {"min_speed": 4.0, "min_frames": 20, "min_disp": 8.0}  # a purposeful drop, seldom a sprint

    def evaluate(self, run, now_idx: int | None = None) -> Candidate | None:
        md, period, club = self.md, run.period, run.club
        pf = md.periods[period]
        if self.possession.at(period, run.t0_ms) != club:
            return None
        back = self.team_xy(period, club, run.end_xy)[0] - self.team_xy(period, club, run.start_xy)[0]
        if back > -8.0:
            return None  # a drop goes towards his own goal
        i0 = max(run.i0 - 10, 0)  # just before he was dropping fast enough to be detected
        i4 = min(i0 + 100, pf.n - 1)
        if now_idx is not None and i4 > now_idx:
            return None
        rcol = md.players.index(run.player_id)
        r0 = pf.xy[i0, rcol].astype(float)
        rx = self.team_xy(period, club, r0)[0]
        goal = np.array([105.0 if md.direction(period, club) > 0 else 0.0, 34.0])
        best = None
        for col in self.outfield(md.other(club)):
            p0 = pf.xy[i0, col].astype(float)
            if np.isnan(p0).any() or float(np.linalg.norm(p0 - r0)) > 6.0 or self.team_xy(period, club, p0)[0] < rx:
                continue
            seg = pf.xy[i0: i4 + 1, col].astype(float)
            disp = np.linalg.norm(seg - p0, axis=1)
            k = int(np.nanargmax(disp))
            follow = _angle(seg[k] - p0, pf.xy[i0 + k, rcol].astype(float) - r0)
            if follow < np.radians(75.0) and (best is None or disp[k] > best[0]):
                best = (float(disp[k]), int(col), p0)
        if best is None:
            return None
        step_up, dcol, p0 = best
        g = (goal - p0) / (float(np.linalg.norm(goal - p0)) or 1.0)
        centre = p0 + g * 9.0
        zone = _rect(float(centre[0]), float(centre[1]), 12.0, 8.0)
        cells = _zone_cells(zone)
        a0 = float(zone_control_at(md, club, period, i0, cells).sum())
        gain = max(float(zone_control_at(md, club, period, i, cells).sum()) - a0 for i in range(i0, i4 + 1, 5))
        signals = [
            Signal(name="cb_step_up_m", value=round(step_up, 1), threshold=10.0, unit="m",
                   evidence_ids=[md.frame_id(period, run.t0_ms)]),
            Signal(name="space_behind_gain_m2", value=round(gain, 0), threshold=150.0, unit="m2",
                   evidence_ids=[md.frame_id(period, int(pf.t_ms[i4]))]),
        ]
        verdict = _finish(signals, True)
        if verdict is None:
            return None
        return self.candidate(self.type, period, club, run.t0_ms, int(pf.t_ms[i4]), run.player_id, signals, verdict,
                              [md.players[dcol]], None, zone)


class CoverShadowDetector(_EventDetector):
    """Before a backward or sideways pass, a defender moved into the lane to an open teammate of the passer and the
    pass to him went from on to off (PRD 12.7, Cover shadow). The moment belongs to the defending team."""

    type = "cover_shadow"
    trigger = "pass"
    any_pass = True  # the backward ball is often cut out too

    def evaluate_pass(self, e, now_idx: int | None = None) -> Candidate | None:
        md, period, club = self.md, e.period, e.team_id
        if club is None or e.player_id not in md.players or not e.start_xy or not e.end_xy:
            return None
        if self.team_xy(period, club, e.end_xy)[0] - self.team_xy(period, club, e.start_xy)[0] > 3.0:
            return None  # the ball still went forward
        pf = md.periods[period]
        i_rel = pf.index_of(e.t_ms)
        pcol = md.players.index(e.player_id)
        # Only look back over the time the passer has had the ball.
        i_from = i_rel
        while i_from > max(i_rel - 150, 0) and float(np.linalg.norm(pf.ball[i_from - 1, :2] - pf.xy[i_from - 1, pcol])) < 2.0:
            i_from -= 1
        if i_rel - i_from < 15:
            return None
        defenders = self.outfield(md.other(club))
        recipient = md.players.index(e.recipient_id) if e.recipient_id in md.players else -1
        best = None
        for q in self.outfield(club):
            if q in (pcol, recipient):
                continue
            frames = list(range(i_from, i_rel + 1, 5))
            probs = [lane_probability(pf.xy[i], pcol, q, defenders) for i in frames]
            k = int(np.argmax(probs))
            if probs[k] < 0.6 or self.space(period, frames[k], int(q), club) < 5.0:
                continue
            drop = probs[k] - lane_probability(pf.xy[i_rel], pcol, q, defenders)
            if best is None or drop > best[0]:
                best = (drop, int(q), frames[k])
        if best is None:
            return None
        drop, qcol, i_open = best
        a, b = pf.xy[i_rel, pcol].astype(float), pf.xy[i_rel, qcol].astype(float)

        def lane_dist(i: int, col: int) -> float:
            pa, pb, p = pf.xy[i, pcol].astype(float), pf.xy[i, qcol].astype(float), pf.xy[i, col].astype(float)
            ab = pb - pa
            s = float(np.clip((p - pa) @ ab / max(float(ab @ ab), 1e-6), 0.0, 1.0))
            return float(np.linalg.norm(pa + s * ab - p))

        # A shadow is cast from inside the lane; the man closing down the passer is pressure, not a shadow.
        movers = [(lane_dist(i_open, d) - lane_dist(i_rel, d), int(d)) for d in defenders
                  if not np.isnan(pf.xy[i_rel, d, 0]) and lane_dist(i_rel, d) <= 2.5
                  and float(np.linalg.norm(pf.xy[i_rel, d] - a)) >= 3.0]
        if not movers:
            return None
        stepped = [d for moved, d in movers if moved >= 1.0]
        if not stepped:
            return None  # nobody stepped in: the lane was already shut
        # The shadow is his whose absence would reopen the lane most.
        others = [int(d) for d in defenders]
        dcol = max(stepped, key=lambda d: lane_probability(pf.xy[i_rel], pcol, qcol, [o for o in others if o != d]))
        signals = [
            Signal(name="pass_prob_drop_pts", value=round(100 * drop, 0), threshold=30.0, unit="pts",
                   evidence_ids=[md.frame_id(period, int(pf.t_ms[i_open])), md.frame_id(period, int(pf.t_ms[i_rel]))]),
            Signal(name="ball_backwards_or_sideways", value=1.0, threshold=1.0, unit="bool", evidence_ids=[e.event_id]),
        ]
        verdict = _finish(signals, now_idx is None)
        if verdict is None:
            return None
        mid = (a + b) / 2
        return self.candidate(self.type, period, md.other(club), int(pf.t_ms[i_open]), e.t_ms, md.players[dcol],
                              signals, verdict, [md.players[qcol]], None,
                              _rect(float(mid[0]), float(mid[1]), max(abs(b[0] - a[0]) / 2, 3.0),
                                    max(abs(b[1] - a[1]) / 2, 3.0)))


class RotationDetector(_EventDetector):
    """Three teammates swapped zones in the four seconds before a pass, at least one defender ended up on a
    different man, and the receiver came out of it with room (PRD 12.7, Rotation)."""

    type = "rotation"
    trigger = "pass"

    def evaluate_pass(self, e, now_idx: int | None = None) -> Candidate | None:
        club = e.team_id
        got = self.receipt(e)
        if got is None or club is None:
            return None
        i_rel, rcol, i_rec = got
        if now_idx is not None and i_rec > now_idx:
            return None
        for i_b in range(i_rel - 150, i_rel - 49, 10):
            if i_b < 0:
                continue
            cand = self._rotation_from(e, i_b, i_rel, rcol, i_rec, now_idx)
            if cand is not None:
                return cand
        return None

    def _rotation_from(self, e, i_b: int, i_rel: int, rcol: int, i_rec: int, now_idx: int | None) -> Candidate | None:
        md, period, club = self.md, e.period, e.team_id
        pf = md.periods[period]
        passer = md.players.index(e.player_id) if e.player_id in md.players else -1
        before, now = pf.xy[i_b].astype(float), pf.xy[i_rel].astype(float)
        mates = [int(c) for c in self.outfield(club) if c not in (rcol, passer) and not np.isnan(before[c, 0])
                 and float(np.linalg.norm(before[c] - before[rcol])) <= 20.0]
        opp = self.outfield(md.other(club))

        def marker(xy: np.ndarray, col: int) -> int:
            d = np.linalg.norm(xy[opp] - xy[col], axis=1)
            return int(opp[int(np.nanargmin(d))]) if not np.isnan(d).all() else -1

        for k, b in enumerate(mates):
            for c in mates[k + 1:]:
                trio = [rcol, b, c]
                for cycle in ((1, 2, 0), (2, 0, 1)):
                    if all(float(np.linalg.norm(now[trio[n]] - before[trio[cycle[n]]])) < 5.0 for n in range(3)):
                        switched = any(marker(before, p) != marker(now, p) for p in trio)
                        space = self.space(period, i_rec, rcol, club)
                        signals = [
                            Signal(name="zones_swapped", value=1.0, threshold=1.0, unit="bool",
                                   evidence_ids=[md.frame_id(period, int(pf.t_ms[i_b])),
                                                 md.frame_id(period, int(pf.t_ms[i_rel]))]),
                            Signal(name="marker_switch", value=1.0 if switched else 0.0, threshold=1.0, unit="bool",
                                   evidence_ids=[md.frame_id(period, int(pf.t_ms[i_rel]))]),
                            Signal(name="receiver_separation_m", value=round(space, 1), threshold=4.0, unit="m",
                                   evidence_ids=[e.event_id, md.frame_id(period, int(pf.t_ms[i_rec]))]),
                        ]
                        verdict = _finish(signals, now_idx is None)
                        if verdict is None:
                            return None
                        rxy = pf.xy[i_rec, rcol].astype(float)
                        return self.candidate(self.type, period, club, int(pf.t_ms[i_b]), int(pf.t_ms[i_rec]),
                                              e.recipient_id, signals, verdict, [], e.recipient_id,
                                              _rect(float(rxy[0]), float(rxy[1]), 10.0, 10.0))
        return None


class SetPieceScreenDetector(_EventDetector):
    """At a corner or a crossed free kick, a teammate stood in the target's marker's path to the ball, and the
    target met it with at least 2 m more room than when it was struck (PRD 12.7, Set-piece screen)."""

    type = "set_piece_screen"
    trigger = "pass"
    match_tolerance_ms = 5000  # the routine is set during the stoppage, a few seconds before the kick

    def evaluate_pass(self, e, now_idx: int | None = None) -> Candidate | None:
        md, period, club = self.md, e.period, e.team_id
        if club is None or e.recipient_id not in md.players or not e.end_xy:
            return None
        end = self.team_xy(e.period, club, e.end_xy)
        if e.subtype != "corner" and not (e.subtype == "free_kick" and end[0] > 88.5 and abs(end[1] - 34) < 20.16):
            return None  # a corner, or a free kick crossed into the box
        pf = md.periods[period]
        rcol = md.players.index(e.recipient_id)
        i_rel = pf.index_of(e.t_ms)
        i_rec = next((i for i in range(i_rel + 3, min(i_rel + 100, pf.n))
                      if float(np.linalg.norm(pf.ball[i, :2] - pf.xy[i, rcol])) < 2.0), None)
        if i_rec is None or (now_idx is not None and i_rec > now_idx):
            return None
        opp = self.outfield(md.other(club))
        d = np.linalg.norm(pf.xy[i_rel, opp].astype(float) - pf.xy[i_rel, rcol].astype(float), axis=1)
        if np.isnan(d).all():
            return None
        mcol = int(opp[int(np.nanargmin(d))])
        gain = self.space(period, i_rec, rcol, club) - float(np.nanmin(d))
        passer = md.players.index(e.player_id) if e.player_id in md.players else -1
        meet = pf.xy[i_rec, rcol].astype(float)

        def in_the_way(i: int, col: int) -> float:
            """How far a teammate is from the marker's path to where the target met the ball, if he's near him."""
            m, p = pf.xy[i, mcol].astype(float), pf.xy[i, col].astype(float)
            if np.isnan(p).any() or float(np.linalg.norm(p - m)) > 3.5:
                return np.inf
            mg = meet - m
            s = float(np.clip((p - m) @ mg / max(float(mg @ mg), 1e-6), 0.0, 1.0))
            return float(np.linalg.norm(m + s * mg - p))

        screen = None
        for col in md.columns_of(club):
            if col in (rcol, passer):
                continue
            close = min(in_the_way(i, int(col)) for i in range(i_rel, i_rec + 1, 3))
            if close < 1.5 and (screen is None or close < screen[0]):
                screen = (close, int(col))
        if screen is None:
            return None
        signals = [
            Signal(name="header_separation_gain_m", value=round(gain, 1), threshold=2.0, unit="m",
                   evidence_ids=[e.event_id, md.frame_id(period, int(pf.t_ms[i_rec]))]),
            Signal(name="screened", value=1.0, threshold=1.0, unit="bool",
                   evidence_ids=[md.frame_id(period, int(pf.t_ms[i_rec]))]),
        ]
        verdict = _finish(signals, now_idx is None)
        if verdict is None:
            return None
        rxy = pf.xy[i_rec, rcol].astype(float)
        return self.candidate(self.type, period, club, e.t_ms, int(pf.t_ms[i_rec]), md.players[screen[1]], signals,
                              verdict, [md.players[mcol]], e.recipient_id, _rect(float(rxy[0]), float(rxy[1]), 4.0, 4.0))


class _TeamDetector(_EventDetector):
    """Team moments play out over minutes: scanned over a whole period, matched to the answer key by team."""

    trigger = "period"
    team_moment = True

    def line_heights(self, period: int, club: str, step: int = 25) -> tuple[np.ndarray, np.ndarray]:
        """Every second the other club has the ball: the club's back-line height in its own frame (mean x' of its
        four deepest outfielders). Lines are measured out of possession."""
        md = self.md
        pf = md.periods[period]
        cols = self.outfield(club)
        other = md.other(club)
        idx = np.array([i for i in range(0, pf.n, step) if self.possession.at(period, int(pf.t_ms[i])) == other],
                       dtype=int)
        if idx.size == 0:
            return idx, np.array([])
        xy = pf.xy[idx][:, cols].astype(float)
        x = xy[..., 0] if md.direction(period, club) > 0 else 105.0 - xy[..., 0]
        x = np.where(np.isnan(x), np.inf, x)
        deepest = np.sort(x, axis=1)[:, :4]
        heights = np.where(np.isfinite(deepest).all(axis=1), deepest.mean(axis=1), np.nan)
        return idx, heights

    def final_third_share(self, period: int, club: str, t0: int, t1: int, side: float | None = None) -> float:
        """Share, in points, of final-third actions in [t0, t1] that are the club's (or, with a side, the club's
        share of its own final-third actions on that flank)."""
        md = self.md
        mine = theirs = on = 0
        for e in md.events_between(period, t0, t1):
            if e.type not in ("pass", "carry", "shot") or not e.start_xy or e.team_id is None:
                continue
            x, y = self.team_xy(period, e.team_id, e.start_xy)
            if x <= 70:
                continue
            if e.team_id == club:
                mine += 1
                on += side is not None and (y - 34.0) * side > 8
            else:
                theirs += 1
        if side is not None:
            return 100.0 * on / max(mine, 1)
        return 100.0 * mine / max(mine + theirs, 1)


class SpaceLostDetector(_TeamDetector):
    """A team's back line sits 8 m or more deeper for five minutes than in the five before, and the other team's
    share of final-third play swings up (PRD 12.7, Space lost)."""

    type = "space_lost"
    match_tolerance_ms = 120_000

    def evaluate_period(self, period: int, now_idx: int | None = None) -> list[Candidate]:
        md = self.md
        pf = md.periods[period]
        out = []
        for club in (md.home, md.away):
            idx, h = self.line_heights(period, club)
            if len(h) < 60:
                continue
            times = pf.t_ms[idx].astype(np.int64)
            t_mid = int(times[0]) + 300_000
            while t_mid + 300_000 <= int(pf.t_ms[-1]):
                if now_idx is not None and t_mid + 300_000 > int(pf.t_ms[min(now_idx, pf.n - 1)]):
                    break
                before = h[(times >= t_mid - 300_000) & (times < t_mid)]
                during = h[(times >= t_mid) & (times < t_mid + 300_000)]
                if len(before) >= 30 and len(during) >= 30:
                    drop = float(np.nanmean(before) - np.nanmean(during))
                    if drop >= 8.0:
                        cand = self._candidate(period, club, t_mid, drop)
                        if cand is not None:
                            out.append(cand)
                            t_mid += 300_000
                            continue
                t_mid += 30_000
        return out

    def _candidate(self, period: int, club: str, t_mid: int, drop: float) -> Candidate | None:
        md = self.md
        pf = md.periods[period]
        t0, t1 = t_mid - 300_000, t_mid + 300_000
        other = md.other(club)
        swing = self.final_third_share(period, other, t_mid, t1) - self.final_third_share(period, other, t0, t_mid)
        signals = [
            Signal(name="line_height_drop_m", value=round(drop, 1), threshold=8.0, unit="m",
                   evidence_ids=[md.frame_id(period, t_mid)]),
            Signal(name="drop_minutes", value=5.0, threshold=5.0, unit="min", evidence_ids=[md.frame_id(period, t1)]),
            Signal(name="field_tilt_swing_pts", value=round(swing, 0), threshold=10.0, unit="pts",
                   evidence_ids=[md.frame_id(period, t1)]),
        ]
        verdict = _finish(signals, True)
        if verdict is None:
            return None
        i = pf.index_of(t_mid)
        cols = self.outfield(club)
        x = pf.xy[i, cols, 0].astype(float)
        x = x if md.direction(period, club) > 0 else 105.0 - x
        cb = md.players[int(cols[int(np.nanargmin(x))])]
        return self.candidate(self.type, period, club, t_mid, t1, cb, signals, verdict, [], None, [])


class FatigueGapDetector(_TeamDetector):
    """Late in a match an opposing full-back's recovery runs slow by 15% or more and the team's attacks shift to
    his flank by 20 points or more (PRD 12.7, Fatigue gap)."""

    type = "fatigue_gap"
    match_tolerance_ms = 300_000

    def evaluate_period(self, period: int, now_idx: int | None = None) -> list[Candidate]:
        md = self.md
        pf = md.periods[period]
        roles = {e.player_id: e.role for sheet in (md.info.home, md.info.away) for e in sheet.lineup}
        out = []
        for club in (md.home, md.away):
            other = md.other(club)
            won = [e for e in md.events if e.period == period and e.team_id == club
                   and e.type in ("interception", "tackle") and e.outcome == "won"]
            for fb in (p for p in md.players if md.team_of[p] == other and roles.get(p) in FULL_BACKS):
                col = md.players.index(fb)
                rec = []
                for e in won:
                    i = pf.index_of(e.t_ms)
                    sp = pf.speed[i: min(i + 125, pf.n), col]
                    sp = sp[np.isfinite(sp)]
                    if sp.size > 10:
                        rec.append((e.t_ms, float(np.percentile(sp, 90))))
                if len(rec) < 6:
                    continue
                _, y = self.team_xy(period, club, pf.xy[pf.n // 2, col])
                side = 1.0 if y > 34 else -1.0
                times = np.array([r[0] for r in rec])
                speeds = np.array([r[1] for r in rec])
                total = sum(p.duration_ms for p in md.info.periods)
                offset = sum(p.duration_ms for p in md.info.periods if p.period < period)
                late = max(int(0.55 * total) - offset, int(pf.t_ms[0]) + 120_000)  # stoppage time included
                for t0 in range(late, int(pf.t_ms[-1]) - 300_000, 30_000):
                    before, during = speeds[times < t0], speeds[(times >= t0) & (times < t0 + 330_000)]
                    if len(before) < 3 or len(during) < 2:
                        continue
                    drop = 100.0 * (np.median(before) - np.median(during)) / max(np.median(before), 1e-6)
                    gain = (self.final_third_share(period, club, t0, t0 + 330_000, side)
                            - self.final_third_share(period, club, t0 - 600_000, t0, side))
                    if drop < 15.0 or gain < 20.0:
                        continue
                    signals = [
                        Signal(name="recovery_speed_drop_pct", value=round(float(drop), 0), threshold=15.0, unit="pct",
                               evidence_ids=[md.frame_id(period, t0)]),
                        Signal(name="flank_share_gain_pts", value=round(float(gain), 0), threshold=20.0, unit="pts",
                               evidence_ids=[md.frame_id(period, t0 + 330_000)]),
                    ]
                    verdict = _finish(signals, True)
                    out.append(self.candidate(self.type, period, club, t0, t0 + 330_000, fb, signals, verdict, [fb],
                                              None, []))
                    break
        return out


EXTRA_DETECTORS = {
    "switch_of_play": SwitchOfPlayDetector,
    "press_broken": PressBrokenDetector,
    "pinning": PinningDetector,
    "rest_defence_exposed": RestDefenceDetector,
    "blind_side_run": BlindSideRunDetector,
    "false_9_drop": FalseNineDetector,
    "cover_shadow": CoverShadowDetector,
    "rotation": RotationDetector,
    "set_piece_screen": SetPieceScreenDetector,
    "space_lost": SpaceLostDetector,
    "fatigue_gap": FatigueGapDetector,
}
DETECTORS.update(EXTRA_DETECTORS)
