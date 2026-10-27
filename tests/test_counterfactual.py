"""The counterfactual workers (PRD 10.10, 12.9; ADR 0005): the engine seeded from the observed state, and replays
of the showcase's decoy run without the striker's decision."""

from __future__ import annotations

import numpy as np
import pytest

from offball.eval import agents as E
from offball.mcp import tools as T
from offball.models import counterfactual as CF
from offball.models import credit as CR


@pytest.fixture(scope="module")
def decoy():
    """The showcase's decoy-run goal: Kestrel Bay's No. 9 drags Ashmoor's No. 5 and No. 10 scores."""
    match_id, cid = E.showcase_moment()
    md, card = T.REGISTRY.data(match_id), T.moment_card(match_id, cid)
    club = card["attacking"]["club_id"]
    t_m = CR.measure_instant(md, club, card["period"], card["t_start_ms"], card["t_end_ms"],
                             card["receiver"]["player_id"])
    return md, card, club, t_m


def test_the_engine_starts_where_the_players_were(decoy) -> None:
    md, card, club, t_m = decoy
    period, pf = card["period"], md.periods[card["period"]]
    a = CF.start_frame(md, period, card["t_start_ms"], t_m)
    sim = CF.seed(md, period, int(pf.t_ms[a]))
    # The ball is with whoever has it, or, mid-pass, at the feet of the nearest player of the side in possession.
    assert sim.ball_state == "owned"
    holder = CF._owner(md, period, a)
    assert sim.player[sim.owner].player_id == holder if holder else md.team_of[sim.player[sim.owner].player_id] == club
    for i in range(22):
        if sim.active[i]:
            col = md.players.index(sim.player[i].player_id)
            assert np.allclose(sim.pos[i], pf.xy[a, col], atol=1e-4)
    assert [t.direction for t in sim.teams] == [md.direction(period, md.home), md.direction(period, md.away)]


def test_the_engine_knows_only_what_was_observed(decoy) -> None:
    md, card, _, _ = decoy
    league = CF.observed_league(md, 1, 0)
    assert {c.style.archetype for c in league.clubs} == {"observed"}
    # At kick-off there is no tracking yet, so the role's league-typical top speed stands in.
    assert league.player("kes-09").attributes.top_speed == CF.PHYSICAL["ST"][0]
    later = CF.observed_league(md, card["period"], md.periods[card["period"]].index_of(card["t_start_ms"]))
    seen = later.player("kes-09").attributes.top_speed
    assert seen != CF.PHYSICAL["ST"][0] and 8.0 < seen < 9.9


def test_each_moment_type_has_its_alternative(decoy) -> None:
    md, card, _, t_m = decoy
    args = (card["creator"]["player_id"], card["period"], card["t_start_ms"], t_m)
    assert CF.instead(md, "decoy_run", *args).intent == "anchor"
    inside = CF.instead(md, "switch_of_play", *args)
    assert inside.intent == "support" and abs(inside.point[1] - CF.HALF_WIDTH) == pytest.approx(4.0)
    drop = CF.instead(md, "pinning", *args)
    assert drop.intent == "support" and drop.point is not None


def test_replays_without_the_decoy_give_credit_an_interval_and_a_ghost(decoy) -> None:
    md, card, club, t_m = decoy
    args = (md, card["type"], club, card["creator"]["player_id"], [d["player_id"] for d in card["dragged"]],
            card["period"], card["t_start_ms"], t_m, card["anchors"]["gap"]["polygon"])
    cf = CF.counterfactual(*args, replays=4)
    assert cf.replays == 4 and len(cf.without_area_m2) == 4
    low, high = cf.space_interval_m2
    assert low <= cf.space_created_m2 <= high and cf.space_created_m2 > 0
    assert len(cf.ghost) >= 2 and cf.ghost[0][0] == cf.t_start_ms <= cf.ghost[-1][0] <= t_m
    # The same seed replays the same moment the same way.
    assert CF.counterfactual(*args, replays=4) == cf
