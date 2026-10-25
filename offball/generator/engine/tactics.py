"""Team shape: where each formation slot wants to be, given the ball, the phase and the club's style."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from offball.generator.engine.geometry import L, W, pt_to_team

if TYPE_CHECKING:
    from offball.generator.engine.sim import Simulator

FULL_BACKS = frozenset({"RB", "LB", "RWB", "LWB"})
WIDE = frozenset({"RW", "LW", "RM", "LM"})


def offside_line_team(sim: Simulator, team: int) -> float:
    """x' (in `team`'s frame) of the opponents' second-last player: the line attackers must stay behind."""
    opp = 1 - team
    d = sim.teams[team].direction
    xs = []
    for i in sim.team_slots[opp]:
        if sim.active[i]:
            x = sim.pos[i, 0] if d > 0 else L - sim.pos[i, 0]
            xs.append(x)
    xs.sort(reverse=True)
    if len(xs) < 2:
        return L / 2
    return max(xs[1], L / 2)


def compute_anchors(sim: Simulator, team: int) -> np.ndarray:
    """Absolute anchor positions for the team's 11 slots, shape (11, 2)."""
    t = sim.teams[team]
    style = t.style
    P = sim.params
    d = t.direction
    bx, by = pt_to_team(float(sim.ball_pos[0]), float(sim.ball_pos[1]), d)
    in_poss = sim.possession == team
    transition = sim.t < sim.transition_until[team]
    out = np.empty((11, 2))

    if in_poss:
        back = float(np.clip(bx - (30.0 - 10.0 * style.line_height), 12.0 + 10.0 * style.line_height, 62.0))
        line = sim.offside_cache[team]
        front = back + 36.0 + 10.0 * style.directness
        front = min(front, max(line - 1.0, 48.0)) if bx < line else max(front, bx)
        depth = max(front - back, 20.0)
        width = P.att_width + 20.0 * style.width
        cy = W / 2 + P.att_ball_shift * (by - W / 2)
    else:
        base_back = 18.0 + 26.0 * style.line_height
        if transition:
            base_back -= 6.0
        back = float(np.clip(bx - 9.0 - 14.0 * (1.0 - style.press_height), 6.0, base_back))
        depth = P.def_depth + 11.0 * style.press_height
        width = P.def_width + 7.0 * (1.0 - style.press_intensity)
        cy = W / 2 + P.def_ball_shift * (by - W / 2)
        if bx < 36.0:
            # Defending the box: drop deep and narrow, between the ball and the goal.
            squeeze = (36.0 - bx) / 36.0
            depth -= P.box_squeeze_depth * squeeze
            width -= P.box_squeeze_width * squeeze
            cy = W / 2 + 0.3 * (by - W / 2)

    for k, slot in enumerate(t.slots):
        if slot.role == "GK":
            gx = float(np.clip(3.0 + 0.1 * bx, 2.0, 24.0)) if in_poss else float(np.clip(1.5 + 0.06 * bx, 1.5, 12.0))
            gy = W / 2 + 0.15 * (by - W / 2)
            xt, yt = gx, gy
        else:
            u, v = slot.u, slot.v
            if in_poss and slot.role in FULL_BACKS:
                u = min(0.95, u + 0.25 + 0.25 * style.width - 0.08 * (style.rest_defence - 2))
            if in_poss and slot.role in WIDE:
                v = 0.04 if v < 0.5 else 0.96  # wingers hold the touchline in possession
            xt = back + u * depth
            yt = cy + (v - 0.5) * width
            if not in_poss:
                yt += 0.12 * (by - yt)  # squeeze towards the ball side
        if slot.role != "GK" and sim.t < sim.shape_shift_until[team]:
            xt += float(sim.shape_shift[team])  # a tactical change: the block sits deeper or higher for a while
        xt = float(np.clip(xt, 1.0, L - 1.0))
        yt = float(np.clip(yt, 1.5, W - 1.5))
        out[k] = (xt, yt) if d > 0 else (L - xt, W - yt)
    return out
