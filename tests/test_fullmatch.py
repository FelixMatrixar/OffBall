"""The match player's backend: the timeline, frames by window, the graphics store, what-ifs from the workers, and the
Tactician's check that it quotes only the numbers it was given."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from offball.agents.schemas import Localized, NumberUsed, TacticianOut
from offball.agents.tactician import misquoted
from offball.eval import agents as E
from offball.services import api
from offball.services import fullmatch as F


@pytest.fixture(scope="module")
def goal() -> tuple[str, str]:
    return E.showcase_moment()


def test_frames_come_a_window_at_a_time(goal) -> None:
    match_id, _ = goal
    w = F.frames(match_id, 2, 1_080_000, 1_080_400)
    assert w["t"][0] >= 1_080_000 and w["t"][-1] <= 1_080_400 and len(w["t"]) == 11
    assert len(w["xy"][0]) == 2 * len(w["ids"]) and len(w["ball"]) == len(w["t"])
    # Substitutes not yet on are null, never NaN.
    assert all(v is None or isinstance(v, float) for v in w["xy"][0])
    assert F.frames(match_id, 2, 0, 10 * 60_000)["to_ms"] == F.MAX_WINDOW_MS
    with pytest.raises(ValueError):
        F.frames(match_id, 3, 0, 1000)


def test_the_timeline_lists_every_moment_with_its_goals(goal) -> None:
    match_id, cid = goal
    tl = F.timeline(match_id)
    assert {p["period"] for p in tl["periods"]} == {1, 2}
    assert tl["home"]["club_id"] and tl["players"] and tl["goals"]
    moment = next(m for m in tl["moments"] if m["candidate_id"] == cid)
    assert moment["outcome"] == "goal" and moment["whatif"] in F.CF.ALTERNATIVES
    starts = [(m["period"], m["t_start_ms"]) for m in tl["moments"]]
    assert starts == sorted(starts)


def test_a_whatif_replays_the_moment_with_another_decision(goal, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(F, "WHATIFS", tmp_path)
    match_id, cid = goal
    w = F.whatif(match_id, cid, "hold")
    c = F.T.candidate(match_id, cid)
    assert set(w["tracks"]) == {c.creator_id, *c.dragged_ids}
    assert all(len(t) >= 2 for t in w["tracks"].values())
    n = w["numbers"]
    assert n["space_lo_m2"] <= n["space_created_m2"] <= n["space_hi_m2"] and n["replays"] == 16
    assert n["space_created_m2"] > 5 and 0 <= n["gap_open_pct_without"] <= 100
    assert w["t_measure_ms"] - w["t_start_ms"] >= F.MIN_WHATIF_MS - 1000
    # Cached: the second call reads the file.
    assert F.whatif(match_id, cid, "hold") == w
    with pytest.raises(ValueError):
        F.whatif(match_id, cid, "teleport")


def test_the_tactician_may_quote_only_the_numbers_it_was_given() -> None:
    words = Localized(en="x", es="x", fr="x")
    out = TacticianOut(headline=words, plain=words, analyst=words,
                       numbers=[NumberUsed(name="space_created_m2", value=34.1), NumberUsed(name="replays", value=16)])
    assert misquoted(out, {"space_created_m2": 34.1, "replays": 16}) == []
    # A negative space said as "that much less" is quoted faithfully.
    assert misquoted(out.model_copy(update={"numbers": [NumberUsed(name="space_created_m2", value=9.3)]}),
                     {"space_created_m2": -9.3}) == []
    out.numbers.append(NumberUsed(name="space_created_m2", value=43.1))
    out.numbers.append(NumberUsed(name="xg", value=0.3))
    assert len(misquoted(out, {"space_created_m2": 34.1, "replays": 16})) == 2


def test_the_api_serves_the_player(goal, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(F, "GRAPHICS", tmp_path / "graphics")
    match_id, cid = goal
    client = TestClient(api.app)
    assert client.get(f"/api/matches/{match_id}/frames", params={"period": 2, "from_ms": 5000, "to_ms": 4000}).status_code == 422
    r = client.get(f"/api/matches/{match_id}/frames", params={"period": 2, "from_ms": 0, "to_ms": 1000})
    assert r.status_code == 200 and "max-age" in r.headers["cache-control"]
    assert client.get(f"/api/matches/{match_id}/graphics").json() == {"overlays": [], "moments": {}}
    assert client.get(f"/api/matches/{match_id}/moments/{cid}/whatifs/teleport").status_code == 404
    assert client.get(f"/api/matches/{match_id}/moments/nope/whatifs/hold").status_code == 404
    listed = next(m for m in client.get("/api/matches").json() if m["match_id"] == match_id)
    assert listed["tracking"] and listed["duration_ms"] > 90 * 60_000


async def test_the_tactician_words_a_whatif_and_they_are_kept(goal, scripted, tmp_path, monkeypatch) -> None:
    from offball.agents.crew import Crew

    monkeypatch.setattr(F, "WHATIFS", tmp_path)
    match_id, cid = goal
    model = scripted()
    crew = Crew.with_clients({"fast": model, "reasoning": model})
    words = await F.whatif_words(crew, match_id, cid, "hold")
    assert words is not None and words["ai_generated"]
    assert set(words["plain"]) == {"en", "es", "fr"} and words["headline"]["en"]
    assert await F.whatif_words(crew, match_id, cid, "hold") == words
    assert model.calls.count("TacticianOut") == 1


async def test_a_viewer_can_ask_the_crew_to_explain_a_moment(goal, scripted, tmp_path, monkeypatch) -> None:
    from offball.agents.crew import Crew

    monkeypatch.setattr(F, "GRAPHICS", tmp_path)
    match_id, cid = goal
    model = scripted()
    asked = F.AskedMoments()
    got = await asked.explain(Crew.with_clients({"fast": model, "reasoning": model}), match_id, cid)
    assert got["status"] == "published" and got["overlays"]
    assert all(o["detected_moment_id"] == cid for o in got["overlays"])
    kept = F.load_graphics(match_id)
    assert kept["moments"][cid]["status"] == "published" and len(kept["overlays"]) == len(got["overlays"])
    # The Scout was told a viewer asked for it.
    assert "requested_by_viewer" in json_of_scout_prompt(model)


def json_of_scout_prompt(model) -> str:
    return " ".join(model.prompts.get("ScoutDecision", []))


def test_a_moment_with_no_gap_has_a_card_but_no_whatif(goal) -> None:
    match_id, _ = goal
    gapless = next(c for c in F.T.REGISTRY.candidates(match_id) if not c.gap_zone)
    card = F.T.moment_card(match_id, gapless.candidate_id)
    assert "gap" not in card["anchors"]
    listed = next(m for m in F.timeline(match_id)["moments"] if m["candidate_id"] == gapless.candidate_id)
    assert listed["whatif"] is None
    with pytest.raises(ValueError):
        F.whatif(match_id, gapless.candidate_id, "hold")
    client = TestClient(api.app)
    assert client.get(f"/api/matches/{match_id}/moments/{gapless.candidate_id}/whatifs/hold").status_code == 404


def test_a_clock_the_viewer_names_becomes_a_match_time() -> None:
    assert F.T.match_time("63:05") == {"clock": "63:05", "period": 2, "t_ms": 1_085_000}
    assert F.T.match_time("12:30") == {"clock": "12:30", "period": 1, "t_ms": 750_000}
    assert F.T.match_time("45+2:10") == {"clock": "45+2:10", "period": 1, "t_ms": 2_830_000}
    assert F.T.match_time("90+3") == {"clock": "90+3:00", "period": 2, "t_ms": 2_880_000}
    with pytest.raises(ValueError):
        F.T.match_time("63:75")
