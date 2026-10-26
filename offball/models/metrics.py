"""Named, deterministic metrics (PRD 13, 14.7).

Every number an agent puts in a caption comes from one of these, through the `compute_metric` tool, so the
Fact-checker can recompute it exactly. Each result carries its unit and the evidence IDs it was computed from.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from offball.core import FRAME_MS, HSR_MPS, PITCH_WIDTH, SPRINT_MPS
from offball.models.match_data import MatchData
from offball.models.pitch_control import control_fast


@dataclass
class MetricResult:
    name: str
    value: float
    unit: str
    evidence_ids: list[str]
    params: dict[str, Any]
    details: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "value": self.value, "unit": self.unit, "evidence_ids": self.evidence_ids,
                "params": self.params, "details": self.details}


@dataclass(frozen=True)
class MetricSpec:
    name: str
    unit: str
    description: str
    params: dict[str, str]
    fn: Callable[..., MetricResult]
    decimals: int = 1


REGISTRY: dict[str, MetricSpec] = {}


def metric(name: str, unit: str, description: str, params: dict[str, str], decimals: int = 1):
    def wrap(fn: Callable[..., MetricResult]):
        REGISTRY[name] = MetricSpec(name, unit, description, params, fn, decimals)
        return fn
    return wrap


def compute(md: MatchData, name: str, **params: Any) -> MetricResult:
    """Compute a named metric. Raises KeyError for unknown metrics and ValueError for bad parameters."""
    spec = REGISTRY[name]
    missing = [p for p in spec.params if p not in params and not spec.params[p].startswith("optional")]
    if missing:
        raise ValueError(f"{name} needs parameters: {missing}")
    result = spec.fn(md, **params)
    result.value = round(float(result.value), spec.decimals)
    return result


# ------------------------------------------------------------------------------------------------ helpers


def _col(md: MatchData, pid: str) -> int:
    try:
        return md.players.index(pid)
    except ValueError as exc:
        raise ValueError(f"Unknown player {pid}") from exc


def _window(md: MatchData, period: int, t0: int, t1: int) -> tuple[int, int]:
    pf = md.periods[period]
    a, b = pf.index_of(t0), pf.index_of(t1)
    if b < a:
        raise ValueError("t_end_ms must not be before t_start_ms")
    return a, b


def _frames(md: MatchData, period: int, *idx: int) -> list[str]:
    pf = md.periods[period]
    return [md.frame_id(period, int(pf.t_ms[i])) for i in idx]


def zone_from(params: dict[str, Any]) -> list[tuple[float, float]]:
    zone = params.get("zone")
    if not zone or len(zone) < 3:
        raise ValueError("zone must be a polygon of at least 3 [x, y] points")
    return [(float(x), float(y)) for x, y in zone]


def _zone_cells(zone: list[tuple[float, float]], step: float = 1.0) -> np.ndarray:
    xs = [p[0] for p in zone]
    ys = [p[1] for p in zone]
    gx = np.arange(min(xs) + step / 2, max(xs), step)
    gy = np.arange(min(ys) + step / 2, max(ys), step)
    mx, my = np.meshgrid(gx, gy)
    return np.stack([mx.ravel(), my.ravel()], axis=1)


def zone_control_at(md: MatchData, club: str, period: int, idx: int, cells: np.ndarray,
                    override: dict[int, np.ndarray] | None = None) -> np.ndarray:
    """Control of `club` over cells at frame idx; `override` moves players (column -> xy) for ghost estimates."""
    pf = md.periods[period]
    xy = pf.xy[idx].astype(float).copy()
    vel = np.nan_to_num(pf.vel[idx].astype(float))
    if override:
        for col, pos in override.items():
            xy[col] = pos
            vel[col] = 0.0
    att = [c for c in md.columns_of(club) if not np.isnan(xy[c, 0])]
    dfn = [c for c in md.columns_of(md.other(club)) if not np.isnan(xy[c, 0])]
    return control_fast(xy[att], vel[att], xy[dfn], vel[dfn], cells)


# ------------------------------------------------------------------------------------------------ movement


@metric("displacement_m", "m", "How far a player moved from where they were at t_start_ms, at most, during the window",
        {"player_id": "str", "period": "int", "t_start_ms": "int", "t_end_ms": "int"})
def displacement_m(md: MatchData, player_id: str, period: int, t_start_ms: int, t_end_ms: int) -> MetricResult:
    a, b = _window(md, period, t_start_ms, t_end_ms)
    col = _col(md, player_id)
    xy = md.periods[period].xy[a: b + 1, col].astype(float)
    d = np.linalg.norm(xy - xy[0], axis=1)
    k = int(np.nanargmax(d))
    return MetricResult("displacement_m", float(np.nanmax(d)), "m", _frames(md, period, a, a + k),
                        {"player_id": player_id, "period": period, "t_start_ms": t_start_ms, "t_end_ms": t_end_ms})


@metric("run_length_m", "m", "Distance a player covered during the window",
        {"player_id": "str", "period": "int", "t_start_ms": "int", "t_end_ms": "int"})
def run_length_m(md: MatchData, player_id: str, period: int, t_start_ms: int, t_end_ms: int) -> MetricResult:
    a, b = _window(md, period, t_start_ms, t_end_ms)
    col = _col(md, player_id)
    xy = md.periods[period].xy[a: b + 1, col].astype(float)
    length = float(np.nansum(np.linalg.norm(np.diff(xy, axis=0), axis=1)))
    return MetricResult("run_length_m", length, "m", _frames(md, period, a, b),
                        {"player_id": player_id, "period": period, "t_start_ms": t_start_ms, "t_end_ms": t_end_ms})


@metric("top_speed_kmh", "km/h", "A player's highest speed during the window",
        {"player_id": "str", "period": "int", "t_start_ms": "int", "t_end_ms": "int"})
def top_speed_kmh(md: MatchData, player_id: str, period: int, t_start_ms: int, t_end_ms: int) -> MetricResult:
    a, b = _window(md, period, t_start_ms, t_end_ms)
    col = _col(md, player_id)
    sp = md.periods[period].speed[a: b + 1, col]
    k = int(np.nanargmax(sp))
    return MetricResult("top_speed_kmh", float(np.nanmax(sp)) * 3.6, "km/h", _frames(md, period, a + k),
                        {"player_id": player_id, "period": period, "t_start_ms": t_start_ms, "t_end_ms": t_end_ms})


@metric("distance_between_m", "m", "Distance between two players at an instant",
        {"player_a": "str", "player_b": "str", "period": "int", "t_ms": "int"})
def distance_between_m(md: MatchData, player_a: str, player_b: str, period: int, t_ms: int) -> MetricResult:
    pf = md.periods[period]
    i = pf.index_of(t_ms)
    d = float(np.linalg.norm(pf.xy[i, _col(md, player_a)].astype(float) - pf.xy[i, _col(md, player_b)].astype(float)))
    return MetricResult("distance_between_m", d, "m", _frames(md, period, i),
                        {"player_a": player_a, "player_b": player_b, "period": period, "t_ms": t_ms})


@metric("distance_covered_km", "km", "Distance a player has covered, optionally up to a time in a period",
        {"player_id": "str", "period": "optional int", "t_end_ms": "optional int"}, decimals=2)
def distance_covered_km(md: MatchData, player_id: str, period: int | None = None, t_end_ms: int | None = None) -> MetricResult:
    col = _col(md, player_id)
    total, ev = 0.0, []
    for p, pf in sorted(md.periods.items()):
        if period is not None and p > period:
            break
        end = pf.index_of(t_end_ms) if (period == p and t_end_ms is not None) else pf.n - 1
        xy = pf.xy[: end + 1, col].astype(float)
        total += float(np.nansum(np.linalg.norm(np.diff(xy, axis=0), axis=1)))
        ev = _frames(md, p, end)
    return MetricResult("distance_covered_km", total / 1000, "km", ev,
                        {"player_id": player_id, "period": period, "t_end_ms": t_end_ms})


@metric("sprints", "count", "Sprints above 25.2 km/h lasting at least one second",
        {"player_id": "str", "period": "optional int", "t_end_ms": "optional int"}, decimals=0)
def sprints(md: MatchData, player_id: str, period: int | None = None, t_end_ms: int | None = None) -> MetricResult:
    col = _col(md, player_id)
    count, ev = 0, []
    for p, pf in sorted(md.periods.items()):
        if period is not None and p > period:
            break
        end = pf.index_of(t_end_ms) if (period == p and t_end_ms is not None) else pf.n - 1
        fast = np.nan_to_num(pf.speed[: end + 1, col]) > SPRINT_MPS
        runs = _segments(fast, min_len=25)
        count += len(runs)
        ev += [md.frame_id(p, int(pf.t_ms[a])) for a, _ in runs[-3:]]
    return MetricResult("sprints", count, "count", ev, {"player_id": player_id, "period": period, "t_end_ms": t_end_ms})


@metric("high_speed_running_m", "m", "Distance above 19.8 km/h",
        {"player_id": "str", "period": "optional int", "t_end_ms": "optional int"}, decimals=0)
def high_speed_running_m(md: MatchData, player_id: str, period: int | None = None, t_end_ms: int | None = None) -> MetricResult:
    col = _col(md, player_id)
    total = 0.0
    for p, pf in sorted(md.periods.items()):
        if period is not None and p > period:
            break
        end = pf.index_of(t_end_ms) if (period == p and t_end_ms is not None) else pf.n - 1
        sp = np.nan_to_num(pf.speed[: end + 1, col])
        total += float((sp[sp > HSR_MPS] * FRAME_MS / 1000).sum())
    return MetricResult("high_speed_running_m", total, "m", [], {"player_id": player_id, "period": period})


def _segments(mask: np.ndarray, min_len: int) -> list[tuple[int, int]]:
    out, start = [], None
    for i, m in enumerate(mask):
        if m and start is None:
            start = i
        elif not m and start is not None:
            if i - start >= min_len:
                out.append((start, i - 1))
            start = None
    if start is not None and len(mask) - start >= min_len:
        out.append((start, len(mask) - 1))
    return out


# ------------------------------------------------------------------------------------------------ space


@metric("zone_control_pct", "%", "Share of a zone a club controls at an instant (pitch control)",
        {"club_id": "str", "period": "int", "t_ms": "int", "zone": "polygon"}, decimals=0)
def zone_control_pct(md: MatchData, club_id: str, period: int, t_ms: int, zone: list) -> MetricResult:
    z = zone_from({"zone": zone})
    i = md.periods[period].index_of(t_ms)
    ctrl = zone_control_at(md, club_id, period, i, _zone_cells(z))
    return MetricResult("zone_control_pct", float(ctrl.mean() * 100), "%", _frames(md, period, i),
                        {"club_id": club_id, "period": period, "t_ms": t_ms, "zone": zone})


@metric("zone_control_gain_pts", "pts", "Change in a club's control of a zone between two instants",
        {"club_id": "str", "period": "int", "t_start_ms": "int", "t_end_ms": "int", "zone": "polygon"}, decimals=0)
def zone_control_gain_pts(md: MatchData, club_id: str, period: int, t_start_ms: int, t_end_ms: int, zone: list) -> MetricResult:
    z = zone_from({"zone": zone})
    cells = _zone_cells(z)
    pf = md.periods[period]
    a, b = pf.index_of(t_start_ms), pf.index_of(t_end_ms)
    c0 = zone_control_at(md, club_id, period, a, cells).mean()
    c1 = zone_control_at(md, club_id, period, b, cells).mean()
    return MetricResult("zone_control_gain_pts", float((c1 - c0) * 100), "pts", _frames(md, period, a, b),
                        {"club_id": club_id, "period": period, "t_start_ms": t_start_ms, "t_end_ms": t_end_ms,
                         "zone": zone}, {"before_pct": round(c0 * 100), "after_pct": round(c1 * 100)})


@metric("space_created_m2", "m²",
        "Space a defender's movement handed the attackers: zone area the club controls now, against a ghost "
        "where the defender stayed where he was at t_start_ms",
        {"club_id": "str", "defender_id": "str", "period": "int", "t_start_ms": "int", "t_end_ms": "int", "zone": "polygon"},
        decimals=0)
def space_created_m2(md: MatchData, club_id: str, defender_id: str, period: int, t_start_ms: int, t_end_ms: int,
                     zone: list) -> MetricResult:
    z = zone_from({"zone": zone})
    cells = _zone_cells(z)
    pf = md.periods[period]
    a, b = pf.index_of(t_start_ms), pf.index_of(t_end_ms)
    col = _col(md, defender_id)
    actual = zone_control_at(md, club_id, period, b, cells)
    ghost = zone_control_at(md, club_id, period, b, cells, override={col: pf.xy[a, col].astype(float)})
    created = float((actual - ghost).sum())  # 1 m cells
    return MetricResult("space_created_m2", max(created, 0.0), "m²", _frames(md, period, a, b),
                        {"club_id": club_id, "defender_id": defender_id, "period": period, "t_start_ms": t_start_ms,
                         "t_end_ms": t_end_ms, "zone": zone})


@metric("line_height_m", "m", "Average distance of a club's back four from its own goal line",
        {"club_id": "str", "period": "int", "t_ms": "int"})
def line_height_m(md: MatchData, club_id: str, period: int, t_ms: int) -> MetricResult:
    pf = md.periods[period]
    i = pf.index_of(t_ms)
    cols = md.columns_of(club_id)
    xy = pf.xy[i, cols].astype(float)
    ok = ~np.isnan(xy[:, 0])
    xt = md.to_team(period, club_id, xy[ok])[:, 0]
    back = np.sort(xt)[1:5]  # skip the keeper
    return MetricResult("line_height_m", float(back.mean()), "m", _frames(md, period, i),
                        {"club_id": club_id, "period": period, "t_ms": t_ms})


@metric("team_width_m", "m", "Width of a club's outfield shape (5th to 95th percentile)",
        {"club_id": "str", "period": "int", "t_ms": "int"})
def team_width_m(md: MatchData, club_id: str, period: int, t_ms: int) -> MetricResult:
    pf = md.periods[period]
    i = pf.index_of(t_ms)
    xy = pf.xy[i, md.columns_of(club_id)].astype(float)
    y = xy[~np.isnan(xy[:, 1]), 1]
    width = float(np.percentile(y, 95) - np.percentile(y, 5)) if len(y) else 0.0
    return MetricResult("team_width_m", min(width, PITCH_WIDTH), "m", _frames(md, period, i),
                        {"club_id": club_id, "period": period, "t_ms": t_ms})


# ------------------------------------------------------------------------------------------------ events


def _event(md: MatchData, event_id: str):
    for e in md.events:
        if e.event_id == event_id:
            return e
    raise ValueError(f"Unknown event {event_id}")


@metric("pass_distance_m", "m", "Length of a pass", {"event_id": "str"})
def pass_distance_m(md: MatchData, event_id: str) -> MetricResult:
    e = _event(md, event_id)
    if e.type != "pass" or not e.start_xy or not e.end_xy:
        raise ValueError(f"{event_id} is not a pass")
    d = float(np.hypot(e.end_xy[0] - e.start_xy[0], e.end_xy[1] - e.start_xy[1]))
    return MetricResult("pass_distance_m", d, "m", [event_id], {"event_id": event_id})


@metric("ball_speed_kmh", "km/h", "Speed of the ball as it left the player's foot", {"event_id": "str"}, decimals=0)
def ball_speed_kmh(md: MatchData, event_id: str) -> MetricResult:
    e = _event(md, event_id)
    if e.ball_speed_mps is None:
        raise ValueError(f"{event_id} has no ball speed")
    return MetricResult("ball_speed_kmh", e.ball_speed_mps * 3.6, "km/h", [event_id], {"event_id": event_id})


@metric("passes_completed", "count", "Completed passes by a club or player, optionally up to a time",
        {"club_id": "optional str", "player_id": "optional str", "period": "optional int", "t_end_ms": "optional int"},
        decimals=0)
def passes_completed(md: MatchData, club_id: str | None = None, player_id: str | None = None,
                     period: int | None = None, t_end_ms: int | None = None) -> MetricResult:
    evs = _filter_events(md, "pass", club_id, player_id, period, t_end_ms)
    done = [e for e in evs if e.outcome == "complete"]
    return MetricResult("passes_completed", len(done), "count", [e.event_id for e in done[-5:]],
                        {"club_id": club_id, "player_id": player_id, "period": period, "t_end_ms": t_end_ms},
                        {"attempted": len(evs)})


@metric("pass_completion_pct", "%", "Pass completion rate of a club or player, optionally up to a time",
        {"club_id": "optional str", "player_id": "optional str", "period": "optional int", "t_end_ms": "optional int"},
        decimals=0)
def pass_completion_pct(md: MatchData, club_id: str | None = None, player_id: str | None = None,
                        period: int | None = None, t_end_ms: int | None = None) -> MetricResult:
    evs = _filter_events(md, "pass", club_id, player_id, period, t_end_ms)
    done = sum(e.outcome == "complete" for e in evs)
    pct = 100.0 * done / len(evs) if evs else 0.0
    return MetricResult("pass_completion_pct", pct, "%", [e.event_id for e in evs[-5:]],
                        {"club_id": club_id, "player_id": player_id, "period": period, "t_end_ms": t_end_ms},
                        {"attempted": len(evs), "completed": done})


@metric("shots", "count", "Shots by a club or player, optionally up to a time",
        {"club_id": "optional str", "player_id": "optional str", "period": "optional int", "t_end_ms": "optional int"},
        decimals=0)
def shots(md: MatchData, club_id: str | None = None, player_id: str | None = None, period: int | None = None,
          t_end_ms: int | None = None) -> MetricResult:
    evs = _filter_events(md, "shot", club_id, player_id, period, t_end_ms)
    return MetricResult("shots", len(evs), "count", [e.event_id for e in evs],
                        {"club_id": club_id, "player_id": player_id, "period": period, "t_end_ms": t_end_ms},
                        {"goals": sum(e.outcome == "goal" for e in evs)})


@metric("goals", "count", "Goals by a club or player, optionally up to a time",
        {"club_id": "optional str", "player_id": "optional str", "period": "optional int", "t_end_ms": "optional int"},
        decimals=0)
def goals(md: MatchData, club_id: str | None = None, player_id: str | None = None, period: int | None = None,
          t_end_ms: int | None = None) -> MetricResult:
    evs = [e for e in _filter_events(md, "shot", club_id, player_id, period, t_end_ms) if e.outcome == "goal"]
    return MetricResult("goals", len(evs), "count", [e.event_id for e in evs],
                        {"club_id": club_id, "player_id": player_id, "period": period, "t_end_ms": t_end_ms})


def _filter_events(md: MatchData, type_: str, club_id: str | None, player_id: str | None, period: int | None,
                   t_end_ms: int | None) -> list:
    out = []
    for e in md.events:
        if e.type != type_:
            continue
        if club_id and e.team_id != club_id:
            continue
        if player_id and e.player_id != player_id:
            continue
        if period is not None and (e.period > period or (e.period == period and t_end_ms is not None and e.t_ms > t_end_ms)):
            continue
        out.append(e)
    return out


def catalogue() -> list[dict[str, Any]]:
    """The metric catalogue, as the compute_metric tool describes it to agents."""
    return [{"name": s.name, "unit": s.unit, "description": s.description, "params": s.params} for s in REGISTRY.values()]


def moment_beats(md: MatchData, period: int, club: str, start_ms: int, dragged: str, receiver: str,
                 zone: list[tuple[float, float]]) -> dict[str, int | None]:
    """When each beat of a decoy-run goal happens, in ms of the period clock, read from the data alone: the run
    starts; the dragged defender is 2 m off his spot; the attackers' control of the gap he leaves is up 30 points,
    open enough to play into; the pass to the receiver; his shot; and the ball crossing the goal line. None for a
    beat that never came."""
    pf = md.periods[period]
    i0 = pf.index_of(start_ms)
    beats: dict[str, int | None] = {"run": start_ms, "follow": None, "gap": None, "pass": None, "shot": None,
                                    "goal": None}
    dcol = md.players.index(dragged)
    spot = pf.xy[i0, dcol].astype(float)
    cells = _zone_cells(zone)
    base = zone_control_at(md, club, period, i0, cells).mean()
    for i in range(i0, min(i0 + 10 * 25, pf.n)):
        if beats["follow"] is None and float(np.linalg.norm(pf.xy[i, dcol] - spot)) >= 2.0:
            beats["follow"] = int(pf.t_ms[i])
        if beats["gap"] is None and zone_control_at(md, club, period, i, cells).mean() - base >= 0.30:
            beats["gap"] = int(pf.t_ms[i])
        if beats["follow"] is not None and beats["gap"] is not None:
            break
    later = md.events_between(period, start_ms, start_ms + 15_000)
    passes = [e for e in later if e.type == "pass" and e.team_id == club and e.recipient_id == receiver]
    if passes:
        beats["pass"] = passes[0].t_ms
        shots = [e for e in later if e.type == "shot" and e.player_id == receiver and e.t_ms >= passes[0].t_ms]
        if shots:
            beats["shot"] = shots[0].t_ms
            goal_x = 105.0 if md.direction(period, club) > 0 else 0.0
            for i in range(pf.index_of(shots[0].t_ms), min(pf.index_of(shots[0].t_ms) + 5 * 25, pf.n)):
                if (pf.ball[i, 0] - goal_x) * (1 if goal_x > 0 else -1) >= 0:
                    beats["goal"] = int(pf.t_ms[i])
                    break
    return beats


# The learned models register their metrics too (PRD 13): pass difficulty and xG.
import offball.models.pass_difficulty  # noqa: E402, F401
import offball.models.xg  # noqa: E402, F401
