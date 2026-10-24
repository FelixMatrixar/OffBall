"""The API: matches, the live stream, and how it behaves with no model configured."""

from __future__ import annotations

import json

import httpx
import pytest

from offball.agents import llm
from offball.services.api import app


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
