"""Player policies: every 200-400 ms each player perceives, scores options by utility and picks one (PRD 12.4).

On the ball: pass, carry, shoot, clear or hold, scored by success probability times gain in possession value.
Off the ball in attack: support, run in behind, decoy, overlap, check run or hold width.
Off the ball in defence: press, mark, track the runner, pass the runner on, cover or hold the zone.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import numpy as np

from offball.generator.engine.geometry import L, W, goal_distance, pt_to_team
from offball.generator.engine.models import (
    ShotContext,
    location_value,
    plan_aerial,
    plan_ground,
    pressure_on,
    time_to_reach,
    xg_true,
)

if TYPE_CHECKING:
    from offball.generator.engine.sim import Simulator

ATTACKING_ROLES = frozenset({"ST", "RW", "LW", "AM", "RM", "LM"})
RUNNER_ROLES = frozenset({"ST", "RW", "LW", "AM", "CM", "RM", "LM"})
FULL_BACKS = frozenset({"RB", "LB", "RWB", "LWB"})


def team_xy(sim: Simulator, team: int, xy: np.ndarray) -> tuple[float, float]:
    return pt_to_team(float(xy[0]), float(xy[1]), sim.teams[team].direction)


def abs_xy(sim: Simulator, team: int, x_t: float, y_t: float) -> np.ndarray:
    d = sim.teams[team].direction
    return np.array([x_t, y_t]) if d > 0 else np.array([L - x_t, W - y_t])


def softmax_pick(sim: Simulator, utilities: list[float], temperature: float) -> int:
    u = np.array(utilities)
    z = (u - u.max()) / max(temperature, 1e-4)
    p = np.exp(z)
    p /= p.sum()
    return int(sim.rng.choice(len(u), p=p))


def keeper_cover(sim: Simulator, shooter: int) -> float:
    """1 when the opposing keeper is set on the line between ball and goal, falling to 0 when beaten."""
    team = sim.team_of[shooter]
    gk = sim.keeper(1 - team)
    if gk < 0:
        return 0.0
    goal = np.array([L if sim.teams[team].direction > 0 else 0.0, W / 2])
    p = sim.pos[shooter]
    seg = goal - p
    s = float(np.clip(((sim.pos[gk] - p) @ seg) / max(seg @ seg, 1e-6), 0, 1))
    off_line = float(np.linalg.norm(p + s * seg - sim.pos[gk]))
    return float(np.clip(1.0 - off_line / 4.0, 0.0, 1.0)) * (0.6 + 0.4 * sim.handling[gk])


# ---------------------------------------------------------------------------------------------------------
# On the ball


def on_ball(sim: Simulator, i: int) -> None:
    team = sim.team_of[i]
    P = sim.params
    p = sim.pos[i]
    xt, yt = team_xy(sim, team, p)
    opp = sim.active_of(1 - team)
    mates = [j for j in sim.active_of(team) if j != i]
    pressure = pressure_on(p, sim.pos[opp])
    directive = sim.directives.get(i)

    if directive is not None:
        if directive.get("action") == "shoot":
            sim.shoot(i)
            return
        if directive.get("action") == "pass":
            j = directive["to"]
            if sim.active[j] and directive.get("when", lambda s: True)(sim):
                tgt = directive.get("point_fn", lambda s: None)(sim)
                target = tgt if tgt is not None else pass_target(sim, i, j)
                aerial = directive.get("aerial", False)
                if aerial:
                    flight = plan_aerial(p.copy(), target, apex=directive.get("apex", 3.2))
                else:
                    flight = plan_ground(p.copy(), target, arrival_speed=P.pass_arrival)
                sim.release_pass(i, j, flight, subtype=directive.get("subtype"))
                sim.directives.pop(i, None)
                return
            if directive.get("hold", True):
                hold_or_shield(sim, i, pressure)
                return

    # Every option is scored the same way, in possession-value units: what the success state is worth,
    # times its probability, minus the opponents' value wherever the ball would be lost.
    utilities: list[float] = []
    actions: list[tuple] = []
    opp_pos = sim.pos[opp]
    style = sim.style_of(team)

    def value(x_t: float, y_t: float) -> float:
        return location_value(x_t, y_t, P)

    def loss_cost(point_t: tuple[float, float]) -> float:
        return P.loss_base + value(L - point_t[0], W - point_t[1])

    def held_value(point: np.ndarray, discount: float) -> float:
        """Value of having the ball at `point`, allowing for the pressure waiting there."""
        px, py = team_xy(sim, team, point)
        pr = pressure_on(point, opp_pos)
        return value(px, py) * (1.0 - P.held_pressure * pr) * discount

    # Shoot
    if sim.role[i] != "GK" and xt > 70 and goal_distance(xt, yt) < 33:
        ctx = ShotContext(xt, yt, pressure, False, sim.finishing[i], sim.composure[i], keeper_cover(sim, i))
        xg = xg_true(ctx, P)
        utilities.append(xg * P.shot_scale * (1.0 + 0.04 * style.directness))
        actions.append(("shot",))

    # Pass
    in_own_third = xt < 35
    for j in mates:
        if sim.role[j] == "GK" and not (in_own_third and pressure > 0.4):
            continue
        dist = float(np.linalg.norm(sim.pos[j] - p))
        if dist < 4.0 or dist > 62.0:
            continue
        # Passers see offside teammates, unless they misread it.
        if sim._is_offside(j) and sim.rng.random() > 0.08 * (1.0 - sim.vision[i]):
            continue
        target = pass_target(sim, i, j)
        tx, ty = team_xy(sim, team, target)
        wide = yt < 15 or yt > W - 15
        cross = wide and xt > 76 and tx > 86 and abs(ty - W / 2) < 18
        aerial = cross or dist > 34 or (sim.role[i] == "GK" and style.build_up == "keeper_long" and dist > 25)
        flight = plan_aerial(p.copy(), target) if aerial else plan_ground(p.copy(), target, arrival_speed=P.pass_arrival)
        a = sim.assess(i, j, flight)
        forward = max(0.0, tx - xt) / 30.0
        gain = held_value(target, 0.97) * (1 + 0.3 * style.directness * forward)
        u = a.p_success * gain - (1 - a.p_success) * loss_cost((tx, ty))
        u -= P.long_pass_cost * max(0.0, dist - 25.0) * (1.2 - style.directness)
        if cross:
            u += 0.004
        utilities.append(u)
        actions.append(("pass", j, flight, a, "cross" if cross else None))

    # Carry: forward and two diagonals.
    goal_dir = 1.0 if sim.teams[team].direction > 0 else -1.0
    here_cost = loss_cost((xt, yt))
    for ang in (0.0, 0.6, -0.6):
        step = 7.0
        dx = math.cos(ang) * step * goal_dir
        dy = math.sin(ang) * step
        end = np.array([np.clip(p[0] + dx, 1, L - 1), np.clip(p[1] + dy, 1, W - 1)])
        p_keep = _carry_keep(sim, i, p, end, opp)
        u = p_keep * held_value(end, 0.95) - (1 - p_keep) * here_cost
        utilities.append(u)
        actions.append(("carry", end))

    # Clear or go long: under pressure in our own half, get it away from danger.
    if xt < 45 and pressure > 0.3:
        land = (min(xt + 38.0, 80.0), float(np.clip(yt, 8, W - 8)))
        keep = P.clear_keep
        utilities.append(keep * value(*land) * 0.9 - (1 - keep) * loss_cost(land))
        actions.append(("clear",))

    # Hold and shield: keep the ball, at the risk of being dispossessed where we stand.
    p_hold = 1.0 - P.hold_risk * pressure
    utilities.append(p_hold * value(xt, yt) * (0.97 - 0.05 * style.tempo) - (1 - p_hold) * here_cost)
    actions.append(("hold",))

    temperature = P.temperature + P.temperature_vision * (1.0 - sim.vision[i]) * (1.4 - 0.4 * sim.energy[i])
    choice = actions[softmax_pick(sim, utilities, temperature)]
    sim.log_intent(i, choice[0], float(max(utilities)))
    if choice[0] == "shot":
        sim.shoot(i)
    elif choice[0] == "pass":
        _, j, flight, a, subtype = choice
        sim.release_pass(i, j, flight, assessment=a, subtype=subtype)
    elif choice[0] == "carry":
        sim.set_intent(i, "carry", choice[1], 0.78, until=sim.t + 1.2)
    elif choice[0] == "clear":
        sim.clear(i)
    else:
        hold_or_shield(sim, i, pressure)


def _carry_keep(sim: Simulator, i: int, start: np.ndarray, end: np.ndarray, opp: list[int]) -> float:
    """Chance of keeping the ball over a short dribble: a race between the dribbler and each defender
    to points along the dribbling line, softened by the dribbler's skill."""
    if not opp:
        return 0.98
    P = sim.params
    carry_speed = 0.8 * float(sim.vmax[i])
    fractions = np.array([0.35, 0.7, 1.0])
    pts = start + fractions[:, None] * (end - start)
    t_carrier = fractions * float(np.linalg.norm(end - start)) / carry_speed
    t_def = time_to_reach(sim.pos[opp], sim.vel[opp], sim.vmax[opp], pts, reaction=0.35)
    p_def = 1 / (1 + np.exp(-((t_carrier[None, :] - t_def + P.carry_lead) / P.carry_tau)))
    beat = P.carry_beat + 0.5 * float(sim.dribbling[i])  # a good dribbler beats a challenge more often
    p_lose = 1 - np.prod(1 - p_def.max(axis=1) * (1 - beat))
    return float(np.clip(1 - p_lose, 0.02, 0.98))


def hold_or_shield(sim: Simulator, i: int, pressure: float) -> None:
    # Shield by turning away from the nearest opponent and drifting a little.
    team = sim.team_of[i]
    opp = sim.active_of(1 - team)
    if len(opp):
        k = opp[int(np.argmin(np.linalg.norm(sim.pos[opp] - sim.pos[i], axis=1)))]
        away = sim.pos[i] - sim.pos[k]
        n = float(np.linalg.norm(away)) or 1.0
        target = sim.pos[i] + away / n * (1.5 + 2.0 * pressure)
    else:
        target = sim.pos[i]
    sim.set_intent(i, "hold", np.clip(target, [1, 1], [L - 1, W - 1]), 0.35, until=sim.t + 0.4)
    sim.next_decision[i] = sim.t + 0.18 + 0.15 * (1.0 - pressure)


def pass_target(sim: Simulator, i: int, j: int) -> np.ndarray:
    """Where to play the ball for teammate j: to feet, or into the path of a runner."""
    p = sim.pos[i]
    pj = sim.pos[j]
    if sim.intent[j] == "run" and "point" in sim.idata[j]:
        run_to = sim.idata[j]["point"]
        dist = float(np.linalg.norm(pj - p))
        lead_t = 0.6 + dist / 18.0
        lead = pj + sim.vel[j] * lead_t
        # Don't lead beyond where the run is going.
        to_end = run_to - pj
        if float(np.linalg.norm(lead - pj)) > float(np.linalg.norm(to_end)):
            lead = run_to
        return np.clip(lead, [1.0, 1.0], [L - 1.0, W - 1.0])
    lead = pj + sim.vel[j] * 0.4
    return np.clip(lead, [1.0, 1.0], [L - 1.0, W - 1.0])


# ---------------------------------------------------------------------------------------------------------
# Off the ball, in possession


def attack_off_ball(sim: Simulator, i: int) -> None:
    team = sim.team_of[i]
    role = sim.role[i]
    if role == "GK":
        sim.set_intent(i, "anchor", None, 0.4)
        return
    if sim.intent[i] == "run" and sim.t < sim.intent_until[i]:
        return  # committed to a run
    owner = sim.owner
    style = sim.style_of(team)
    P = sim.params
    xt, yt = team_xy(sim, team, sim.pos[i])
    line = sim.offside_cache[team]
    options: list[tuple[str, float, np.ndarray | None, float, float]] = []  # name, utility, point, speed, secs

    anchor_t = team_xy(sim, team, sim.anchor[i])
    # Utilities are in possession-value units: the chance this movement gets the ball, times what it is
    # worth there, minus the effort. Holding shape has a structural value of its own.
    fatigue_cost = 0.004 + 0.008 * (1.0 - sim.energy[i])
    options.append(("anchor", P.anchor_value + 0.003 * float(sim.intent[i] == "anchor"), None, 0.5, 0.0))

    if owner >= 0 and sim.team_of[owner] == team and owner != i:
        bo = sim.pos[owner]
        bx, by = team_xy(sim, team, bo)
        opp = sim.active_of(1 - team)
        dist_owner = float(np.linalg.norm(sim.pos[i] - bo))
        owner_pressure = pressure_on(bo, sim.pos[opp])

        # Support: offer an angle near the ball.
        if dist_owner < 32:
            best_pt, best_open = None, -1.0
            for ang in (-1.1, -0.5, 0.0, 0.5, 1.1, 2.4, -2.4):
                r = 12.0 + 4.0 * sim.rng.random()
                base = math.atan2(anchor_t[1] - by, anchor_t[0] - bx)
                ax = bx + r * math.cos(base + ang * 0.5)
                ay = by + r * math.sin(base + ang * 0.5)
                if not (2 < ax < L - 2 and 2 < ay < W - 2) or ax > line - 0.5:
                    continue
                pt = abs_xy(sim, team, ax, ay)
                openness = float(np.min(np.linalg.norm(sim.pos[opp] - pt, axis=1))) if len(opp) else 15.0
                if openness > best_open:
                    best_open, best_pt = openness, pt
            if best_pt is not None:
                p_recv = 0.2 + 0.45 * owner_pressure
                value = location_value(*team_xy(sim, team, best_pt), P) * min(best_open, 8.0) / 8.0
                options.append(("support", p_recv * value + P.support_base - 0.5 * fatigue_cost, best_pt, 0.7, 1.6))

        # Run in behind: when there is space behind the line and the passer has time.
        if role in RUNNER_ROLES and line < 92 and owner_pressure < 0.6 and xt > bx - 10:
            depth = 7.0 + 6.0 * sim.rng.random()
            tx = min(line + depth, L - 6.0)
            ty = float(np.clip(yt + (W / 2 - yt) * 0.35 + sim.rng.normal(0, 4), 6, W - 6))
            onside = xt <= line - 0.3 * sim.run_timing[i]
            if onside:
                p_recv = P.run_rate * (0.5 + sim.run_timing[i]) * (1.0 - owner_pressure) * (0.6 + 0.6 * style.directness)
                u = p_recv * location_value(tx, ty, P) - fatigue_cost
                options.append(("run", u, abs_xy(sim, team, tx, ty), 0.97, 2.6 + 1.2 * sim.rng.random()))

        # Decoy run: drag a marker away from a valuable zone (the run itself isn't for the ball).
        marker = sim.marker_of(i)
        if role in ("ST", "RW", "LW", "AM") and marker >= 0 and xt > 60:
            side = 1.0 if yt < W / 2 else -1.0
            if abs(by - yt) < 8:
                side = -side if by > yt else side
            tx = min(xt + 4 + 4 * sim.rng.random(), line + 2)
            ty = float(np.clip(yt + side * (14 + 6 * sim.rng.random()), 5, W - 5))
            vacated = location_value(*team_xy(sim, team, sim.pos[marker]), P)
            u = sim.decoy[i] * vacated * P.decoy_scale - fatigue_cost
            options.append(("decoy_run", u, abs_xy(sim, team, tx, ty), 0.95, 2.8))

        # Overlap: a full-back goes round the wide player on his side.
        if role in FULL_BACKS and bx > 60 and abs(by - yt) < 16 and owner != i and sim.role[owner] in (
            "RW", "LW", "RM", "LM", "AM", "CM"
        ):
            outside = 3.0 if yt < W / 2 else W - 3.0
            tx = min(bx + 10, line + 1, L - 8)
            u = 0.22 * location_value(tx, outside, P) * (0.5 + style.width) - fatigue_cost + 0.004
            options.append(("overlap", u, abs_xy(sim, team, tx, outside), 0.92, 3.0))

    u = [o[1] + float(sim.rng.gumbel(0, 0.0025)) for o in options]
    k = int(np.argmax(u))
    name, util, point, speed, secs = options[k]
    sim.log_intent(i, name, util)
    if name == "anchor":
        sim.set_intent(i, "anchor", None, speed)
    elif name in ("run", "decoy_run", "overlap"):
        sim.set_intent(i, "run", point, speed, until=sim.t + secs, data={"kind": name})
    else:
        sim.set_intent(i, name, point, speed, until=sim.t + secs)


# ---------------------------------------------------------------------------------------------------------
# Off the ball, out of possession


def defend(sim: Simulator, i: int) -> None:
    team = sim.team_of[i]
    if sim.role[i] == "GK":
        keeper_position(sim, i)
        return
    if i in sim.pressers[team]:
        sim.set_intent(i, "press", None, 0.82 + 0.15 * sim.style_of(team).press_intensity)
        return
    if i in sim.covers[team]:
        sim.set_intent(i, "cover", None, 0.75, data={"who": sim.pressers[team][0] if sim.pressers[team] else -1})
        return

    current = sim.idata[i].get("who", -1) if sim.intent[i] in ("mark", "track") else -1
    if current >= 0 and sim.active[current]:
        speed = float(np.linalg.norm(sim.vel[current]))
        leaving = float(np.linalg.norm(sim.pos[current] - sim.anchor[i])) > 9.0
        if sim.intent[i] == "track":
            # Keep tracking until the run dies out or the runner is far from danger.
            started = sim.idata[i].get("since", sim.t)
            if speed > 3.0 and sim.t - started < 5.5:
                return
            sim.set_intent(i, "anchor", None, 0.7)
            sim.log_intent(i, "release", 0.0)
            return
        if speed > 5.0 and leaving and "decided" not in sim.idata[i]:
            run_target = sim.idata[current].get("point")
            danger = _run_is_dangerous(sim, team, current, run_target)
            discipline = sim.attr(i, "discipline")
            P = sim.params
            p_track = P.track_base + P.track_discipline * (1 - discipline) + (P.track_danger if danger else -0.06)
            if sim.rng.random() < float(np.clip(p_track, 0.02, 0.98)):
                sim.set_intent(i, "track", None, 0.97, data={"who": current, "since": sim.t, "decided": True})
                sim.log_intent(i, "track_runner", p_track)
            else:
                sim.set_intent(i, "anchor", None, 0.65, data={"decided": True, "passed_on": current})
                sim.log_intent(i, "pass_on", 1 - p_track)
            return
        if not leaving:
            return  # keep marking

    # Zonal marking: the most dangerous attacker inside my zone.
    opp = sim.active_of(1 - team)
    best, best_score = -1, 0.0
    own_goal = np.array([0.0 if sim.teams[team].direction > 0 else L, W / 2])
    # In and around our box, defenders mark tighter and over a wider zone.
    deep = float(np.linalg.norm(sim.ball_pos[:2] - own_goal)) < 34.0
    zone = sim.params.zone_radius_deep if deep else sim.params.zone_radius
    for k in opp:
        if sim.role[k] == "GK":
            continue
        d_zone = float(np.linalg.norm(sim.pos[k] - sim.anchor[i]))
        if d_zone > zone:
            continue
        if sim.marker_of(k) not in (-1, i):
            continue
        danger = 1.0 / (1.0 + float(np.linalg.norm(sim.pos[k] - own_goal)) / 20.0)
        score = danger / (1.0 + d_zone / 6.0)
        if score > best_score:
            best, best_score = k, score
    if best >= 0:
        sim.set_intent(i, "mark", None, 0.75, data={"who": best})
    else:
        sim.set_intent(i, "anchor", None, 0.6)


def _run_is_dangerous(sim: Simulator, team: int, runner: int, run_target: np.ndarray | None) -> bool:
    """A run is dangerous when it heads in behind and towards the middle of our goal."""
    own_goal = np.array([0.0 if sim.teams[team].direction > 0 else L, W / 2])
    tgt = run_target if run_target is not None else sim.pos[runner] + sim.vel[runner] * 1.5
    closer = float(np.linalg.norm(tgt - own_goal)) < float(np.linalg.norm(sim.pos[runner] - own_goal)) - 4.0
    central = abs(float(tgt[1]) - W / 2) < 14.0
    return closer and central


def keeper_position(sim: Simulator, i: int) -> None:
    team = sim.team_of[i]
    d = sim.teams[team].direction
    goal = np.array([0.0 if d > 0 else L, W / 2])
    b = sim.ball_pos[:2]
    to_ball = b - goal
    dist = float(np.linalg.norm(to_ball)) or 1.0
    depth = float(np.clip(1.0 + dist * 0.06, 1.0, 6.5))
    target = goal + to_ball / dist * depth
    sim.set_intent(i, "keep", target, 0.7)


def loose_ball(sim: Simulator, i: int) -> None:
    if i in sim.chasers:
        sim.set_intent(i, "chase", None, 0.97)
    else:
        sim.set_intent(i, "anchor", None, 0.6)
