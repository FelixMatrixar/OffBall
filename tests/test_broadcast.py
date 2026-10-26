"""The broadcast workflow's wiring and publishing, with the test-only stand-in model."""

from __future__ import annotations

import json

import jsonschema
import pytest

from offball.agents import crew as crew_module
from offball.agents.broadcast import run_moment
from offball.agents.crew import Crew
from offball.agents.publish import PublishError, build_overlays
from offball.agents.schemas import DraftOut, ModeScript, PlannedOverlay, Schedule
from offball.mcp import tools as T
from offball.services.replay import CONTRACTS
from offball.services.state import MatchState


def _goal_id() -> str:
    return next(c["candidate_id"] for c in T.list_candidates("m07")
                if c["period"] == 2 and c["creator_id"] == "kes-09" and c["type"] == "decoy_run")


async def test_a_moment_goes_on_air(scripted) -> None:
    model = scripted()
    state = MatchState("m07")
    outcome = await run_moment(Crew.with_clients({"fast": model, "reasoning": model}), state, "m07", _goal_id(),
                               {"min_gap_s": 20, "approval": "auto", "live": False})
    assert outcome.status == "published", outcome.note
    overlays = list(state.overlays.values())
    assert len(overlays) == len(outcome.overlay_ids) and overlays
    assert {o.mode for o in overlays} == {"casual", "learn", "analyst", "player", "audio", "broadcaster"}
    schema = json.loads((CONTRACTS / "overlay-upsert.schema.json").read_text(encoding="utf-8"))
    for msg in state.partner_log:
        if msg["type"] == "overlay.upsert":
            jsonschema.validate(msg, schema)
    ring = next(o for o in overlays if o.mode == "broadcaster" and o.kind == "gap_ring")
    assert ring.approval == "pending"
    assert all(o.t_end_ms - o.t_start_ms >= 2500 for o in overlays)
    captions = [o for o in overlays if o.kind == "caption"]
    assert all(set(o.text) == {"en", "es", "fr"} and set(o.speech) == {"en", "es", "fr"} for o in captions)
    assert all(set(o.a11y_text) == {"en", "es", "fr"} for o in captions)
    assert captions[0].speech["es"].ssml.startswith('<speak version="1.0" xml:lang="es">')
    kinds = [e.kind for e in state.envelopes]
    assert kinds[:3] == ["moment", "draft", "verdict"] and "schedule" in kinds


async def test_a_rejected_draft_is_rewritten(scripted) -> None:
    model = scripted(reject_first_draft=True)
    state = MatchState("m07")
    outcome = await run_moment(Crew.with_clients({"fast": model, "reasoning": model}), state, "m07", _goal_id(),
                               {"live": False})
    assert outcome.status == "published"
    assert model.calls.count("DraftOut") == 2
    verdicts = [e.payload["passed"] for e in state.envelopes if e.kind == "verdict"]
    assert verdicts == [False, True]


async def test_a_failed_persona_drops_only_its_mode(scripted) -> None:
    model = scripted(failing_mode="audio")
    state = MatchState("m07")
    outcome = await run_moment(Crew.with_clients({"fast": model, "reasoning": model}), state, "m07", _goal_id(),
                               {"live": False})
    assert outcome.status == "published", outcome.note
    assert {o.mode for o in state.overlays.values()} == {"casual", "learn", "analyst", "player", "broadcaster"}
    audio = [e.payload for e in state.envelopes if e.kind == "script" and e.payload["mode"] == "audio"]
    assert audio and audio[0]["lines"] == []


async def test_running_a_moment_again_airs_no_duplicate(scripted) -> None:
    crew = Crew.with_clients({"fast": scripted(), "reasoning": scripted()})
    state = MatchState("m07")
    first = await run_moment(crew, state, "m07", _goal_id(), {"live": False})
    sent = sum(m["type"] == "overlay.upsert" for m in state.partner_log)
    second = await run_moment(crew, state, "m07", _goal_id(), {"live": False})
    assert first.overlay_ids == second.overlay_ids
    assert sum(m["type"] == "overlay.upsert" for m in state.partner_log) == sent
    num = _goal_id().rsplit("-d", 1)[1]
    assert all(oid.startswith(f"m07-o{num}-") for oid in first.overlay_ids)
    assert state.tokens.used > 0


async def test_the_token_budget_limits_what_airs(scripted) -> None:
    spent = MatchState("m07")
    spent.tokens.used = spent.tokens.budget
    out = await run_moment(Crew.with_clients({"fast": scripted(), "reasoning": scripted()}), spent, "m07", _goal_id(),
                           {"live": False})
    assert out.status == "skipped" and "budget" in out.note
    nearly = MatchState("m07")
    nearly.tokens.used = int(nearly.tokens.budget * 0.85)
    model = scripted(scout_priority=2)
    out = await run_moment(Crew.with_clients({"fast": model, "reasoning": model}), nearly, "m07", _goal_id(),
                           {"live": False})
    assert out.status == "skipped" and model.calls == ["ScoutDecision"]


async def test_a_call_past_its_time_limit_fails(scripted, monkeypatch) -> None:
    monkeypatch.setitem(crew_module.TIME_LIMIT_S, "scout", 0.05)
    model = scripted(slow={"ScoutDecision": 1.0})
    out = await run_moment(Crew.with_clients({"fast": model, "reasoning": model}), MatchState("m07"), "m07",
                           _goal_id(), {"live": False})
    assert out.status == "failed" and "within" in out.note


def test_a_graphic_on_a_run_the_moment_lacks_goes_back_to_the_producer(scripted) -> None:
    """A moment with no run path (a switch of play, say) can't carry a run arrow: the schedule goes back to the
    Producer with the reason, rather than the moment failing."""
    card = T.moment_card("m07", _goal_id())
    card = {**card, "anchors": {**card["anchors"], "run": {"player_id": "kes-11", "from_xy": [], "to_xy": []}}}
    model = scripted()
    script = model._answer(ModeScript, "Viewing mode: casual\n")
    draft = model._answer(DraftOut, "")
    plan = Schedule(note="", overlays=[PlannedOverlay(mode="casual", kind="run_arrow", anchor="run", text_ref="none",
                                                      line_index=None, start_beat="run_start", start_offset_s=0,
                                                      end_beat="after", end_offset_s=3, priority=1, approval="auto")])
    with pytest.raises(PublishError, match="no anchor 'run'"):
        build_overlays(card, {"casual": script}, plan, draft, None)
