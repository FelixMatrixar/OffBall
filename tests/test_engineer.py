"""The Engineer and the degrade flags (PRD 14.1, 14.7; M3's exit: the Engineer mitigates an injected latency fault),
with the test-only stand-in model."""

from __future__ import annotations

from offball.agents import crew as crew_module
from offball.agents.broadcast import run_moment
from offball.agents.crew import Crew, parse_faults
from offball.agents.engineer import check
from offball.mcp import tools as T
from offball.services.flags import FlagStore
from offball.services.state import MatchState


def _goal_id() -> str:
    return next(c["candidate_id"] for c in T.list_candidates("m07")
                if c["period"] == 2 and c["creator_id"] == "kes-09" and c["type"] == "decoy_run")


def test_faults_parse() -> None:
    assert parse_faults("latency:explainer:4000, error:scout") == {"explainer": ("latency", 4000), "scout": ("error", 0)}
    assert parse_faults("") == {}


def test_flag_changes_revert_unless_kept() -> None:
    flags = FlagStore()
    flags.set("explainer.model_tier", "fast", by="engineer", reason="slow", now=0)
    assert flags.expire(now=599) == [] and flags.get("explainer.model_tier") == "fast"
    reverts = flags.expire(now=600)
    assert [r.new for r in reverts] == ["reasoning"] and flags.get("explainer.model_tier") == "reasoning"
    flags.set("voice.enabled", "off", by="engineer", reason="speech failing", now=0)
    flags.keep("voice.enabled")
    assert flags.expire(now=10_000) == [] and flags.get("voice.enabled") == "off"
    flags.undo("voice.enabled", now=10_001)
    assert flags.get("voice.enabled") == "on"


async def test_the_engineer_mitigates_an_injected_latency_fault(scripted, monkeypatch) -> None:
    monkeypatch.setitem(crew_module.BUDGET_MS, "explainer", 100)  # so a short injected delay is well over budget
    fast, reasoning = scripted(), scripted()
    flags = FlagStore()
    crew = Crew.with_clients({"fast": fast, "reasoning": reasoning}, flags=flags,
                             faults={"explainer": ("latency", 300)})
    state = MatchState("m07")
    assert (await run_moment(crew, state, "m07", _goal_id(), {"live": False})).status == "published"
    assert "DraftOut" in reasoning.calls and "DraftOut" not in fast.calls
    incident = await check(crew, state)
    assert incident is not None and incident.changes[0].flag == "explainer.model_tier"
    assert flags.get("explainer.model_tier") == "fast"
    assert [e.kind for e in state.envelopes][-1] == "incident"
    # The next moment's Explainer runs on the fast tier.
    reasoning.calls.clear()
    await run_moment(crew, MatchState("m07"), "m07", _goal_id(), {"live": False})
    assert "DraftOut" in fast.calls and "DraftOut" not in reasoning.calls
    # Healthy again: the Engineer leaves things alone, and the schedule reverts the flag after 10 minutes.
    crew.telemetry.calls.clear()
    assert await check(crew, state) is None
    flags.expire(now=flags.changes[-1].at + 600)
    assert flags.get("explainer.model_tier") == "reasoning"


async def test_the_producer_can_undo_a_flag_change(no_model_client) -> None:
    client, run_token = no_model_client
    from offball.services.flags import FLAG_STORE

    FLAG_STORE.set("producer.density", "low", by="engineer", reason="late drops")
    r = await client.post("/api/matches/m07/flags/producer.density/undo", headers={"X-Producer-Token": run_token})
    assert r.status_code == 200 and r.json()["values"]["producer.density"] == "standard"
    assert (await client.post("/api/matches/m07/flags/producer.density/undo")).status_code == 401
    flags = (await client.get("/api/flags")).json()
    assert flags["changes"][-1]["by"] == "producer"
