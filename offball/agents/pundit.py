"""Ask OffBall (PRD 10.4; INTEGRATION.md 6.1): a fan's question, answered by the Pundit and fact-checked.

The Pundit answers with the match tools; each tool call is reported as it happens, so the panel can show the
work. The Fact-checker then checks every claim independently, and a claim it can't confirm goes out marked
unverified. Answers are in English, Spanish or French, as the viewer asks; any other language gets English.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from agent_framework import FunctionInvocationContext, function_middleware
from opentelemetry import trace

from offball.agents.crew import AgentFailed, Crew, as_json
from offball.agents.schemas import AnswerOut, VerdictOut
from offball.core import clock_label
from offball.mcp import tools as T
from offball.services.telemetry import TRACER

LANGUAGE_NAMES = {"en": "English", "es": "Spanish", "fr": "French"}
SHOW_MAX_MS = 20_000  # the longest play an answer shows on the pitch


async def answer(crew: Crew, match_id: str, question: str, period: int | None = None, t_ms: int | None = None,
                 mode: str = "casual", fav: str | None = None, lang: str = "en",
                 moment_id: str | None = None) -> AsyncIterator[tuple[str, dict[str, Any]]]:
    """Yield ("tool", {"name"}) for each tool call, then ("answer", Answer) in the frontend's shape."""
    events: asyncio.Queue[tuple[str, dict[str, Any]] | None] = asyncio.Queue()
    used: list[str] = []

    @function_middleware
    async def report(context: FunctionInvocationContext, call_next) -> None:
        name = context.function.name
        used.append(name)
        await events.put(("tool", {"name": name}))
        await call_next()

    async def work() -> None:
        token = T.VIEWER_CLOCK.set((period, t_ms) if period is not None and t_ms is not None else None)
        # The span names the match, mode and language, never the question (PRD 18.6).
        span = TRACER.start_span("ask", attributes={"offball.match_id": match_id, "offball.mode": mode,
                                                    "offball.lang": lang})
        try:
            with trace.use_span(span, end_on_exit=True):
                await events.put(("answer", await _answer(crew, match_id, question, period, t_ms, mode, fav, lang,
                                                           used, [report], moment_id)))
        except AgentFailed as exc:
            await events.put(("error", {"detail": f"The Pundit couldn't answer: {exc}"}))
        finally:
            T.VIEWER_CLOCK.reset(token)
            await events.put(None)

    task = asyncio.create_task(work())
    while (item := await events.get()) is not None:
        yield item
    await task


def _on_screen(match_id: str, moment_id: str | None) -> str:
    """The moment the viewer has open or is watching, in a sentence for the prompt."""
    if not moment_id:
        return ""
    try:
        c = T.candidate(match_id, moment_id)
    except ValueError:
        return ""
    dragged = f", pulling {', '.join(c.dragged_ids)}" if c.dragged_ids else ""
    return (f" On screen is moment {c.candidate_id}: a {c.type.replace('_', ' ')} by {c.creator_id}{dragged}, from "
            f"{clock_label(c.period, c.t_start_ms)} to {clock_label(c.period, c.t_end_ms)} (period {c.period}, t_ms "
            f"{c.t_start_ms} to {c.t_end_ms}). 'This', 'that run' or 'here' mean this moment.")


def _show(match_id: str, out: AnswerOut, clock: tuple[int, int] | None) -> dict[str, Any] | None:
    """The play the Pundit chose to show its answer, kept to what the viewer has seen and to 20 s."""
    if out.show_period is None or out.show_from_ms is None:
        return None
    md = T.REGISTRY.data(match_id)
    if out.show_period not in md.periods:
        return None
    period, end = out.show_period, int(md.periods[out.show_period].t_ms[-1])
    start = max(0, min(out.show_from_ms, end))
    stop = out.show_to_ms if out.show_to_ms is not None and out.show_to_ms > start else start + 8000
    stop = min(stop, start + SHOW_MAX_MS, end)
    if clock is not None:
        if (period, start) > clock:
            return None  # it hasn't happened yet for this viewer
        if period == clock[0]:
            stop = min(stop, clock[1])
    moment = out.show_moment_id
    if moment and not any(c.candidate_id == moment for c in T.REGISTRY.candidates(match_id)):
        moment = None
    players = [p for p in dict.fromkeys(out.show_player_ids) if p in md.players][:4]
    return {"period": period, "from_ms": start, "to_ms": max(stop, start + 1000), "player_ids": players,
            "moment_id": moment}


async def _answer(crew: Crew, match_id: str, question: str, period: int | None, t_ms: int | None, mode: str,
                  fav: str | None, lang: str, used: list[str], middleware: list,
                  moment_id: str | None = None) -> dict[str, Any]:
    if period is not None and t_ms is not None:
        where = f"{clock_label(period, t_ms)} on the match clock (period {period}, t_ms {t_ms})"
    else:
        where = "the end of the match"
    language = LANGUAGE_NAMES.get(lang, "English")
    prompt = (f"Match {match_id}. The viewer is watching in {mode} mode, at {where}."
              + _on_screen(match_id, moment_id)
              + (f" Their favourite player is {fav}." if fav else "")
              + f" Answer in {language}."
              + f"\n\nTheir question: {question}")
    out = await crew.ask("pundit", prompt, AnswerOut, middleware=middleware)
    claims = [{"text": c.text, "verified": c.verified, "evidence": c.evidence} for c in out.claims]
    if claims and out.state in ("ok", "partial"):
        listed = [{"claim_id": f"a{k + 1}", **c} for k, c in enumerate(claims)]
        verdict = await crew.ask(
            "factchecker",
            f"Check these claims from an answer about match {match_id}, as of {where}.\n\nClaims:\n{as_json(listed)}",
            VerdictOut, middleware=middleware)
        ok = {c.claim_id: c.ok for c in verdict.checks}
        for k, c in enumerate(claims):
            c["verified"] = bool(c["verified"] and ok.get(f"a{k + 1}", False))
    state = out.state
    if state == "ok" and not all(c["verified"] for c in claims):
        state = "partial"
    result: dict[str, Any] = {"question": question, "state": state, "claims": claims, "tools": list(dict.fromkeys(used))}
    if state in ("ok", "partial") and (show := _show(match_id, out, T.VIEWER_CLOCK.get())):
        result["show"] = show
    if out.alternative_label and out.alternative_question:
        result["alternative"] = {"label": out.alternative_label, "question": out.alternative_question}
    return result
