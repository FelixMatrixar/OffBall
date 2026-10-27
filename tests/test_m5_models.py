"""The M5 models (PRD 13): space value, off-ball scoring opportunity, off-ball credit and the run classifier, on the
showcase's decoy-run goal and on small made-up states."""

from __future__ import annotations

import numpy as np
import pytest

from offball.eval import agents as E
from offball.mcp import tools as T
from offball.models import credit as CR
from offball.models import epv as EPV
from offball.models import metrics
from offball.models import obso as OBSO
from offball.models import runclass as RC
from offball.models.pitch_control import GRID_2M, control_spearman, ppcf
from offball.models.runs import Possession, detect_runs


@pytest.fixture(scope="module")
def goal():
    """The showcase's decoy-run goal: Kestrel Bay's No. 9 drags Ashmoor's No. 5 and No. 10 scores."""
    match_id, cid = E.showcase_moment()
    return T.REGISTRY.data(match_id), T.moment_card(match_id, cid)


def test_player_control_shares_make_up_each_cell() -> None:
    rng = np.random.default_rng(3)
    cells = GRID_2M.centres()
    a, d = rng.uniform([0, 0], [105, 68], (11, 2)), rng.uniform([0, 0], [105, 68], (11, 2))
    av, dv, ball = rng.normal(0, 2, (11, 2)), rng.normal(0, 2, (11, 2)), np.array([60.0, 30.0])
    p_att, p_def = ppcf(a, av, d, dv, ball, cells)
    assert np.allclose(p_att.sum(axis=0) + p_def.sum(axis=0), 1.0)
    assert np.allclose(p_att.sum(axis=0), control_spearman(a, av, d, dv, ball, cells))


def test_the_value_solver_rises_towards_a_scoring_zone() -> None:
    counts = EPV.Counts.empty()
    near_goal, middle = EPV.zone(100.0, 34.0), EPV.zone(50.0, 34.0)
    counts.moves["pass"][middle] = 10
    counts.to["pass"][middle, near_goal] = 10  # every pass from the middle reaches the box
    counts.shots[near_goal], counts.xg[near_goal] = 10, 3.0
    s = EPV.solve(counts, np.zeros(EPV.NX * EPV.NY))
    flat = s.value.ravel()
    assert flat[near_goal] > flat[middle] > 0
    assert np.allclose(s.value, s.shot + s.passing + s.carrying)


def test_space_value_is_higher_near_the_goal_a_club_attacks(goal) -> None:
    md, card = goal
    club, period = card["attacking"]["club_id"], card["period"]
    attack = 105.0 if md.direction(period, club) > 0 else 0.0
    near, far = EPV.value_at(md, period, club, np.array([[abs(attack - 8), 34.0], [abs(attack - 95), 34.0]]))
    assert near > 5 * far > 0
    r = metrics.compute(md, "space_value", club_id=club, period=period, t_ms=card["t_end_ms"])
    assert 0 < r.value < 1 and r.unit == "EPV" and r.evidence_ids


def test_the_scorer_had_a_scoring_opportunity_before_the_goal(goal) -> None:
    md, card = goal
    club, period = card["attacking"]["club_id"], card["period"]
    shot = next(e for e in md.events if e.period == period and e.type == "shot" and e.outcome == "goal"
                and e.team_id == club and e.t_ms >= card["t_start_ms"])
    pf = md.periods[period]
    values = OBSO.by_player(md, period, pf.index_of(shot.t_ms - 1000), club)
    assert set(values) <= set(md.players) and all(0 <= v < 1 for v in values.values())
    ranked = sorted(values, key=values.get, reverse=True)
    assert shot.player_id in ranked[:2]
    r = metrics.compute(md, "scoring_opportunity", club_id=club, period=period, t_ms=shot.t_ms - 1000,
                        player_id=shot.player_id)
    assert r.value > 0 and r.details["top"]


def test_the_decoy_run_created_space_and_threat(goal) -> None:
    md, card = goal
    params = {"club_id": card["attacking"]["club_id"], "creator_id": card["creator"]["player_id"],
              "dragged_ids": [d["player_id"] for d in card["dragged"]], "period": card["period"],
              "t_start_ms": card["t_start_ms"], "t_end_ms": card["t_end_ms"],
              "zone": card["anchors"]["gap"]["polygon"]}
    space = metrics.compute(md, "space_created_by_m2", **params)
    threat = metrics.compute(md, "threat_created", **params)
    assert space.value > 5 and threat.value > 0
    assert set(space.details["ghosts"]) == {params["creator_id"], *params["dragged_ids"]}
    assert card["t_start_ms"] <= space.details["t_measure_ms"] <= card["t_end_ms"]
    # Recomputing gives the same number, as the Fact-checker needs.
    assert metrics.compute(md, "space_created_by_m2", **params).value == space.value


def test_a_ghost_moves_with_its_team() -> None:
    md = T.REGISTRY.data("m07")
    pf = md.periods[2]
    a, b = pf.index_of(1080000), pf.index_of(1084000)
    c = CR.credit(md, "kes", "kes-09", ["ash-05"], 2, int(pf.t_ms[a]), int(pf.t_ms[b]), [[80, 20], [95, 20], [95, 45], [80, 45]])
    col = md.players.index("ash-05")
    mates = [k for k in md.columns_of("ash") if k != col]
    shift = np.nanmean(pf.xy[b, mates] - pf.xy[a, mates], axis=0)
    assert np.allclose(c.ghosts["ash-05"], np.round(pf.xy[a, col] + shift, 1), atol=0.06)


def test_the_run_classifier_names_every_attacking_run(goal) -> None:
    md, card = goal
    period = card["period"]
    poss = Possession(md)
    runs = [r for r in detect_runs(md, period) if poss.at(period, r.t0_ms) == r.club][:40]
    assert runs
    assert all(len(RC.features(md, r)) == len(RC.FEATURES) for r in runs)
    named = RC.classify(md, runs)
    assert len(named) == len(runs)
    assert {t for t, _ in named} <= set(RC.TYPES) and all(0 < p <= 1 for _, p in named)
