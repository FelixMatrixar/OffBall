"""Traces (PRD 14.3, AI-6): every agent call is a span inside its moment's span, linked to the envelopes and graphics
it produced, and no prompt or question text is ever written to a span (PRD 18.6). Uses the test-only stand-in model."""

from __future__ import annotations

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from offball.agents.broadcast import run_moment
from offball.agents.crew import Crew
from offball.mcp import tools as T
from offball.services.state import MatchState

EXPORTER = InMemorySpanExporter()


@pytest.fixture(scope="module", autouse=True)
def provider():
    current = trace.get_tracer_provider()
    if not isinstance(current, TracerProvider):
        current = TracerProvider()
        trace.set_tracer_provider(current)
    current.add_span_processor(SimpleSpanProcessor(EXPORTER))
    yield


async def test_a_moment_is_one_trace_with_a_span_per_agent_call(scripted) -> None:
    EXPORTER.clear()
    cid = next(c["candidate_id"] for c in T.list_candidates("m07")
               if c["period"] == 2 and c["creator_id"] == "kes-09" and c["type"] == "decoy_run")
    model = scripted(reject_first_draft=True)
    state = MatchState("m07")
    out = await run_moment(Crew.with_clients({"fast": model, "reasoning": model}), state, "m07", cid, {"live": False})
    assert out.status == "published"
    spans = EXPORTER.get_finished_spans()
    moment = next(s for s in spans if s.name == "moment")
    agents = [s for s in spans if s.name.startswith("agent ")]
    assert {s.name for s in agents} >= {"agent scout", "agent explainer", "agent factchecker", "agent persona",
                                        "agent producer"}
    assert sum(s.name == "agent explainer" for s in agents) == 2, "the rewrite after the rejection is traced"
    assert all(s.context.trace_id == moment.context.trace_id for s in agents)
    assert all(s.attributes["offball.candidate_id"] == cid for s in agents)
    # Hand-offs are events on whichever span of the moment's trace made them (a workflow step or the moment itself).
    in_trace = [s for s in spans if s.context.trace_id == moment.context.trace_id]
    seqs = sorted(e.attributes["offball.seq"] for s in in_trace for e in s.events if e.name == "handoff")
    assert seqs == [e.seq for e in state.envelopes]
    sent = {e.attributes["offball.overlay_id"] for s in spans for e in s.events if e.name == "overlay"}
    assert sent == set(out.overlay_ids)
    words = [str(v) for s in spans for v in s.attributes.values()] + \
            [str(v) for s in spans for e in s.events for v in e.attributes.values()]
    assert not any("Moment card" in w or "Watch No. 9" in w for w in words), "no prompts or lines in traces"
