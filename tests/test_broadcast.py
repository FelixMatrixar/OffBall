"""The broadcast workflow's wiring and publishing, with the test-only stand-in model."""

from __future__ import annotations

import json

import jsonschema

from offball.agents.broadcast import run_moment
from offball.agents.crew import Crew
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
    assert all(o.text.get("en") for o in overlays if o.kind == "caption")
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
