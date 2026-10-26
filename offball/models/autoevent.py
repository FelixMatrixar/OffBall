"""Auto-eventing from tracking (PRD 13): passes and shots found from the ball and the players alone.

A player has the ball when it is within reach and low enough to play. Each time the ball leaves a player, where it
goes next decides the event: towards the goal mouth, fast, from shooting range, it's a shot; to another player, it's
a pass, completed if that player is a team-mate; out of play, it's a pass that went out. The result is scored against
the generator's own events (`evaluate`); it isn't wired into the live pipeline, which reads the feed's events.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from offball.core import FRAME_MS, GOAL_WIDTH, HALF_WIDTH, PITCH_LENGTH, PITCH_WIDTH
from offball.models.match_data import MatchData

REACH_M = 1.2  # the ball is a player's when it's this close
PLAYABLE_Z = 1.6  # and no higher than this
MIN_HOLD = 2  # frames a player must keep it, so the ball brushing past doesn't count
SHOT_RANGE_M = 35.0
SHOT_SPEED = 11.0  # m/s off the foot
MIN_FLIGHT_M = 2.0  # a pass moves the ball at least this far between players (best F1 on the smoke set)
TOLERANCE_MS = 500


@dataclass
class Found:
    kind: str  # "pass" or "shot"
    period: int
    t_ms: int
    player_id: str
    outcome: str  # pass: complete, incomplete or out; shot: on its way


def _holders(md: MatchData, period: int) -> np.ndarray:
    """Per frame, the column of the player with the ball, or -1."""
    pf = md.periods[period]
    d = np.linalg.norm(pf.xy.astype(float) - pf.ball[:, None, :2].astype(float), axis=2)
    d = np.where(np.isnan(d), np.inf, d)
    col = np.argmin(d, axis=1)
    near = d[np.arange(len(col)), col] <= REACH_M
    low = np.nan_to_num(pf.ball[:, 2], nan=9.0) <= PLAYABLE_Z
    return np.where(near & low, col, -1)


def _segments(holder: np.ndarray) -> list[tuple[int, int, int]]:
    """(column, first frame, last frame) of each spell on the ball of at least MIN_HOLD frames."""
    out = []
    change = np.nonzero(np.diff(holder) != 0)[0] + 1
    starts = np.concatenate([[0], change])
    ends = np.concatenate([change - 1, [len(holder) - 1]])
    for a, b in zip(starts, ends, strict=True):
        if holder[a] >= 0 and b - a + 1 >= MIN_HOLD:
            if out and out[-1][0] == holder[a]:
                out[-1] = (out[-1][0], out[-1][1], int(b))  # the same player again after a touch: one spell
            else:
                out.append((int(holder[a]), int(a), int(b)))
    return out


def _is_shot(md: MatchData, period: int, club: str, i: int) -> bool:
    pf = md.periods[period]
    j = min(pf.n - 1, i + 4)
    if j <= i:
        return False
    a, b = (md.to_team(period, club, pf.ball[k, :2].astype(float)) for k in (i, j))
    v = (b - a) / ((j - i) * FRAME_MS / 1000)
    speed = float(np.linalg.norm(v))
    if np.isnan(speed) or speed < SHOT_SPEED or v[0] <= 0:
        return False
    if float(np.hypot(PITCH_LENGTH - a[0], HALF_WIDTH - a[1])) > SHOT_RANGE_M:
        return False
    y_at_line = a[1] + v[1] * (PITCH_LENGTH - a[0]) / v[0]
    return abs(y_at_line - HALF_WIDTH) <= GOAL_WIDTH / 2 + 4.0


def detect_events(md: MatchData) -> list[Found]:
    """Every pass and shot the tracking shows, in time order."""
    out = []
    for period, pf in sorted(md.periods.items()):
        spells = _segments(_holders(md, period))
        for k, (col, _, last) in enumerate(spells):
            pid = md.players[col]
            club = md.team_of[pid]
            t = int(pf.t_ms[last])
            if _is_shot(md, period, club, last):
                out.append(Found("shot", period, t, pid, "on_target_or_not"))
                continue
            nxt = spells[k + 1] if k + 1 < len(spells) else None
            if nxt is None or nxt[0] == col:
                continue  # kept it, or play ended with the ball at their feet
            flight = pf.ball[last: nxt[1] + 1, :2].astype(float)
            if np.linalg.norm(flight[-1] - flight[0]) < MIN_FLIGHT_M:
                continue  # won in a tackle or knocked off a foot, not passed
            gone = bool(((flight[:, 0] < 0) | (flight[:, 0] > PITCH_LENGTH) | (flight[:, 1] < 0)
                         | (flight[:, 1] > PITCH_WIDTH)).any())
            receiver_club = md.team_of[md.players[nxt[0]]]
            outcome = "out" if gone else "complete" if receiver_club == club else "incomplete"
            out.append(Found("pass", period, t, pid, outcome))
    return sorted(out, key=lambda f: (f.period, f.t_ms))


def _match(found: list[Found], truth: list[tuple[int, int, str]]) -> int:
    """Greedy one-to-one matching by period, player and time within TOLERANCE_MS."""
    used: set[int] = set()
    hits = 0
    for f in found:
        best = None
        for k, (p, t, pid) in enumerate(truth):
            if k in used or p != f.period or pid != f.player_id:
                continue
            gap = abs(t - f.t_ms)
            if gap <= TOLERANCE_MS and (best is None or gap < best[1]):
                best = (k, gap)
        if best is not None:
            used.add(best[0])
            hits += 1
    return hits


def evaluate(matches: list[MatchData]) -> dict:
    """Precision, recall and F1 for passes and shots against the generator's events."""
    totals = {"pass": [0, 0, 0], "shot": [0, 0, 0]}  # found, truth, matched
    for md in matches:
        found = detect_events(md)
        for kind in totals:
            mine = [f for f in found if f.kind == kind]
            truth = [(e.period, e.t_ms, e.player_id) for e in md.events if e.type == kind and e.player_id
                     and e.period in md.periods]
            totals[kind][0] += len(mine)
            totals[kind][1] += len(truth)
            totals[kind][2] += _match(mine, truth)
    scores = {}
    for kind, (n_found, n_truth, matched) in totals.items():
        precision = matched / n_found if n_found else 0.0
        recall = matched / n_truth if n_truth else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        scores[kind] = {"found": n_found, "generator": n_truth, "matched": matched, "precision": precision,
                        "recall": recall, "f1": f1}
    return {"tolerance_ms": TOLERANCE_MS, "scores": scores}
