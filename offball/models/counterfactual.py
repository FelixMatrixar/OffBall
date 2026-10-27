"""Counterfactual workers (PRD 10.10, 11.4, 12.9; ADR 0005): replay a moment in the match engine from the observed
state, with and without one player's decision, to measure what that decision caused.

The engine starts from what was observed at the moment's start: every player's position and velocity, the ball,
who has it, the score and which way each side attacks. The line-ups come from the published league (formation,
roles, numbers). The engine's hidden player attributes and club styles are never read: each player's top speed is
estimated from his own tracking before the moment, and everything else takes league-typical values, as it would for
a real match (PRD 12.9). The other players decide for themselves at every tick, so a defender follows a run only if
the run gives him a reason to.

The decision under test is the creator's. With it, the creator moves as he was observed to move; without it, he does
what the moment type says the alternative was: for a run, a rotation, a screen or a cover he holds his place in the
shape; for a switch of play the winger comes inside instead of holding the touchline; for a broken press or a pin
he drops towards the ball. Each side is replayed several times with different random draws, and the gap zone's
controlled area and value are measured at the instant the gap is used, with the same pitch-control model the
generator uses for its truth (`offball.models.pitch_control.control_fast`). Space Created is the difference of
the medians, with a 90% interval from resampling, and the creator's median path without the decision is the ghost.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

import numpy as np

from offball.core import DT, HALF_WIDTH
from offball.generator.engine.params import EngineParams
from offball.generator.engine.sim import Simulator
from offball.generator.engine.tactics import compute_anchors, offside_line_team
from offball.generator.league import (
    ARCHETYPES,
    PHYSICAL,
    ROLE_GROUP,
    TECHNICAL,
    Attributes,
    Club,
    ClubStyle,
    KitSet,
    League,
    Player,
)
from offball.models import epv
from offball.models.match_data import MatchData
from offball.models.metrics import _zone_cells, zone_control_at, zone_from
from offball.models.pitch_control import control_fast
from offball.models.runs import Possession

ROOT = Path(__file__).resolve().parents[2]
LEAGUE = ROOT / "datasets" / "league" / "league.json"
RERUNS = 16  # replays per side of the comparison
GHOST_STEP_MS = 500
OWNER_RADIUS_M = 1.5
START_SEARCH_MS = 2000
MIN_SPEED_FRAMES = 3000  # two minutes of tracking before a player's own top speed is trusted
GAP_GAIN = 0.40  # zone control gained that counts as the gap opening, as the generator counts it
# What the creator does instead, by moment type; anything else holds its place in the shape.
COME_INSIDE = {"switch_of_play"}
DROP_TO_BALL = {"press_broken", "pinning"}


@cache
def _public_clubs() -> dict[str, dict]:
    return {c["club_id"]: c for c in json.loads(LEAGUE.read_text(encoding="utf-8"))["clubs"]}


def _top_speed(md: MatchData, pid: str, period: int, idx: int) -> float | None:
    """A player's top speed so far in the match: the fastest his smoothed tracking has shown before the moment,
    once there are a few minutes of it (the showcase's striker shows 9.13 m/s against a true 9.3)."""
    col = md.players.index(pid)
    seen = [md.periods[p].speed[:, col] for p in md.periods if p < period]
    seen.append(md.periods[period].speed[:idx, col])
    speeds = np.concatenate(seen)
    speeds = speeds[~np.isnan(speeds)]
    return float(speeds.max()) if len(speeds) >= MIN_SPEED_FRAMES else None


def _attributes(md: MatchData, pid: str, role: str, period: int, idx: int) -> Attributes:
    """League-typical attributes for the role, with the top speed this player has shown."""
    base = TECHNICAL[ROLE_GROUP[role]]
    speed, accel = PHYSICAL[role]
    seen = _top_speed(md, pid, period, idx) if pid in md.players else None
    tech = {name: base.get(name, 0.5) for name in ("passing", "vision", "first_touch", "dribbling", "finishing",
                                                   "tackling", "scanning", "run_timing", "discipline", "composure",
                                                   "aerial")}
    return Attributes(top_speed=float(np.clip(seen or speed, 6.6, 9.9)), accel=accel, decel=accel * 1.25,
                      turn_rate=9.0, stamina=base.get("stamina", 0.68), decoy_tendency=base["decoy_tendency"],
                      decision_speed=0.5, work_rate=0.62, handling=base.get("handling", 0.0), **tech)


def observed_league(md: MatchData, period: int, idx: int) -> League:
    """The two clubs as anyone could know them: the published squads and formations, league-typical styles and
    attributes, and each player's observed top speed."""
    balanced = ARCHETYPES["balanced"]
    clubs = []
    for club_id in (md.home, md.away):
        c = _public_clubs()[club_id]
        style = ClubStyle(formation=c["formation"], press_height=balanced["press_height"],
                          press_intensity=balanced["press_intensity"], tempo=balanced["tempo"],
                          directness=balanced["directness"], width=balanced["width"],
                          line_height=balanced["line_height"], rest_defence=int(balanced["rest_defence"]),
                          build_up=str(balanced["build_up"]), rotation=balanced["rotation"], archetype="observed")
        players = []
        for p in c["squad"]:
            first, _, surname = p["name"].partition(" ")
            players.append(Player(p["player_id"], club_id, p["number"], first, surname or first, p["role"],
                                  p["foot"], p["age"], p["height_cm"],
                                  _attributes(md, p["player_id"], p["role"], period, idx)))
        clubs.append(Club(club_id, c["name"], c["short_name"], 0.6, style, KitSet(**c["kits"]), c["badge"], players))
    return League(seed=0, clubs=clubs, fixtures=[])


def _owner(md: MatchData, period: int, idx: int) -> str | None:
    """The player on the ball at a frame: within reach of it, with the ball on the ground."""
    pf = md.periods[period]
    ball = pf.ball[idx]
    if np.isnan(ball[:2]).any() or ball[2] >= 1.0:
        return None
    d = np.linalg.norm(pf.xy[idx].astype(float) - ball[:2].astype(float), axis=1)
    k = int(np.nanargmin(d)) if not np.isnan(d).all() else -1
    return md.players[k] if k >= 0 and d[k] <= OWNER_RADIUS_M else None


def start_frame(md: MatchData, period: int, t_ms: int, before_ms: int) -> int:
    """Where a replay starts: the first frame from t_ms on where someone has the ball, so the engine begins from
    a state it can read (a ball in flight carries a pass plan the tracking doesn't show). Within START_SEARCH_MS and
    before `before_ms`; t_ms itself when there is none."""
    pf = md.periods[period]
    a = pf.index_of(t_ms)
    last = min(pf.index_of(t_ms + START_SEARCH_MS), pf.index_of(before_ms) - 1)
    return next((i for i in range(a, last + 1) if _owner(md, period, i)), a)


def seed(md: MatchData, period: int, t_ms: int, rng_seed: int = 0) -> Simulator:
    """An engine at the observed state of frame t_ms, ready to step."""
    pf = md.periods[period]
    a = pf.index_of(t_ms)
    sim = Simulator(observed_league(md, period, a), md.home, md.away, md.match_id, rng_seed,
                    params=EngineParams.load(), home_direction=md.direction(1, md.home))
    sim.recording = False
    sim.period = period
    for side, club in enumerate((md.home, md.away)):
        sim.teams[side].direction = md.direction(period, club)
        sim.teams[side].score = sum(1 for e in md.events if e.type == "shot" and e.outcome == "goal"
                                    and e.team_id == club and (e.period, e.t_ms) < (period, int(pf.t_ms[a])))
    on = {pid for k, pid in enumerate(md.players) if not np.isnan(pf.xy[a, k, 0])}
    # Starters who have gone off hand their slot to whoever came on for their side.
    slotted = {sim.player[i].player_id for i in range(22) if sim.player[i].player_id in on}
    for i in range(22):
        if sim.player[i].player_id in on:
            continue
        club = sim.teams[sim.team_of[i]].club
        spare = next((p for p in club.players if p.player_id in on and p.player_id not in slotted), None)
        if spare is None:
            sim.active[i] = False
            continue
        slotted.add(spare.player_id)
        sim.player[i] = spare
        sim.slot_player[i] = sim.pidx[spare.player_id]
        sim._load_attributes(i, spare)
    sim.t = float(pf.t_ms[a]) / 1000.0
    sim.frame = int(pf.t_ms[a]) // 40
    vel = np.nan_to_num(pf.vel[a].astype(float))
    for i in range(22):
        if not sim.active[i]:
            continue
        col = md.players.index(sim.player[i].player_id)
        sim.pos[i] = pf.xy[a, col].astype(float)
        sim.vel[i] = vel[col]
        sim.v_wish[i] = vel[col]
        sim.ori[i] = float(np.nan_to_num(pf.ori[a, col]))
    sim.target = sim.pos.copy()
    sim.ball_pos = np.nan_to_num(pf.ball[a].astype(float))
    club = Possession(md).at(period, int(pf.t_ms[a]))
    sim.possession = (0 if club == md.home else 1) if club else -1
    # The ball goes to whoever has it, or else to the nearest player of the side in possession, at his feet.
    on_ball = _owner(md, period, a)
    if on_ball is not None:
        holder = sim.slot_of(on_ball)
    else:
        side = sim.possession if sim.possession >= 0 else 0
        near = sim.active_of(side)
        holder = min(near, key=lambda i: float(np.linalg.norm(sim.pos[i] - sim.ball_pos[:2])))
        sim.ball_pos = np.array([sim.pos[holder][0], sim.pos[holder][1], 0.0])
    sim.ball_vel = np.zeros(3)
    sim.owner, sim.last_touch, sim.ball_state = holder, holder, "owned"
    sim.possession = int(sim.team_of[holder])
    sim.carry_from = (sim.t, sim.pos[holder].copy())
    sim.anchor = np.vstack([compute_anchors(sim, 0), compute_anchors(sim, 1)])
    sim.offside_cache = [offside_line_team(sim, 0), offside_line_team(sim, 1)]
    sim.stoppage_s[period] = 1e6  # a replay never reaches the end of the half
    sim.next_decision[:] = sim.t
    return sim


@dataclass(frozen=True)
class Decision:
    """One player's choice, as an engine intent held for a while."""

    player_id: str
    intent: str  # run, support or anchor
    point: tuple[float, float] | None
    speed: float
    seconds: float


@dataclass(frozen=True)
class Observed:
    """The tracked world from the replay's start to the measurement, per engine slot: what the players the
    decision doesn't touch did, frame by frame."""

    xy: np.ndarray  # (frames, 22, 2)
    vel: np.ndarray  # (frames, 22, 2)
    ball: np.ndarray  # (frames, 3)
    owner: np.ndarray  # (frames,) slot on the ball, or -1


def observe(md: MatchData, sim: Simulator, period: int, a: int, b: int) -> Observed:
    pf = md.periods[period]
    cols = [md.players.index(sim.player[i].player_id) for i in range(22)]
    xy = pf.xy[a: b + 1][:, cols].astype(float)
    vel = np.nan_to_num(pf.vel[a: b + 1][:, cols].astype(float))
    slot = {sim.player[i].player_id: i for i in range(22) if sim.active[i]}
    owner = np.asarray([slot.get(_owner(md, period, f) or "", -1) for f in range(a, b + 1)])
    return Observed(xy, vel, np.nan_to_num(pf.ball[a: b + 1].astype(float)), owner)


@dataclass
class Replay:
    area_m2: float
    value: float
    control_gain: float
    track: list[tuple[int, float, float]] = field(default_factory=list)


def replay(snapshot: dict, base: Simulator, who: int, decision: Decision | None, free: list[int],
           observed: Observed, cells: np.ndarray, values: np.ndarray, side: int, control_start: float,
           rng_seed: int) -> Replay:
    """Play the engine on from the snapshot and measure the zone at the last observed frame. Only the `free` slots
    are the engine's to move; everyone else, and the ball, replays as tracked. With a decision, slot `who` is free
    and makes it; without one, he replays as tracked too. `who`'s path is kept for the ghost."""
    sim = base.fork(snapshot)
    sim.reseed(rng_seed)
    i = who
    if decision is not None:
        point = None if decision.point is None else np.asarray(decision.point, dtype=float)
        sim.set_intent(i, decision.intent, point, decision.speed, until=sim.t + decision.seconds,
                       data={"kind": "counterfactual"} if decision.intent == "run" else None)
        sim.lock_until[i] = sim.t + decision.seconds
    pinned = np.asarray([k for k in range(22) if k not in free and sim.active[k]])
    owner = int(sim.owner)
    track, every = [], max(1, int(round(GHOST_STEP_MS / 1000 / DT)))
    for f in range(1, len(observed.ball)):
        if (f - 1) % every == 0:
            track.append((sim.t_ms, round(float(sim.pos[i][0]), 2), round(float(sim.pos[i][1]), 2)))
        sim.step()
        sim.pos[pinned] = observed.xy[f, pinned]
        sim.vel[pinned] = observed.vel[f, pinned]
        owner = int(observed.owner[f]) if observed.owner[f] >= 0 else owner
        sim.ball_pos, sim.ball_vel = observed.ball[f].copy(), np.zeros(3)
        sim.flight, sim.flight_plan, sim.ball_state = None, {}, "owned"
        sim.owner, sim.possession = owner, int(sim.team_of[owner])
    att, dfn = sim.active_of(side), sim.active_of(1 - side)
    ctrl = control_fast(sim.pos[att], sim.vel[att], sim.pos[dfn], sim.vel[dfn], cells)
    track.append((sim.t_ms, round(float(sim.pos[i][0]), 2), round(float(sim.pos[i][1]), 2)))
    return Replay(float(ctrl.sum()), float((ctrl * values).mean()), float(ctrl.mean()) - control_start, track)


def instead(md: MatchData, moment_type: str, creator_id: str, period: int, t_start_ms: int,
            t_measure_ms: int) -> Decision:
    """What the creator would have done instead, for this type of moment."""
    pf = md.periods[period]
    a, b = pf.index_of(t_start_ms), pf.index_of(t_measure_ms)
    start = pf.xy[a, md.players.index(creator_id)].astype(float)
    seconds = max((b - a) * DT, 1.0) + 1.0
    if moment_type in COME_INSIDE:
        inside = HALF_WIDTH + np.sign(start[1] - HALF_WIDTH) * 4.0
        return Decision(creator_id, "support", (float(start[0]), float(inside)), 0.7, seconds)
    if moment_type in DROP_TO_BALL:
        mid = (start + pf.ball[a, :2].astype(float)) / 2
        return Decision(creator_id, "support", (float(mid[0]), float(mid[1])), 0.6, seconds)
    return Decision(creator_id, "anchor", None, 0.5, seconds)


@dataclass(frozen=True)
class Counterfactual:
    space_created_m2: float
    space_interval_m2: tuple[float, float]
    threat_created: float
    threat_interval: tuple[float, float]
    gap_opens_without: bool
    replays: int
    t_start_ms: int  # where the replays began: the first frame on from the moment's start with a player on the ball
    ghost: list[tuple[int, float, float]]  # the creator's median path without his decision: t_ms, x, y
    without_area_m2: list[float]


def _interval(actual: float, without: np.ndarray, rng: np.random.Generator, n: int = 400) -> tuple[float, float]:
    """90% interval of what happened minus the median without, by resampling the replays."""
    diffs = [actual - np.median(rng.choice(without, len(without))) for _ in range(n)]
    return float(np.percentile(diffs, 5)), float(np.percentile(diffs, 95))


def counterfactual(md: MatchData, moment_type: str, club_id: str, creator_id: str, dragged_ids: list[str],
                   period: int, t_start_ms: int, t_measure_ms: int, zone: list, replays: int = RERUNS,
                   rng_seed: int = 0) -> Counterfactual:
    """What the creator's decision caused in the zone by t_measure_ms: what happened, against replays in which he
    makes the alternative and the defenders he pulled are free to do otherwise. Everyone else replays as
    tracked: freeing more of the engine's players replaced real defending with the engine's, which doesn't
    reproduce how real defenders follow runs (the development moments scored worse every time)."""
    pf = md.periods[period]
    a = start_frame(md, period, t_start_ms, t_measure_ms)
    b = max(pf.index_of(t_measure_ms), a + 1)
    t0 = int(pf.t_ms[a])
    base = seed(md, period, t0, rng_seed)
    snapshot = base.checkpoint()
    observed = observe(md, base, period, a, b)
    side = 0 if club_id == md.home else 1
    cells = _zone_cells(zone_from({"zone": zone}))
    values = epv.value_at(md, period, club_id, cells)
    actual_ctrl = zone_control_at(md, club_id, period, b, cells)
    control_start = float(zone_control_at(md, club_id, period, a, cells).mean())
    who = base.slot_of(creator_id)
    free = [who, *(k for k in map(base.slot_of, dragged_ids) if k >= 0)]
    decision = instead(md, moment_type, creator_id, period, t0, int(pf.t_ms[b]))
    runs = [replay(snapshot, base, who, decision, free, observed, cells, values, side, control_start,
                   rng_seed * 1000 + k) for k in range(replays)]
    area, value = float(actual_ctrl.sum()), float((actual_ctrl * values).mean())
    wo_area = np.asarray([r.area_m2 for r in runs])
    wo_val = np.asarray([r.value for r in runs])
    rng = np.random.default_rng(rng_seed)
    ghost = []
    for n in range(min(len(r.track) for r in runs)):
        pts = np.asarray([r.track[n][1:] for r in runs])
        ghost.append((runs[0].track[n][0], round(float(np.median(pts[:, 0])), 1), round(float(np.median(pts[:, 1])), 1)))
    return Counterfactual(
        space_created_m2=round(area - float(np.median(wo_area)), 1),
        space_interval_m2=tuple(round(v, 1) for v in _interval(area, wo_area, rng)),
        threat_created=round(value - float(np.median(wo_val)), 4),
        threat_interval=tuple(round(v, 4) for v in _interval(value, wo_val, rng)),
        gap_opens_without=bool(np.mean([r.control_gain >= GAP_GAIN for r in runs]) > 0.5),
        replays=replays, t_start_ms=t0, ghost=ghost, without_area_m2=[round(v, 1) for v in wo_area])
