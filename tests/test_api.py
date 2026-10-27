"""The API: matches, the live stream, and how it behaves with no model configured."""

from __future__ import annotations

import json

import httpx
import jsonschema
import pytest

from offball.agents import llm
from offball.services.api import app
from offball.services.replay import CONTRACTS


@pytest.fixture
def no_model(monkeypatch):
    monkeypatch.setattr(llm.ModelSettings, "from_env",
                        classmethod(lambda cls: (_ for _ in ()).throw(llm.ModelNotConfigured("no model"))))


@pytest.fixture
async def client():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def test_matches(client) -> None:
    r = await client.get("/api/matches")
    assert r.status_code == 200 and any(m["match_id"] == "m07" for m in r.json())
    r = await client.get("/api/matches/m07")
    assert r.json()["home"]["name"] == "Kestrel Bay"
    assert (await client.get("/api/matches/nope")).status_code == 404


async def test_ask_needs_a_model(client, no_model) -> None:
    r = await client.post("/api/matches/m07/ask", json={"question": "Who made the goal?"})
    assert r.status_code == 503 and "model" in r.json()["detail"]


async def test_stream_without_a_model(client, no_model) -> None:
    lines = []
    url = "/api/matches/m07/stream?period=2&from_ms=1243000&to_ms=1245000&speed=60&close_at_end=1"
    async with client.stream("GET", url) as r:
        assert r.status_code == 200
        async for line in r.aiter_lines():
            if line.startswith("data:"):
                lines.append(json.loads(line[5:].strip()))
            goal = [m for m in lines if m["type"] == "match.status" and m["score"]["kes"] == 1]
            if goal and len(lines) > 60:
                break
    types = {m["type"] for m in lines}
    assert {"frame", "clock.sync", "match.status"} <= types
    frame_schema = json.loads((CONTRACTS / "frame-message.schema.json").read_text(encoding="utf-8"))
    for m in lines:
        if m["type"] == "frame":
            jsonschema.validate(m, frame_schema)
    assert "overlay.upsert" not in types, "without a model no graphics air"


async def test_a_finished_run_is_joined_not_replayed(client, no_model) -> None:
    from offball.services.runner import RUNS

    url = "/api/matches/m07/stream?period=2&from_ms=1243000&to_ms=1244000&speed=60&close_at_end=1"
    async with client.stream("GET", url) as r:
        _ = [line async for line in r.aiter_lines()]
    first = RUNS["m07"]
    async with client.stream("GET", url) as r:
        async for line in r.aiter_lines():
            if line.startswith("data:"):
                break
    assert RUNS["m07"] is first and first.done.is_set()


async def test_ask_streams_each_tool_then_the_checked_answer(client, scripted, monkeypatch) -> None:
    from offball.agents.crew import Crew
    from offball.services import api

    model = scripted()
    monkeypatch.setattr(api, "_crew", Crew.with_clients({"fast": model, "reasoning": model}))
    events = []
    body = {"question": "Why did No. 5 follow?", "period": 2, "t_ms": 1086000, "mode": "learn", "lang": "es"}
    async with client.stream("POST", "/api/matches/m07/ask", json=body) as r:
        assert r.status_code == 200
        name = None
        async for line in r.aiter_lines():
            if line.startswith("event:"):
                name = line[6:].strip()
            elif line.startswith("data:"):
                events.append((name, json.loads(line[5:].strip())))
    assert [e for e, _ in events] == ["tool", "answer"]
    assert events[0][1] == {"name": "match_facts"}
    answer = events[1][1]
    jsonschema.validate(answer, json.loads((CONTRACTS / "answer.schema.json").read_text(encoding="utf-8")))
    assert answer["state"] == "ok" and answer["tools"] == ["match_facts"]
    assert answer["claims"][0]["verified"] and answer["claims"][0]["text"].startswith("El 9")
    # The play that shows it stops where the viewer is, and rings only players who were on the pitch.
    assert answer["show"] == {"period": 2, "from_ms": 1_079_500, "to_ms": 1_086_000, "player_ids": ["kes-09", "ash-05"],
                              "moment_id": None}


async def test_suggestions_are_three_questions_about_what_was_seen(client) -> None:
    r = await client.get("/api/matches/m07/suggestions", params={"period": 2, "t_ms": 1091000})
    assert r.status_code == 200
    chips = r.json()
    assert len(chips) == 3 and all(q.endswith("?") for q in chips)
    assert any(q.startswith("What did No. ") for q in chips)


async def test_producer_calls_need_the_runs_token(client, no_model) -> None:
    r = await client.post("/api/live-runs", json={"match_id": "m07", "period": 2, "from_ms": 1243000,
                                                  "to_ms": 1244000, "speed": 60})
    assert r.status_code == 201
    run = r.json()
    assert run["producer_token"] and run["stream"].startswith("/api/matches/m07/stream?period=2")
    body = {"overlay_id": "m07-o0001", "decision": "approve"}
    assert (await client.post("/api/matches/m07/approvals", json=body)).status_code == 401
    assert (await client.post("/api/matches/m07/approvals", json=body,
                              headers={"X-Producer-Token": "guess"})).status_code == 401
    r = await client.post("/api/matches/m07/approvals", json=body, headers={"X-Producer-Token": run["producer_token"]})
    assert r.status_code == 404, "the token is right; there is just no such graphic without a model"


def test_the_trace_has_a_row_per_step() -> None:
    from offball.mcp import tools as T
    from offball.services.api import trace_rows
    from offball.services.state import MatchState

    state = MatchState("m07")
    found = T.REGISTRY.candidates("m07")[0].model_copy(update={"candidate_id": "m07-d0001"})
    state.append("candidate", found, produced_by="interpret")
    for kind, agent, payload in [("moment", "scout", {}), ("draft", "explainer", {}),
                                 ("verdict", "factchecker", {"passed": False}), ("draft", "explainer", {}),
                                 ("verdict", "factchecker", {"passed": True}),
                                 ("script", "persona", {"mode": "casual", "lines": [1]}),
                                 ("script", "persona", {"mode": "audio", "lines": []}),
                                 ("schedule", "producer", {})]:
        state.append(kind, {"candidate_id": "m07-d0001", **payload}, produced_by=agent)
    rows = trace_rows([e for e in state.envelopes if e.payload.get("candidate_id") == "m07-d0001"])
    assert [r["agent"] for r in rows] == ["Scout", "Explainer", "Fact-checker", "Explainer", "Fact-checker",
                                          "Persona · casual", "Persona · audio", "Producer"]
    assert [r["kind"] for r in rows].count("rejected") == 1 and rows[6]["kind"] == "fallback"
    assert rows[5]["start"] == rows[6]["start"], "the Personas start together"
    assert all(0 <= r["start"] <= r["end"] for r in rows)
