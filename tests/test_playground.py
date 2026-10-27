"""Play it out: the engine from a position a viewer sets, with their orders or the Coach's."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from offball.agents import coach
from offball.agents.crew import Crew
from offball.mcp import tools as T
from offball.models import playground as PG
from offball.services import api

AT = (2, 1081440)  # the showcase's decoy run, as tracked


@pytest.fixture(scope="module")
def md():
    return T.REGISTRY.data("m07")


def test_the_board_starts_from_the_tracked_frame(md) -> None:
    board = PG.position_of(md, *AT)
    assert len(board["players"]) == 22 and board["ball_owner"] in board["players"]
    assert set(board["attacks_towards_x"].values()) == {0.0, 105.0}


def test_moved_players_and_the_ball_go_where_the_viewer_put_them(md) -> None:
    sim = PG.setup(md, *AT, {"kes-10": (90.0, 34.0)}, "kes-10")
    i = sim.slot_of("kes-10")
    assert list(sim.pos[i]) == [90.0, 34.0] and sim.owner == i
    assert list(sim.ball_pos[:2]) == [90.0, 34.0] and sim.possession == sim.team_of[i]


def test_orders_the_engine_cant_play_are_named(md) -> None:
    sim = PG.setup(md, *AT, {}, "kes-08")
    problems = PG.check_orders(sim, [PG.Order("kes-09", "press"), PG.Order("ash-05", "run", (80, 30)),
                                     PG.Order("kes-08", "pass", target_id="ash-05"), PG.Order("nobody", "shoot"),
                                     PG.Order("kes-09", "carry", (90, 30))])
    assert len(problems) == 5
    assert PG.check_orders(sim, [PG.Order("kes-08", "pass", target_id="kes-10", at_s=1.0),
                                 PG.Order("ash-05", "mark", target_id="kes-10")]) == []


def test_a_shot_from_the_box_plays_out_with_its_chance(md) -> None:
    orders = [PG.Order("kes-10", "carry", (97.0, 36.0)), PG.Order("kes-10", "shoot", at_s=1.4)]
    out = PG.play_out(md, *AT, {"kes-10": (90.0, 34.0)}, "kes-10", orders, runs=4)
    assert out["summary"]["runs"] == 4 and out["summary"]["shots"] >= 3
    run = out["runs"][0]
    assert run["outcome"] in PG.SHOT_OUTCOMES and 0 < run["xg"] < 1 and run["shooter"] == "kes-10"
    # Every run comes back frame by frame for the board to animate.
    assert len(run["frames"]) == len(run["ball"]) > 10 and len(run["frames"][0]) == 2 * len(out["ids"])
    # The same position and orders play out the same way.
    assert PG.play_out(md, *AT, {"kes-10": (90.0, 34.0)}, "kes-10", orders, runs=4)["summary"] == out["summary"]


def test_a_pass_to_a_runner_past_the_line_is_offside(md) -> None:
    out = PG.play_out(md, *AT, {"kes-10": (96.0, 38.0), "kes-08": (82.0, 40.0)}, "kes-08",
                      [PG.Order("kes-08", "pass", target_id="kes-10", at_s=0.6)], runs=2)
    assert {r["outcome"] for r in out["runs"]} == {"offside"}


async def test_the_coach_plans_an_attack_then_a_defence(md, scripted) -> None:
    model = scripted()
    crew = Crew.with_clients({"fast": model, "reasoning": model})
    attack = await coach.plan(crew, md, *AT, {}, "kes-08", "attack", "shoot", [])
    assert attack and attack["orders"] == [{"player_id": "kes-08", "action": "shoot", "to_xy": None, "target_id": None,
                                            "at_s": 0.5}]
    defend = await coach.plan(crew, md, *AT, {}, "kes-08", "defend", "stop it", [PG.Order("kes-08", "shoot", at_s=0.5)])
    assert defend and defend["orders"][0]["action"] == "press" and defend["orders"][0]["player_id"].startswith("ash")
    assert "offside_line_x_of_each_defence" in model.prompts["CoachOut"][0]


def test_the_api_plays_a_board_and_refuses_orders_it_cant_play() -> None:
    client = TestClient(api.app)
    r = client.get("/api/matches/m07/playground", params={"period": AT[0], "t_ms": AT[1]})
    assert r.status_code == 200 and r.json()["ball_owner"]
    body = {"period": AT[0], "t_ms": AT[1], "positions": {"kes-10": [90, 34]}, "ball_owner": "kes-10", "runs": 2,
            "orders": [{"player_id": "kes-10", "action": "shoot", "at_s": 0.2}]}
    r = client.post("/api/matches/m07/playground/play", json=body)
    assert r.status_code == 200 and r.json()["summary"]["shots"] == 2
    body["orders"] = [{"player_id": "kes-10", "action": "press"}]
    assert client.post("/api/matches/m07/playground/play", json=body).status_code == 422
