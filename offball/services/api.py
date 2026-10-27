"""The OffBall API (PRD 11.7; INTEGRATION.md 6): the calls the frontend makes, and the live stream.

Run it with `offball serve api`. The stream sends the messages in INTEGRATION.md section 4 as Server-Sent
Events, one message per event.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import os
import secrets
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from offball.agents.crew import Crew
from offball.agents.llm import ModelNotConfigured, model_configured
from offball.agents.pundit import answer as pundit_answer
from offball.core import number_of
from offball.mcp import tools as T
from offball.services import fullmatch as F
from offball.services import stats as S
from offball.services.bus import ValkeyBus, bus_url
from offball.services.emitter import Correction, EmitterConfig
from offball.services.flags import FLAG_STORE
from offball.services.runner import RUNS, current_state, start_run
from offball.services.state import iso_now

log = logging.getLogger("offball.api")
STATS_CACHE = T.ROOT / "replays" / "cache" / "stats"  # git ignores replays/

@contextlib.asynccontextmanager
async def lifespan(_: FastAPI):
    # Detect the moments of the matches named in OFFBALL_WARM in the background, so the first question about them
    # doesn't wait minutes (the result is cached on disk after the first time).
    warming = [asyncio.create_task(asyncio.to_thread(T.REGISTRY.candidates, m))
               for m in os.environ.get("OFFBALL_WARM", "").split(",") if m.strip()]
    yield
    for run in RUNS.values():
        run.stop.set()
    for task in warming:
        task.cancel()


app = FastAPI(title="OffBall API", version="0.1.0", lifespan=lifespan,
              description="Off-ball match intelligence from synthetic football data. All match data is synthetic.")
# On the VM only the web app's origins may call from a browser (PRD 18.12); up.sh sets them.
ORIGINS = [o.strip() for o in os.environ.get("OFFBALL_WEB_ORIGINS", "*").split(",") if o.strip()]
app.add_middleware(CORSMiddleware, allow_origins=ORIGINS, allow_methods=["*"], allow_headers=["*"])
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
    return {"ok": True, "model_configured": model_configured(), "bus": "valkey" if bus_url() else "in-process",
            "live_runs": sorted(k for k, r in RUNS.items() if not r.done.is_set())}


@app.get("/api/ready")
async def ready() -> dict[str, Any]:
    """Ready to start live runs (OPS-5): the event bus answers, when there is one."""
    if bus_url():
        bus = ValkeyBus()
        try:
            await bus.ping()
        except Exception as exc:
            raise HTTPException(503, f"The event bus doesn't answer: {type(exc).__name__}") from exc
        finally:
            await bus.close()
    return {"ready": True}


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


_timeline_locks: dict[str, asyncio.Lock] = {}
_whatif_slots = asyncio.Semaphore(int(os.environ.get("OFFBALL_WHATIFS_AT_ONCE", "1")))
FINISHED = "public, max-age=86400"  # a finished match's frames never change


def _finished(match_id: str) -> None:
    _match_dir(match_id)
    if T.REGISTRY.is_live(match_id):
        raise HTTPException(409, f"{match_id} is being played live; the match player plays finished matches")


@app.get("/api/matches/{match_id}/timeline")
async def timeline(match_id: str) -> dict[str, Any]:
    """What the match player needs before the first frame: clubs, kits, line-ups, periods, goals and every detected
    moment, with whether the crew has explained it (INTEGRATION.md 6.10). The first call finds the moments, which
    takes a minute or two; after that they are cached on disk."""
    _finished(match_id)
    async with _timeline_locks.setdefault(match_id, asyncio.Lock()):
        return await asyncio.to_thread(F.timeline, match_id)


@app.get("/api/matches/{match_id}/frames")
async def match_frames(match_id: str, response: Response, period: int, from_ms: int = Query(ge=0),
                       to_ms: int = Query(gt=0)) -> dict[str, Any]:
    """Tracked frames for a window of at most a minute, for the match player to play and seek through."""
    _finished(match_id)
    if to_ms <= from_ms:
        raise HTTPException(422, "to_ms must be after from_ms")
    try:
        value = await asyncio.to_thread(F.frames, match_id, period, from_ms, to_ms)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    response.headers["Cache-Control"] = FINISHED
    return value


@app.get("/api/matches/{match_id}/graphics")
def graphics(match_id: str) -> dict[str, Any]:
    """The graphics the broadcast crew made for the match's moments, and what happened to each moment it saw."""
    _finished(match_id)
    data = F.load_graphics(match_id)
    return {"overlays": [o for o in data["overlays"] if o.get("approval") in ("auto", "approved")],
            "moments": data["moments"]}


def _moment(match_id: str, candidate_id: str):
    _finished(match_id)
    try:
        return T.candidate(match_id, candidate_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.post("/api/matches/{match_id}/moments/{candidate_id}/graphics")
async def explain_moment(match_id: str, candidate_id: str) -> dict[str, Any]:
    """Send a moment the crew hasn't explained to it now, as a viewer opens it: one to three minutes, within the match's
    token budget for viewers' requests. The answer is the moment's outcome and its graphics."""
    _moment(match_id, candidate_id)
    return await F.ASKED.explain(crew(), match_id, candidate_id)


@app.get("/api/matches/{match_id}/moments/{candidate_id}/whatifs/{option}")
async def whatif(match_id: str, candidate_id: str, option: str) -> dict[str, Any]:
    """Replay a moment with its creator making an alternative (hold, inside or drop): what his decision caused,
    with the paths of the players who were free to react. A few seconds the first time; cached after."""
    _moment(match_id, candidate_id)
    if option not in F.CF.ALTERNATIVES:
        raise HTTPException(404, f"The alternatives are {', '.join(F.CF.ALTERNATIVES)}")
    async with _whatif_slots:
        try:
            return await asyncio.to_thread(F.whatif, match_id, candidate_id, option)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc


@app.get("/api/matches/{match_id}/moments/{candidate_id}/whatifs/{option}/words")
async def whatif_words(match_id: str, candidate_id: str, option: str) -> dict[str, Any]:
    """The Tactician's words for a what-if, in English, Spanish and French; `words` is null when it couldn't give
    faithful ones."""
    _moment(match_id, candidate_id)
    if option not in F.CF.ALTERNATIVES:
        raise HTTPException(404, f"The alternatives are {', '.join(F.CF.ALTERNATIVES)}")
    agents = crew()
    async with _whatif_slots:
        try:
            await asyncio.to_thread(F.whatif, match_id, candidate_id, option)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc
    return {"words": await F.whatif_words(agents, match_id, candidate_id, option)}


def _stat(match_id: str, name: str, player_id: str | None, until: tuple[int, int] | None,
          window_from: tuple[int, int] | None) -> Any:
    md = T.REGISTRY.data(match_id)
    end = until or S.end_of(md)
    cands = T.REGISTRY.candidates(match_id) if name in ("leaders", "focus", "run_map") else []
    return S.compute(md, cands, name, end, player_id, (window_from, end) if window_from else None)


@app.get("/api/matches/{match_id}/stats/{name}")
async def stat(match_id: str, name: str, player_id: str | None = None, period: int | None = None,
               t_ms: int | None = None, from_ms: int | None = None) -> Any:
    """Panel numbers and chart data in the frontend's shapes (INTEGRATION.md 6.5), up to `period` and `t_ms` (the
    whole match when left out). `focus` reads the moment from `from_ms` to `t_ms`. A finished match's answers are
    cached on disk."""
    match_dir = _match_dir(match_id)
    until = (period, t_ms) if period is not None and t_ms is not None else None
    window_from = (period, from_ms) if until and from_ms is not None else None
    args = [match_id, name, player_id, until, window_from]
    cache = None
    manifest = match_dir / "manifest.json"
    if not T.REGISTRY.is_live(match_id) and manifest.exists():
        digest = hashlib.sha256(manifest.read_bytes() + Path(S.__file__).read_bytes() + json.dumps(args).encode())
        cache = STATS_CACHE / f"{match_id}-{digest.hexdigest()[:24]}.json"
        if cache.exists():
            return json.loads(cache.read_text(encoding="utf-8"))
    try:
        value = await asyncio.to_thread(_stat, *args)
    except S.StatUnavailable as exc:
        raise HTTPException(404, str(exc)) from exc
    if cache is not None:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(value, separators=(",", ":")), encoding="utf-8", newline="\n")
    return value


@app.get("/api/matches/{match_id}/stream")
async def stream(match_id: str, period: int | None = None, from_ms: int = 0, to_ms: int | None = None,
                 speed: float = Query(1.0, ge=0.25, le=60), close_at_end: bool = False,
                 producer: str | None = None) -> EventSourceResponse:
    """The match's live stream. Starts a live run of the match if none is playing. The stream stays open after
    the run ends, ticking the clock, unless close_at_end is set. With the run's producer token (`producer`), it also
    carries the graphics waiting for approval, as the producer group does (PRD 11.6)."""
    match_dir = _match_dir(match_id)
    agents = crew() if model_configured() else None
    run = start_run(match_dir, EmitterConfig(speed=speed, period=period, from_ms=from_ms, to_ms=to_ms), agents)
    state = run.state
    queue = state.subscribe(maxsize=10_000)
    is_producer = bool(producer) and secrets.compare_digest(producer, run.producer_token)

    def public(m: dict) -> bool:
        """Unapproved graphics go only to the producer, never to the public stream (PRD 11.6)."""
        return is_producer or m["type"] != "overlay.upsert" or m["overlay"]["approval"] in ("auto", "approved")

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
                                                 body.fav, body.lang):
            yield {"event": kind, "data": json.dumps(payload, ensure_ascii=False)}

    return EventSourceResponse(events())


@app.get("/api/matches/{match_id}/suggestions")
def suggestions(match_id: str, period: int | None = None, t_ms: int | None = None) -> list[str]:
    """Three questions about what the viewer has just seen (INTEGRATION.md 6.1): the strongest moments of the last
    minute first, then two that always have an answer."""
    _match_dir(match_id)
    token = T.VIEWER_CLOCK.set((period, t_ms) if period is not None and t_ms is not None else None)
    try:
        seen = T.list_candidates(match_id, period=period)
    finally:
        T.VIEWER_CLOCK.reset(token)
    if seen:
        latest = max(c["t_end_ms"] for c in seen)
        seen = [c for c in seen if c["t_end_ms"] >= latest - 60_000]
    terms = T.glossary("en")
    out: list[str] = []
    for c in sorted(seen, key=lambda c: (-c["strength"], -c["t_start_ms"])):
        if not c.get("creator_id"):
            continue
        q = f"What did No. {number_of(c['creator_id'])}'s {terms.get(c['type'], c['type'].replace('_', ' '))} do?"
        if q not in out:
            out.append(q)
        if len(out) == 2:
            break
    out += [q for q in ("Who has created the most space so far?", "Who is in control right now?") if q not in out]
    return out[:3]


class ApprovalBody(BaseModel):
    overlay_id: str
    decision: str  # approve, hold, skip or retract
    by: str = "producer"
    note: str = ""


class CorrectionBody(BaseModel):
    event_id: str
    field: str
    value: str | float | int | None
    after_ms: int = 3000


class LiveRunBody(BaseModel):
    match_id: str
    period: int | None = None
    from_ms: int = 0
    to_ms: int | None = None
    speed: float = 1.0
    # Feed corrections the emitter sends during the run, to test the correction path (PRD 10.6, 14.5).
    corrections: list[CorrectionBody] = []


@app.post("/api/live-runs", status_code=201)
async def live_run(body: LiveRunBody) -> dict[str, Any]:
    """Start a live run of a match and become its producer (PRD 11.7): the answer carries the producer token that
    approvals need. At most LIVE_MAX_MATCHES runs play at once; past that the answer is 429 with a place in line."""
    match_dir = _match_dir(body.match_id)
    if not 0.25 <= body.speed <= 60:
        raise HTTPException(422, "speed must be between 0.25 and 60")
    playing = [k for k, r in RUNS.items() if not r.done.is_set() and k != body.match_id]
    if len(playing) >= int(os.environ.get("LIVE_MAX_MATCHES", "10")):
        raise HTTPException(429, {"queue_position": len(playing) + 1, "eta_s": 90})
    agents = crew() if model_configured() else None
    fixes = tuple(Correction(c.event_id, c.field, c.value, c.after_ms) for c in body.corrections)
    config = EmitterConfig(speed=body.speed, period=body.period, from_ms=body.from_ms, to_ms=body.to_ms,
                           corrections=fixes)
    current = RUNS.get(body.match_id)
    if current is not None and current.config == config and not current.done.is_set():
        raise HTTPException(409, f"{body.match_id} is already being produced in this window")
    run = start_run(match_dir, config, agents, restart=True)
    query = f"period={body.period}&from_ms={body.from_ms}" if body.period is not None else f"from_ms={body.from_ms}"
    if body.to_ms is not None:
        query += f"&to_ms={body.to_ms}"
    return {"match_id": body.match_id, "producer_token": run.producer_token, "speed": body.speed,
            "stream": f"/api/matches/{body.match_id}/stream?{query}&speed={body.speed:g}",
            "graphics": "on" if agents else "off: no model is configured"}


def _producer(match_id: str, token: str | None):
    """The run a producer token belongs to; producer calls are never public (PRD 11.7)."""
    run = RUNS.get(match_id)
    if run is None:
        raise HTTPException(404, f"No run of {match_id}")
    if not token or not secrets.compare_digest(token, run.producer_token):
        raise HTTPException(401, "Producer calls need this run's producer token, from POST /api/live-runs")
    return run


@app.post("/api/matches/{match_id}/approvals", status_code=202)
def approve(match_id: str, body: ApprovalBody,
            x_producer_token: str | None = Header(default=None)) -> dict[str, Any]:
    state = _producer(match_id, x_producer_token).state
    if body.overlay_id not in state.overlays:
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
    mine = [e for e in state.envelopes if e.payload.get("candidate_id") == cid]
    steps = [{"seq": e.seq, "agent": e.produced_by, "kind": e.kind, "wall_ms": e.wall_ms, "payload": e.payload}
             for e in mine]
    return {"overlay_id": overlay_id, "candidate_id": cid, "steps": steps, "rows": trace_rows(mine)}


@app.get("/api/flags")
def flags() -> dict[str, Any]:
    """The degrade flags, their normal values and the latest changes (PRD 14.7)."""
    FLAG_STORE.expire()
    return FLAG_STORE.snapshot()


@app.post("/api/matches/{match_id}/flags/{flag}/{action}")
def flag_action(match_id: str, flag: str, action: str,
                x_producer_token: str | None = Header(default=None)) -> dict[str, Any]:
    """The producer undoes a flag change at once, or keeps it so it won't revert (PRD 10.6, 11.7)."""
    state = _producer(match_id, x_producer_token).state
    if action not in ("undo", "keep"):
        raise HTTPException(404, "The actions are undo and keep")
    change = FLAG_STORE.undo(flag) if action == "undo" else FLAG_STORE.keep(flag)
    if change is None:
        raise HTTPException(404, f"No change to {flag} to {action}")
    state.append("flag", {"flag": flag, "action": action, **change.as_dict()}, produced_by="producer")
    return FLAG_STORE.snapshot()


AGENT_NAMES = {"scout": "Scout", "explainer": "Explainer", "factchecker": "Fact-checker", "persona": "Persona",
               "producer": "Producer", "corrections": "Corrections", "broadcast": "Publish"}


def trace_rows(envelopes: list) -> list[dict[str, Any]]:
    """The console's trace (INTEGRATION.md 6.3): a row per agent step, in seconds after the moment was found. A step
    starts when the last step by another agent ended, so the Personas, which run side by side, start together."""
    found = next((e.wall_ms for e in envelopes if e.kind == "candidate"), envelopes[0].wall_ms if envelopes else 0)
    rows, last_by_other = [], {}
    previous_end, previous_agent = found, None
    for e in envelopes:
        if e.kind in ("candidate", "outcome"):
            continue
        if e.produced_by != previous_agent:
            last_by_other[e.produced_by] = previous_end
        start = last_by_other.get(e.produced_by, found)
        kind = "ok"
        if e.kind in ("verdict", "recheck") and not e.payload.get("passed", True):
            kind = "rejected"
        elif e.kind == "script" and not e.payload.get("lines"):
            kind = "fallback"
        label = AGENT_NAMES.get(e.produced_by, e.produced_by)
        if e.kind == "script":
            label = f"Persona · {e.payload.get('mode')}"
        elif e.kind == "script_check":
            label = "Fact-checker · scripts"
        rows.append({"agent": label, "start": round((start - found) / 1000, 2), "end": round((e.wall_ms - found) / 1000, 2),
                     "kind": kind})
        previous_end, previous_agent = e.wall_ms, e.produced_by
    return rows


