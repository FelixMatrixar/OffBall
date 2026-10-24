"""The OffBall API (PRD 11.7; INTEGRATION.md 6): the calls the frontend makes, and the live stream.

Run it with `offball serve api`. The stream sends the messages in INTEGRATION.md section 4 as Server-Sent
Events, one message per event.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from offball.agents.crew import Crew
from offball.agents.llm import ModelNotConfigured, model_configured
from offball.agents.pundit import answer as pundit_answer
from offball.mcp import tools as T
from offball.services.emitter import EmitterConfig
from offball.services.runner import RUNS, current_state, start_run
from offball.services.state import iso_now

log = logging.getLogger("offball.api")

@contextlib.asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    for run in RUNS.values():
        run.stop.set()


app = FastAPI(title="OffBall API", version="0.1.0", lifespan=lifespan,
              description="Off-ball match intelligence from synthetic football data. All match data is synthetic.")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
_crew: Crew | None = None


def crew() -> Crew:
    """The agents, built on first use. Without a configured model they can't run, and the API says so."""
    global _crew
    if _crew is None:
        try:
            _crew = Crew.from_env()
        except ModelNotConfigured as exc:
            raise HTTPException(503, str(exc)) from exc
    return _crew


def _match_dir(match_id: str):
    dirs = T.REGISTRY.match_dirs()
    if match_id not in dirs:
        raise HTTPException(404, f"Unknown match {match_id}")
    return dirs[match_id]


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"ok": True, "model_configured": model_configured(), "live_runs": sorted(k for k, r in RUNS.items()
                                                                                    if not r.done.is_set())}


@app.get("/api/matches")
def matches() -> list[dict[str, Any]]:
    return T.list_matches()


@app.get("/api/matches/{match_id}")
def match(match_id: str) -> dict[str, Any]:
    return json.loads((_match_dir(match_id) / "match.json").read_text(encoding="utf-8"))


@app.get("/api/matches/{match_id}/candidates")
def candidates(match_id: str) -> list[dict[str, Any]]:
    _match_dir(match_id)
    return T.list_candidates(match_id)


@app.get("/api/matches/{match_id}/stream")
async def stream(match_id: str, period: int | None = None, from_ms: int = 0, to_ms: int | None = None,
                 speed: float = Query(1.0, ge=0.25, le=60), close_at_end: bool = False) -> EventSourceResponse:
    """The match's live stream. Starts a live run of the match if none is playing. The stream stays open after
    the run ends, ticking the clock, unless close_at_end is set."""
    match_dir = _match_dir(match_id)
    agents = crew() if model_configured() else None
    run = start_run(match_dir, EmitterConfig(speed=speed, period=period, from_ms=from_ms, to_ms=to_ms), agents)
    state = run.state
    queue = state.subscribe(maxsize=10_000)

    def public(m: dict) -> bool:
        """Unapproved graphics go only to the producer, never to the public stream (PRD 11.6)."""
        return m["type"] != "overlay.upsert" or m["overlay"]["approval"] in ("auto", "approved")

    async def events():
        try:
            # A late joiner gets the score and the graphics already on air.
            snapshot = [m for m in state.partner_log if m["type"] == "match.status"][-1:]
            snapshot += [{"type": "overlay.upsert", "match_id": match_id, "overlay": o.model_dump(mode="json"),
                          "sent_at": iso_now()} for o in state.live_overlays()]
            for m in snapshot:
                if public(m):
                    yield {"data": json.dumps(m, separators=(",", ":"))}
            # One message per event: every reader handles that, including the partner template. The stream
            # stays open after the run ends and keeps the clock ticking, so silence never reads as a stall.
            while True:
                try:
                    m = await asyncio.wait_for(queue.get(), 1.0)
                except TimeoutError:
                    if run.done.is_set() and close_at_end:
                        break
                    if run.done.is_set():
                        period, t_ms = run.live.clock
                        m = {"type": "clock.sync", "match_id": match_id, "period": period, "t_ms": t_ms,
                             "speed": run.config.speed, "server_time": iso_now()}
                    else:
                        continue
                if public(m):
                    yield {"data": json.dumps(m, separators=(",", ":"))}
        finally:
            state.unsubscribe(queue)

    return EventSourceResponse(events(), ping=15)


class AskBody(BaseModel):
    question: str
    period: int | None = None
    t_ms: int | None = None
    mode: str = "casual"
    lang: str = "en"
    fav: str | None = None


@app.post("/api/matches/{match_id}/ask")
async def ask(match_id: str, body: AskBody) -> EventSourceResponse:
    _match_dir(match_id)
    agents = crew()

    async def events():
        async for kind, payload in pundit_answer(agents, match_id, body.question, body.period, body.t_ms, body.mode,
                                                 body.fav):
            yield {"event": kind, "data": json.dumps(payload, ensure_ascii=False)}

    return EventSourceResponse(events())


class ApprovalBody(BaseModel):
    overlay_id: str
    decision: str  # approve, hold, skip or retract
    by: str = "producer"
    note: str = ""


@app.post("/api/matches/{match_id}/approvals", status_code=202)
def approve(match_id: str, body: ApprovalBody) -> dict[str, Any]:
    state = current_state(match_id)
    if state is None or body.overlay_id not in state.overlays:
        raise HTTPException(404, f"No overlay {body.overlay_id} in a run of {match_id}")
    o = state.overlays[body.overlay_id]
    if body.decision == "retract":
        state.retract_overlay(o.overlay_id, "producer")
    else:
        approval = {"approve": "approved", "hold": "held", "skip": "skipped"}.get(body.decision)
        if approval is None:
            raise HTTPException(422, "decision must be approve, hold, skip or retract")
        state.upsert_overlay(o.model_copy(update={"rev": o.rev + 1, "approval": approval}))
    state.append("approval", {"overlay_id": o.overlay_id, "decision": body.decision, "by": body.by,
                              "note": body.note}, produced_by="producer")
    return {"overlay_id": o.overlay_id, "decision": body.decision}


@app.get("/api/matches/{match_id}/overlays/{overlay_id}/trace")
def trace(match_id: str, overlay_id: str) -> dict[str, Any]:
    state = current_state(match_id)
    if state is None or overlay_id not in state.overlays:
        raise HTTPException(404, f"No overlay {overlay_id} in a run of {match_id}")
    cid = state.overlays[overlay_id].detected_moment_id
    steps = [{"seq": e.seq, "agent": e.produced_by, "kind": e.kind, "wall_ms": e.wall_ms, "payload": e.payload}
             for e in state.envelopes
             if e.payload.get("candidate_id") == cid]
    return {"overlay_id": overlay_id, "candidate_id": cid, "steps": steps}


