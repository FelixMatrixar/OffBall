"""Possession timeline and off-ball run detection from observed tracking (PRD 13)."""

from __future__ import annotations

import bisect
from dataclasses import dataclass

import numpy as np

from offball.models.match_data import MatchData

POSSESSING_TYPES = {"pass", "carry", "shot", "clearance"}
WINNING_TYPES = {"interception", "tackle"}


class Possession:
    """Which club has the ball at any instant, from the event stream."""

    def __init__(self, md: MatchData) -> None:
        self.times: dict[int, list[int]] = {}
        self.clubs: dict[int, list[str]] = {}
        for e in md.events:
            club = None
            if e.type in POSSESSING_TYPES or (e.type in WINNING_TYPES and e.outcome == "won"):
                club = e.team_id
            if club is None:
                continue
            self.times.setdefault(e.period, []).append(e.t_ms)
            self.clubs.setdefault(e.period, []).append(club)

    def at(self, period: int, t_ms: int) -> str | None:
        times = self.times.get(period, [])
        k = bisect.bisect_right(times, t_ms) - 1
        return self.clubs[period][k] if k >= 0 else None


@dataclass
class Run:
    player_id: str
    club: str
    period: int
    i0: int
    i1: int
    t0_ms: int
    t1_ms: int
    start_xy: np.ndarray
    end_xy: np.ndarray
    max_speed: float

    @property
    def displacement(self) -> np.ndarray:
        return self.end_xy - self.start_xy


def detect_runs(md: MatchData, period: int, i_from: int = 0, i_to: int | None = None, min_speed: float = 5.0,
                min_frames: int = 30, min_disp: float = 8.0, onset_speed: float = 2.5) -> list[Run]:
    """Segments where a player moves faster than min_speed for at least min_frames and covers min_disp metres."""
    pf = md.periods[period]
    i_to = pf.n if i_to is None else min(i_to, pf.n)
    speed = np.nan_to_num(pf.speed[i_from:i_to])
    runs = []
    for col, pid in enumerate(md.players):
        fast = speed[:, col] >= min_speed
        if not fast.any():
            continue
        edges = np.diff(np.concatenate([[0], fast.astype(np.int8), [0]]))
        starts = np.nonzero(edges == 1)[0]
        ends = np.nonzero(edges == -1)[0] - 1
        for a, b in zip(starts, ends, strict=True):
            if b - a + 1 < min_frames:
                continue
            # Walk back to the onset: where the player started accelerating out of a jog.
            while a > 0 and speed[a - 1, col] > onset_speed and speed[a - 1, col] <= speed[a, col] + 0.05:
                a -= 1
            ia, ib = i_from + a, i_from + b
            p0 = pf.xy[ia, col].astype(float)
            p1 = pf.xy[ib, col].astype(float)
            if np.isnan(p0).any() or np.isnan(p1).any() or float(np.linalg.norm(p1 - p0)) < min_disp:
                continue
            runs.append(Run(pid, md.team_of[pid], period, ia, ib, int(pf.t_ms[ia]), int(pf.t_ms[ib]), p0, p1,
                            float(speed[a: b + 1, col].max())))
    return runs
