"""Space value (PRD 13): what having the ball at each part of the pitch is worth, as the chance the possession ends
in a goal.

The surface is a possession-value grid in the spirit of Fernández et al. (2021), with their three components: from
each zone a team shoots, passes or carries, and the zone's value is the chance of scoring from a shot there plus
the value of where its passes and carries go, solved as a Markov chain (the expected-threat construction). The
shot component uses the xG model at the zone, so it never needs goals from every zone; the pass and carry
components count successful moves between zones, and a move that loses the ball is worth nothing to its team.

It learns from events only (`offball.models.train` fits it on the calibration matches) and works in the team frame,
attacking towards x = 105. `surface` weights it by pitch control for one frame: the value of the ball reaching each
cell, for the side that would control it. Validated against realized possession outcomes (PRD 19.2: expected
calibration error 0.02 or less).
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache
from pathlib import Path

import numpy as np

from offball.contracts import Event
from offball.core import PITCH_LENGTH, PITCH_WIDTH
from offball.models.match_data import MatchData
from offball.models.metrics import MetricResult, _frames, metric, zone_control_at

ARTIFACT = Path(__file__).parent / "artifacts" / "epv.npz"
NX, NY = 16, 12  # zones along and across the pitch
PRIOR = 5.0  # pseudo-actions that pull thin zones towards the league-wide rates
ITERATIONS = 60
MOVES = ("pass", "carry")


@dataclass(frozen=True)
class Surface:
    """The value grid and its components, each (NY, NX) in the team frame, row 0 at y = 0."""

    value: np.ndarray
    shot: np.ndarray
    passing: np.ndarray
    carrying: np.ndarray

    def at(self, x: np.ndarray | float, y: np.ndarray | float, part: str = "value") -> np.ndarray:
        """Bilinear interpolation between zone centres, for team-frame points (x towards the goal at 105)."""
        grid = getattr(self, part)
        fx = np.clip(np.asarray(x, dtype=float) / (PITCH_LENGTH / NX) - 0.5, 0, NX - 1)
        fy = np.clip(np.asarray(y, dtype=float) / (PITCH_WIDTH / NY) - 0.5, 0, NY - 1)
        x0, y0 = np.floor(fx).astype(int), np.floor(fy).astype(int)
        x1, y1 = np.minimum(x0 + 1, NX - 1), np.minimum(y0 + 1, NY - 1)
        ax, ay = fx - x0, fy - y0
        return ((1 - ax) * (1 - ay) * grid[y0, x0] + ax * (1 - ay) * grid[y0, x1]
                + (1 - ax) * ay * grid[y1, x0] + ax * ay * grid[y1, x1])


def zone(x: float, y: float) -> int:
    """The flat zone index of a team-frame point."""
    ix = min(max(int(x / (PITCH_LENGTH / NX)), 0), NX - 1)
    iy = min(max(int(y / (PITCH_WIDTH / NY)), 0), NY - 1)
    return iy * NX + ix


def zone_centres() -> np.ndarray:
    """(NY * NX, 2) team-frame centres, in flat zone order."""
    xs = (np.arange(NX) + 0.5) * PITCH_LENGTH / NX
    ys = (np.arange(NY) + 0.5) * PITCH_WIDTH / NY
    gx, gy = np.meshgrid(xs, ys)
    return np.stack([gx.ravel(), gy.ravel()], axis=1)


def team_xy(md: MatchData, e: Event, xy: tuple[float, float] | list[float]) -> tuple[float, float]:
    """An event's point in its own team's frame."""
    p = md.to_team(e.period, e.team_id, np.asarray(xy, dtype=float))
    return float(p[0]), float(p[1])


@dataclass
class Counts:
    """Actions per zone, gathered over training matches."""

    shots: np.ndarray
    xg: np.ndarray  # summed xG of the shots
    moves: dict[str, np.ndarray]  # attempted passes and carries
    to: dict[str, np.ndarray]  # successful moves, zone -> zone

    @classmethod
    def empty(cls) -> Counts:
        n = NX * NY
        return cls(np.zeros(n), np.zeros(n), {k: np.zeros(n) for k in MOVES}, {k: np.zeros((n, n)) for k in MOVES})

    def add(self, md: MatchData, shot_xg) -> None:
        for e in md.events:
            if e.team_id is None or not e.start_xy or e.type not in ("shot", *MOVES):
                continue
            z = zone(*team_xy(md, e, e.start_xy))
            if e.type == "shot":
                self.shots[z] += 1
                self.xg[z] += shot_xg(md, e)
                continue
            self.moves[e.type][z] += 1
            if e.end_xy and e.outcome == "complete":
                self.to[e.type][z, zone(*team_xy(md, e, e.end_xy))] += 1


def solve(counts: Counts, centre_xg: np.ndarray) -> Surface:
    """The value of each zone: shoot, pass or carry, iterated to its fixed point."""
    total = counts.shots + sum(counts.moves.values())
    league = {k: counts.moves[k].sum() / max(total.sum(), 1) for k in MOVES}
    league_shot = counts.shots.sum() / max(total.sum(), 1)
    denom = total + PRIOR
    p_shot = (counts.shots + PRIOR * league_shot) / denom
    p_move = {k: (counts.moves[k] + PRIOR * league[k]) / denom for k in MOVES}
    # A zone's shots are worth their mean xG, or the model's xG at its centre where few were taken.
    goal = (counts.xg + PRIOR * centre_xg) / (counts.shots + PRIOR)
    trans = {k: counts.to[k] / np.maximum(counts.moves[k], 1)[:, None] for k in MOVES}
    value = np.zeros(NX * NY)
    for _ in range(ITERATIONS):
        value = p_shot * goal + sum(p_move[k] * (trans[k] @ value) for k in MOVES)
    shape = (NY, NX)
    return Surface(value.reshape(shape), (p_shot * goal).reshape(shape),
                   (p_move["pass"] * (trans["pass"] @ value)).reshape(shape),
                   (p_move["carry"] * (trans["carry"] @ value)).reshape(shape))


def save(surface: Surface, path: Path = ARTIFACT) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez(path, value=surface.value, shot=surface.shot, passing=surface.passing, carrying=surface.carrying)


@cache
def model() -> Surface:
    if not ARTIFACT.exists():
        raise FileNotFoundError(f"No space value model at {ARTIFACT}; run `uv run python -m offball.models.train`")
    with np.load(ARTIFACT) as f:
        return Surface(f["value"], f["shot"], f["passing"], f["carrying"])


def value_at(md: MatchData, period: int, club: str, xy: np.ndarray) -> np.ndarray:
    """Space value of absolute pitch points for `club`, which attacks the goal its direction gives."""
    t = md.to_team(period, club, np.asarray(xy, dtype=float))
    return model().at(t[..., 0], t[..., 1])


def surface(md: MatchData, period: int, idx: int, club: str, cells: np.ndarray) -> np.ndarray:
    """The value of the ball reaching each cell, for `club`: its control there times the space value."""
    return zone_control_at(md, club, period, idx, cells) * value_at(md, period, club, cells)


@metric("space_value", "EPV", "Space value where a player or the ball is at an instant: the chance the possession "
        "ends in a goal, from the space value model, for the given club", {"club_id": "str", "period": "int",
        "t_ms": "int", "player_id": "optional str (the ball when absent)"}, decimals=3)
def space_value(md: MatchData, club_id: str, period: int, t_ms: int, player_id: str | None = None) -> MetricResult:
    pf = md.periods[period]
    i = pf.index_of(t_ms)
    if player_id is None:
        xy = pf.ball[i, :2].astype(float)
    else:
        xy = pf.xy[i, md.players.index(player_id)].astype(float)
    if np.isnan(xy).any():
        raise ValueError("no position at that instant")
    params = {"club_id": club_id, "period": period, "t_ms": t_ms, **({"player_id": player_id} if player_id else {})}
    return MetricResult("space_value", float(value_at(md, period, club_id, xy)), "EPV", _frames(md, period, i), params)
