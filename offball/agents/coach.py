"""The Coach (Play it out): an attacking or defending plan for a position a viewer has set up, as orders the
match engine plays.

The viewer's position and goal go to the Coach with the pitch's geometry: who attacks which goal and where each
defence's offside line is. Orders it gives that the engine can't play (a player who isn't on the pitch, the wrong
side's action, a pass to an opponent) go back to it once with the problems. If it still can't give a playable plan,
there is none, as a step whose agent fails says nothing.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

from offball.agents.crew import AgentFailed, Crew, as_json
from offball.agents.schemas import CoachOut
from offball.models import playground as PG
from offball.models.match_data import MatchData

log = logging.getLogger("offball.coach")
TRIAL_RUNS = 6  # playouts the Coach tries its plan with before the viewer sees it


def _orders(out: CoachOut) -> list[PG.Order]:
    return [PG.Order(o.player_id, o.action, (o.to_x, o.to_y) if o.to_x is not None and o.to_y is not None else None,
                     o.target_id, float(o.at_s)) for o in out.orders]


def describe(md: MatchData, sim) -> dict[str, Any]:
    """The position as the Coach reads it: every player, the ball, the goals and the offside lines."""
    lineup = {e.player_id: (e.number, e.role, sheet.name) for sheet in (md.info.home, md.info.away) for e in sheet.lineup}
    players = []
    for i in range(22):
        if not sim.active[i]:
            continue
        pid = sim.pid(i)
        number, role, club = lineup.get(pid, (None, None, sim.teams[sim.team_of[i]].club.name))
        players.append({"player_id": pid, "club": club, "number": number, "role": role,
                        "x": round(float(sim.pos[i][0]), 1), "y": round(float(sim.pos[i][1]), 1),
                        "side": "attacking" if int(sim.team_of[i]) == sim.possession else "defending"})
    goals, lines = {}, {}
    for side in (0, 1):
        club = sim.teams[side].club
        attacks = 105.0 if sim.teams[side].direction > 0 else 0.0
        goals[club.name] = f"attacks the goal at x = {attacks:g}"
        # A defence's offside line is its second-last player towards its own goal.
        own_goal = 105.0 - attacks
        deepest = sorted((float(sim.pos[i][0]) for i in sim.active_of(side)), key=lambda x: abs(x - own_goal))
        lines[club.name] = round(deepest[1], 1) if len(deepest) > 1 else None
    return {"players": players, "ball_with": sim.pid(sim.owner), "goals": goals,
            "offside_line_x_of_each_defence": lines}


async def plan(crew: Crew, md: MatchData, period: int, t_ms: int, positions: dict[str, tuple[float, float]],
               ball_owner: str | None, side: str, goal: str, against: list[PG.Order]) -> dict[str, Any] | None:
    """A plan for `side` ("attack" or "defend") from the viewer's position, or None if the Coach can't give one."""
    sim = PG.setup(md, period, t_ms, positions, ball_owner)
    position = describe(md, sim)
    attacking = sim.teams[sim.possession].club.name
    defending = sim.teams[1 - sim.possession].club.name
    task = (f"Plan {attacking}'s attack." if side == "attack"
            else f"Plan {defending}'s defence against {attacking}'s attack.")
    base = (f"Position:\n{as_json(position)}\n\n{task}\nWhat the viewer wants: {goal.strip() or 'the best plan'}")
    if side == "defend" and against:
        base += "\n\nThe attacking orders to defend against:\n" + as_json(
            [{"player_id": o.player_id, "action": o.action, "to": o.to_xy, "target_id": o.target_id, "at_s": o.at_s}
             for o in against])
    prompt = base
    best: tuple[float, dict[str, Any]] | None = None
    tested = 0
    for _ in range(4):
        try:
            out = await crew.ask("coach", prompt, CoachOut)
        except AgentFailed:
            break
        orders = _orders(out)
        wanted = PG.ATTACK_ACTIONS if side == "attack" else PG.DEFEND_ACTIONS
        problems = PG.check_orders(sim, orders)
        problems += [f"{o.player_id} {o.action}: plan only the {side}, with {', '.join(wanted)}"
                     for o in orders if o.action not in wanted]
        if problems:
            log.warning("The Coach's orders couldn't be played: %s", "; ".join(problems))
            prompt = f"{base}\n\nYour previous orders couldn't be played:\n" + "\n".join(problems) + "\nGive them again."
            continue
        # The Coach tries its plan in the engine before the viewer sees it, and redraws it once if it fails.
        trial = PG.play_out(md, period, t_ms, positions, ball_owner, orders + list(against) if side == "defend" else orders,
                            runs=TRIAL_RUNS, rng_seed=99)
        tested += 1
        s_ = trial["summary"]
        score = (3 * s_["goals"] + s_["shots"]) if side == "attack" else -(3 * s_["goals"] + s_["shots"])
        plan_out = {"side": side, "headline": out.headline, "explanation": out.explanation, "ai_generated": True,
                    "tested": {"runs": s_["runs"], "shots": s_["shots"], "goals": s_["goals"]},
                    "orders": [{"player_id": o.player_id, "action": o.action,
                                "to_xy": None if o.to_xy is None else [round(float(v), 1) for v in np.asarray(o.to_xy)],
                                "target_id": o.target_id, "at_s": round(o.at_s, 1)} for o in orders]}
        if best is None or score > best[0]:
            best = (score, plan_out)
        works = s_["shots"] > 0 if side == "attack" else s_["goals"] == 0 and s_["shots"] <= s_["runs"] // 4
        if works or tested >= 2:
            break
        prompt = (f"{base}\n\nYou planned:\n{as_json(plan_out['orders'])}\n\nIn {s_['runs']} trial playouts in the "
                  f"engine it went like this:\n{as_json(_story(trial))}\n"
                  + ("It never got a shot away. Plan again so the attack gets a shot." if side == "attack"
                     else "The attack still got shots away. Plan again so the defence stops them."))
    return best[1] if best else None


def _story(trial: dict[str, Any]) -> list[dict[str, Any]]:
    """What happened in each trial playout, briefly: how it ended and the events that decided it."""
    out = []
    for r in trial["runs"]:
        key = [e for e in r["events"] if e["type"] in ("pass", "shot", "interception", "tackle", "offside", "clearance",
                                                         "save", "block")][:4]
        out.append({"outcome": r["outcome"], "events": [{k: e[k] for k in ("type", "t_ms", "player_id", "outcome")}
                                                        for e in key]})
    return out
