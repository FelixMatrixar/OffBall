"""Feed corrections (PRD 10.6, 14.11): the emitter's correction fault, ingest's envelope, and the crew's re-check,
with the test-only stand-in model."""

from __future__ import annotations

import json

import jsonschema

from offball.agents.broadcast import run_moment
from offball.agents.corrections import handle_correction
from offball.agents.crew import Crew
from offball.mcp import tools as T
from offball.services.emitter import Correction, EmitterConfig, FeedEmitter
from offball.services.live import LiveMatch
from offball.services.replay import CONTRACTS
from offball.services.state import MatchState

from .conftest import GOAL_WINDOW

CITED = "m07-e0948"  # the event the stand-in's goal claim cites


def _goal_id() -> str:
    return next(c["candidate_id"] for c in T.list_candidates("m07")
                if c["period"] == 2 and c["creator_id"] == "kes-09" and c["type"] == "decoy_run")


async def _aired(model) -> tuple[Crew, MatchState]:
    crew = Crew.with_clients({"fast": model, "reasoning": model})
    state = MatchState("m07")
    assert (await run_moment(crew, state, "m07", _goal_id(), {"live": False})).status == "published"
    return crew, state


async def test_a_correction_replaces_the_graphics_then_retracts_them(scripted) -> None:
    crew, state = await _aired(scripted(reject_rechecks=True))
    cited = {o.overlay_id for o in state.live_overlays() if CITED in o.evidence_ids}
    assert cited
    outcomes = await handle_correction(crew, state, "m07", CITED, {"live": False})
    assert [o.status for o in outcomes] == ["corrected"]
    msgs = [m for m in state.partner_log if m["type"] in ("overlay.upsert", "overlay.retract")]
    retracts = [k for k, m in enumerate(msgs) if m["type"] == "overlay.retract"]
    replacements = [k for k, m in enumerate(msgs) if m["type"] == "overlay.upsert"
                    and "correction" in m["overlay"]["labels"]]
    assert retracts and replacements and max(replacements) < min(retracts)
    ids = {msgs[k]["overlay"]["overlay_id"] for k in replacements}
    schema = json.loads((CONTRACTS / "overlay-retract.schema.json").read_text(encoding="utf-8"))
    for k in retracts:
        jsonschema.validate(msgs[k], schema)
        assert msgs[k]["reason"] == "correction" and msgs[k]["corrects_event_id"] == CITED
        assert msgs[k]["replacement_id"] in ids
    assert cited.isdisjoint(o.overlay_id for o in state.live_overlays())
    assert any(e.kind == "recheck" and not e.payload["passed"] for e in state.envelopes)


async def test_claims_that_still_hold_stay_on_air(scripted) -> None:
    crew, state = await _aired(scripted())
    before = {o.overlay_id for o in state.live_overlays()}
    outcomes = await handle_correction(crew, state, "m07", CITED, {"live": False})
    assert [o.status for o in outcomes] == ["kept"]
    assert {o.overlay_id for o in state.live_overlays()} == before
    assert not any(m["type"] == "overlay.retract" for m in state.partner_log)


def test_the_emitter_corrects_an_event_and_ingest_records_it(m07) -> None:
    plain = FeedEmitter(m07, EmitterConfig(faults=False, **GOAL_WINDOW))
    target = next(m["payload"] for m in (t.msg for t in plain.messages()) if m["kind"] == "event")
    fix = Correction(target["event_id"], "player_id", "kes-07", after_ms=1000)
    emitter = FeedEmitter(m07, EmitterConfig(faults=False, corrections=(fix,), **GOAL_WINDOW))
    sent = [t.msg for t in emitter.messages()]
    corrected = [m for m in sent if m["kind"] == "correction"]
    assert len(corrected) == 1 and corrected[0]["corrects_event_id"] == target["event_id"]
    assert corrected[0]["payload"]["player_id"] == "kes-07"
    state = MatchState("m07")
    live = LiveMatch(emitter.info, state)
    for m in sent:
        live.ingest(m)
    assert [e.payload["event_id"] for e in state.of_kind("correction")] == [target["event_id"]]
    assert next(e for e in live.events if e.event_id == target["event_id"]).player_id == "kes-07"
