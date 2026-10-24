"""Observed match data as arrays: what the interpret service, the MCP tools and the Tactician read.

Only public files are read here (match.json, events.jsonl, tracking.parquet). Nothing in this module may
touch the held-out truth store.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

from offball.contracts import Event, MatchInfo
from offball.core import FRAME_MS, HZ, PITCH_LENGTH, PITCH_WIDTH, frame_ref


@dataclass
class PeriodFrames:
    period: int
    t_ms: np.ndarray  # (T,)
    xy: np.ndarray  # (T, P, 2), NaN when a player is off the pitch
    ori: np.ndarray  # (T, P)
    ball: np.ndarray  # (T, 3)

    @property
    def n(self) -> int:
        return len(self.t_ms)

    @cached_property
    def vel(self) -> np.ndarray:
        """(T, P, 2) velocities from smoothed central differences."""
        return smoothed_velocity(self.xy)

    @cached_property
    def speed(self) -> np.ndarray:
        return np.linalg.norm(self.vel, axis=2)

    def index_of(self, t_ms: int) -> int:
        """Index of the frame nearest t_ms. Frames may start later than kick-off, as a live window does."""
        t0 = int(self.t_ms[0]) if self.n else 0
        return int(np.clip(round((t_ms - t0) / FRAME_MS), 0, max(self.n - 1, 0)))


def smoothed_velocity(xy: np.ndarray, window: int = 5) -> np.ndarray:
    """Central differences over +-2 frames, then a short moving average; gaps stay NaN."""
    vel = np.full_like(xy, np.nan)
    k = 2
    vel[k:-k] = (xy[2 * k:] - xy[: -2 * k]) / (2 * k / HZ)
    if window > 1:
        kernel = np.ones(window) / window
        flat = vel.reshape(vel.shape[0], -1)
        out = np.empty_like(flat)
        for c in range(flat.shape[1]):
            col = flat[:, c]
            ok = ~np.isnan(col)
            if ok.sum() < window:
                out[:, c] = col
                continue
            filled = np.where(ok, col, 0.0)
            num = np.convolve(filled, kernel, mode="same")
            den = np.convolve(ok.astype(float), kernel, mode="same")
            with np.errstate(invalid="ignore", divide="ignore"):
                out[:, c] = np.where(ok, num / np.maximum(den, 1e-9), np.nan)
        vel = out.reshape(vel.shape)
    return vel


@dataclass
class MatchData:
    info: MatchInfo
    events: list[Event]
    players: list[str]
    team_of: dict[str, str]
    periods: dict[int, PeriodFrames] = field(default_factory=dict)

    @property
    def match_id(self) -> str:
        return self.info.match_id

    @property
    def home(self) -> str:
        return self.info.home.club_id

    @property
    def away(self) -> str:
        return self.info.away.club_id

    def other(self, club: str) -> str:
        return self.away if club == self.home else self.home

    def direction(self, period: int, club: str) -> int:
        """+1 when the club attacks towards x = 105 in this period."""
        p = next(p for p in self.info.periods if p.period == period)
        return 1 if p.attacks_left_to_right == club else -1

    def to_team(self, period: int, club: str, xy: np.ndarray) -> np.ndarray:
        """Absolute -> team frame (the club attacks towards x' = 105)."""
        if self.direction(period, club) > 0:
            return xy
        out = np.array(xy, dtype=float, copy=True)
        out[..., 0] = PITCH_LENGTH - out[..., 0]
        out[..., 1] = PITCH_WIDTH - out[..., 1]
        return out

    def columns_of(self, club: str) -> np.ndarray:
        return np.array([k for k, p in enumerate(self.players) if self.team_of[p] == club])

    def player_name(self, pid: str) -> str:
        for sheet in (self.info.home, self.info.away):
            for entry in sheet.lineup:
                if entry.player_id == pid:
                    return entry.name
        return pid

    def player_number(self, pid: str) -> int:
        return int(pid.rsplit("-", 1)[1])

    def club_name(self, club: str) -> str:
        return self.info.home.name if club == self.home else self.info.away.name

    def frame_id(self, period: int, t_ms: int) -> str:
        return frame_ref(self.match_id, period, t_ms // FRAME_MS)

    def events_between(self, period: int, t0: int, t1: int) -> list[Event]:
        return [e for e in self.events if e.period == period and t0 <= e.t_ms <= t1]

    @classmethod
    def load(cls, match_dir: Path) -> MatchData:
        info = MatchInfo.model_validate_json((match_dir / "match.json").read_text(encoding="utf-8"))
        events = [Event.model_validate_json(line) for line in
                  (match_dir / "events.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
        table = pq.read_table(match_dir / "tracking.parquet")
        return cls.from_table(info, events, table)

    @classmethod
    def from_table(cls, info: MatchInfo, events: list[Event], table) -> MatchData:
        names = table.column_names
        players = sorted({n[:-2] for n in names if n.endswith("_x") and not n.startswith("ball")})
        team_of = {p: p.split("-")[0] for p in players}
        period_col = table.column("period").to_numpy()
        data = cls(info=info, events=events, players=players, team_of=team_of)
        for period in np.unique(period_col):
            sel = np.nonzero(period_col == period)[0]
            sub = table.take(sel)
            n = len(sel)
            xy = np.empty((n, len(players), 2), dtype=np.float32)
            ori = np.empty((n, len(players)), dtype=np.float32)
            for k, pid in enumerate(players):
                xy[:, k, 0] = sub.column(f"{pid}_x").to_numpy(zero_copy_only=False)
                xy[:, k, 1] = sub.column(f"{pid}_y").to_numpy(zero_copy_only=False)
                ori[:, k] = sub.column(f"{pid}_o").to_numpy(zero_copy_only=False)
            ball = np.stack([sub.column(c).to_numpy(zero_copy_only=False) for c in ("ball_x", "ball_y", "ball_z")], axis=1)
            data.periods[int(period)] = PeriodFrames(int(period), sub.column("t_ms").to_numpy(), xy, ori, ball)
        return data


def load_info(match_dir: Path) -> MatchInfo:
    return MatchInfo.model_validate(json.loads((match_dir / "match.json").read_text(encoding="utf-8")))
