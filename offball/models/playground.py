"""Play it out: the match engine from a position a viewer sets, with the orders they or the coach give.

A viewer stops a match, moves players and the ball, and gives orders. An attacker runs or supports to a spot; the
carrier carries the ball to a spot, passes to a teammate or shoots; a player told to pass or shoot does it when the
ball reaches him. A defender presses the carrier, marks or tracks an attacker, covers a teammate, or holds a spot.
Everyone else decides for himself, as the engine's players always do, from league-typical attributes (ADR 0008).

The position plays out several times with different random draws. Each run is kept at 80 ms, every player and the
ball, so the app can animate any of them, with what happened: a goal, a save, a block, a miss, the ball lost, or
the ball kept. A shot's chance quality is the engine's own probability of scoring it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np

from offball.core import DT
from offball.generator.engine.geometry import L, W
from offball.generator.engine.sim import Simulator
from offball.generator.engine.tactics import compute_anchors, offside_line_team
from offball.models import counterfactual as CF
from offball.models.match_data import MatchData

ATTACK_ACTIONS = ("run", "support", "carry", "pass", "shoot")
DEFEND_ACTIONS = ("press", "mark", "track", "cover", "hold")
Action = Literal["run", "support", "carry", "pass", "shoot", "press", "mark", "track", "cover", "hold"]
RUNS = 8
SHOT_OUTCOMES = ("goal", "saved", "blocked", "off_target")
SECONDS = 8.0
RECORD_EVERY = 2  # steps between kept frames: 80 ms
AFTER_END_S = 1.5  # play on this long after a shot or a lost ball, so the end reads on screen


@dataclass(frozen=True)
class Order:
    player_id: str
    action: Action
    to_xy: tuple[float, float] | None = None
    target_id: str | None = None
    at_s: float = 0.0


def _clip(xy) -> np.ndarray:
    return np.array([float(np.clip(xy[0], 0.5, L - 0.5)), float(np.clip(xy[1], 0.5, W - 0.5))])


def setup(md: MatchData, period: int, t_ms: int, positions: dict[str, tuple[float, float]],
          ball_owner: str | None, rng_seed: int = 0) -> Simulator:
    """The engine at the tracked frame, with the players the viewer moved where they put them, standing, and the
    ball at the feet of whoever they gave it to."""
    sim = CF.seed(md, period, t_ms, rng_seed)
    for pid, xy in positions.items():
        i = sim.slot_of(pid)
        if i < 0:
            continue
        sim.pos[i] = _clip(xy)
        sim.vel[i] = 0.0
        sim.v_wish[i] = 0.0
    sim.target = sim.pos.copy()
    holder = sim.slot_of(ball_owner) if ball_owner else sim.owner
    if holder < 0:
        holder = sim.owner
    sim.owner, sim.last_touch, sim.ball_state = holder, holder, "owned"
    sim.ball_pos = np.array([sim.pos[holder][0], sim.pos[holder][1], 0.0])
    sim.ball_vel = np.zeros(3)
    sim.possession = int(sim.team_of[holder])
    sim.carry_from = (sim.t, sim.pos[holder].copy())
    sim.anchor = np.vstack([compute_anchors(sim, 0), compute_anchors(sim, 1)])
    sim.offside_cache = [offside_line_team(sim, 0), offside_line_team(sim, 1)]
    sim.next_decision[:] = sim.t
    for team in sim.teams:  # nobody comes off in a few seconds of play
        team.sub_windows = []
    return sim


def check_orders(sim: Simulator, orders: list[Order]) -> list[str]:
    """What is wrong with a set of orders for this position, if anything."""
    attack = sim.possession
    problems = []
    for k, o in enumerate(orders):
        i = sim.slot_of(o.player_id)
        where = f"order {k} ({o.player_id} {o.action})"
        if i < 0:
            problems.append(f"{where}: no such player on the pitch")
            continue
        side_attacks = int(sim.team_of[i]) == attack
        if side_attacks and o.action not in ATTACK_ACTIONS:
            problems.append(f"{where}: {o.player_id} is attacking; attackers can {', '.join(ATTACK_ACTIONS)}")
        if not side_attacks and o.action not in DEFEND_ACTIONS:
            problems.append(f"{where}: {o.player_id} is defending; defenders can {', '.join(DEFEND_ACTIONS)}")
        if o.action in ("run", "support", "carry", "hold") and o.to_xy is None:
            problems.append(f"{where}: needs to_xy, the spot")
        if o.action in ("pass", "mark", "track", "cover"):
            j = sim.slot_of(o.target_id or "")
            if j < 0:
                problems.append(f"{where}: needs target_id, a player on the pitch")
            elif o.action == "pass" and (j == i or int(sim.team_of[j]) != int(sim.team_of[i])):
                problems.append(f"{where}: a pass goes to a teammate")
            elif o.action in ("mark", "track") and int(sim.team_of[j]) == int(sim.team_of[i]):
                problems.append(f"{where}: {o.action} an attacker, not a teammate")
            elif o.action == "cover" and int(sim.team_of[j]) != int(sim.team_of[i]):
                problems.append(f"{where}: cover a teammate")
        receives = any(p.action == "pass" and p.target_id == o.player_id for p in orders)
        if o.action == "carry" and i != sim.owner and not receives:
            problems.append(f"{where}: only the player on the ball, or one a pass is ordered to, can carry it")
        if not 0 <= o.at_s <= SECONDS:
            problems.append(f"{where}: at_s runs from 0 to {SECONDS:g}")
    return problems


def _apply(sim: Simulator, o: Order, end_t: float, next_on_ball: float | None = None) -> None:
    i = sim.slot_of(o.player_id)
    if i < 0:
        return
    point = _clip(o.to_xy) if o.to_xy is not None else None
    if o.action in ("run", "support", "carry"):
        speed = {"run": 0.95, "support": 0.7, "carry": 0.8}[o.action]
        dist = float(np.linalg.norm(point - sim.pos[i]))
        dur = min(end_t - sim.t, dist / max(1.0, speed * float(sim.vmax[i])) + 0.6)
        if o.action == "carry" and sim.owner != i:
            return  # the ball has gone; nothing to carry
        if o.action == "carry" and next_on_ball is not None:
            dur = max(dur, next_on_ball - sim.t)  # he carries to the spot, then keeps it there until his pass or shot
        sim.set_intent(i, o.action, point, speed, until=sim.t + dur, data={"kind": "playground"})
        sim.lock_until[i] = sim.t + dur
    elif o.action in ("pass", "shoot"):
        j = sim.slot_of(o.target_id or "")
        # The directive waits for the ball: the carrier acts at his next decision, a teammate when it reaches him.
        sim.directives[i] = {"action": "pass", "to": j, "hold": True} if o.action == "pass" else {"action": "shoot"}
        sim.lock_until[i] = sim.t
        sim.next_decision[i] = sim.t
    elif o.action == "press":
        sim.set_intent(i, "press", None, 0.95, until=end_t)
        sim.lock_until[i] = end_t
    elif o.action in ("mark", "track", "cover"):
        sim.set_intent(i, o.action, None, 0.9, until=end_t, data={"who": sim.slot_of(o.target_id or "")})
        sim.lock_until[i] = end_t
    elif o.action == "hold":
        sim.set_intent(i, "keep", point, 0.75, until=end_t)
        sim.lock_until[i] = end_t


def _start(sim: Simulator, orders: list[Order], t0: float) -> list[Order]:
    """Orders that take effect from the first instant, applied now; the rest come back to be applied on time.

    A pass or shot by anyone but the carrier waits for the ball to reach him, whenever that is. The carrier's timed
    pass is a directive that waits for its moment while he shields the ball, as the engine's players do under
    pressure; his timed shot holds him where he is until then.
    """
    i = sim.owner
    carries = any(o.action == "carry" and sim.slot_of(o.player_id) == i for o in orders)
    receivers = {o.player_id for o in orders if o.action == "carry" and sim.slot_of(o.player_id) != i}
    later = []
    for o in orders:
        k = sim.slot_of(o.player_id)
        if o.player_id in receivers:
            continue  # a receiver's carry, and what he does after it, wait for the ball: see _run
        if o.action in ("pass", "shoot") and k != i:
            _apply(sim, o, t0)
        elif o.action == "pass" and k == i and o.at_s > 0 and not carries:
            fire = t0 + o.at_s
            sim.directives[i] = {"action": "pass", "to": sim.slot_of(o.target_id or ""), "hold": True,
                                 "when": lambda s_, fire=fire: s_.t >= fire - 1e-9}
            sim.next_decision[i] = sim.t
        elif o.action == "shoot" and k == i and o.at_s > 0 and not carries:
            sim.set_intent(i, "keep", sim.pos[i].copy(), 0.3, until=t0 + o.at_s)
            sim.lock_until[i] = t0 + o.at_s
            later.append(o)
        else:
            later.append(o)
    return later


def _run(base: Simulator, snap: dict, orders: list[Order], seconds: float, rng_seed: int) -> dict:
    sim = base.fork(snap)
    sim.reseed(rng_seed)
    attack = sim.possession
    t0 = sim.t
    end_t = t0 + seconds
    pending = sorted(_start(sim, orders, t0), key=lambda o: o.at_s)
    # A receiver told to carry does it when the ball reaches him, and his pass or shot follows the carry.
    receiving = {o.player_id: o for o in orders if o.action == "carry" and sim.slot_of(o.player_id) != sim.owner}
    after: list[tuple[float, Order]] = []
    slots = [i for i in range(22) if sim.active[i]]
    frames, ball, events = [], [], []
    outcome, xg, shooter, stop_at = "kept", 0.0, None, end_t
    seen = len(sim.events)
    steps = int(round(seconds / DT))
    for f in range(steps + int(AFTER_END_S / DT)):
        for pid, o in list(receiving.items()):
            k = sim.slot_of(pid)
            if sim.owner == k and sim.ball_state == "owned":
                del receiving[pid]
                _apply(sim, o, end_t)
                done = float(sim.intent_until[k])
                after += [(max(done, t0 + b.at_s), b) for b in orders if b.player_id == pid and b.action in ("pass", "shoot")]
        for due in [a for a in after if a[0] <= sim.t + 1e-9]:
            after.remove(due)
            _apply(sim, due[1], end_t)
        while pending and t0 + pending[0].at_s <= sim.t + 1e-9:
            o = pending.pop(0)
            later = [t0 + n.at_s for n in pending if n.player_id == o.player_id and n.action in ("pass", "shoot")]
            _apply(sim, o, end_t, min(later) if later else None)
        if f % RECORD_EVERY == 0:
            frames.append([round(float(v), 1) for i in slots for v in sim.pos[i]])
            ball.append([round(float(v), 1) for v in sim.ball_pos])
        sim.step()
        for ev in sim.events[seen:]:
            rel = int(round((ev["t_ms"] / 1000 - t0) * 1000))
            events.append({"type": ev["type"], "t_ms": rel, "player_id": ev["player_id"], "team_id": ev["team_id"],
                           "outcome": ev["outcome"]})
            if outcome == "kept" and ev["type"] == "shot" and ev["team_id"] == sim.teams[attack].club.club_id:
                outcome, shooter = ev["outcome"] or "off_target", ev["player_id"]
                xg = next((p["p_success"] for p in sim.probabilities if p.get("serial") == ev["_serial"]), 0.0)
                stop_at = min(stop_at, sim.t + AFTER_END_S)
            elif outcome == "kept" and ev["type"] == "offside":
                outcome = "offside"
                stop_at = min(stop_at, sim.t + AFTER_END_S)
        seen = len(sim.events)
        if outcome == "kept" and sim.ball_state == "dead":
            outcome = "out"  # out of play: a throw-in, a corner or a goal kick
            stop_at = min(stop_at, sim.t + AFTER_END_S)
        elif outcome == "kept" and sim.possession != attack and sim.possession >= 0:
            outcome = "lost"
            stop_at = min(stop_at, sim.t + AFTER_END_S)
        if sim.t >= stop_at:
            break
    return {"outcome": outcome, "xg": round(float(xg), 3), "shooter": shooter, "frames": frames, "ball": ball,
            "events": events}


def play_out(md: MatchData, period: int, t_ms: int, positions: dict[str, tuple[float, float]],
             ball_owner: str | None, orders: list[Order], runs: int = RUNS, seconds: float = SECONDS,
             rng_seed: int = 0) -> dict:
    """Play the position out `runs` times. Every run comes back at 80 ms for the app to animate."""
    base = setup(md, period, t_ms, positions, ball_owner, rng_seed)
    problems = check_orders(base, orders)
    if problems:
        raise ValueError("; ".join(problems))
    snap = base.checkpoint()
    played = [_run(base, snap, orders, seconds, rng_seed * 1000 + k) for k in range(runs)]
    shots = [r for r in played if r["outcome"] in SHOT_OUTCOMES]
    return {
        "period": period, "t_ms": t_ms, "step_ms": int(round(RECORD_EVERY * DT * 1000)),
        "attacking": base.teams[base.possession].club.club_id, "ball_owner": base.pid(base.owner),
        "ids": [base.pid(i) for i in range(22) if base.active[i]],
        "runs": played,
        "summary": {"runs": runs, "shots": len(shots), "goals": sum(r["outcome"] == "goal" for r in played),
                    "lost": sum(r["outcome"] == "lost" for r in played),
                    "xg": round(sum(r["xg"] for r in shots) / runs, 3)},
    }


def position_of(md: MatchData, period: int, t_ms: int) -> dict:
    """The tracked position at a frame, as the board starts from it: every player, the ball and who has it."""
    base = setup(md, period, t_ms, {}, None)
    return {"period": period, "t_ms": t_ms, "attacking": base.teams[base.possession].club.club_id,
            "ball_owner": base.pid(base.owner),
            "players": {base.pid(i): [round(float(base.pos[i][0]), 1), round(float(base.pos[i][1]), 1)]
                        for i in range(22) if base.active[i]},
            "attacks_towards_x": {base.teams[s].club.club_id: (L if base.teams[s].direction > 0 else 0.0)
                                  for s in (0, 1)}}
