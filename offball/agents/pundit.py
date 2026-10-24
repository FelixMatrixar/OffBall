"""Ask OffBall (PRD 10.4; INTEGRATION.md 6.1): a fan's question, answered by the Pundit and fact-checked.

The Pundit answers with the match tools; each tool call is reported as it happens, so the panel can show the
work. The Fact-checker then checks every claim independently, and a claim it can't confirm goes out marked
unverified. Answers are in English.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from agent_framework import FunctionInvocationContext, function_middleware

from offball.agents.crew import AgentFailed, Crew, as_json
from offball.agents.schemas import AnswerOut, VerdictOut
from offball.mcp import tools as T


async def answer(crew: Crew, match_id: str, question: str, period: int | None = None, t_ms: int | None = None,
                 mode: str = "casual", fav: str | None = None) -> AsyncIterator[tuple[str, dict[str, Any]]]:
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
        try:
            await events.put(("answer", await _answer(crew, match_id, question, period, t_ms, mode, fav, used,
                                                       [report])))
        except AgentFailed as exc:
            await events.put(("error", {"detail": f"The Pundit couldn't answer: {exc}"}))
        finally:
            T.VIEWER_CLOCK.reset(token)
            await events.put(None)

    task = asyncio.create_task(work())
    while (item := await events.get()) is not None:
        yield item
    await task


async def _answer(crew: Crew, match_id: str, question: str, period: int | None, t_ms: int | None, mode: str,
                  fav: str | None, used: list[str], middleware: list) -> dict[str, Any]:
    where = f"period {period}, t_ms {t_ms}" if period is not None and t_ms is not None else "the end of the match"
    prompt = (f"Match {match_id}. The viewer is watching in {mode} mode, at {where}."
              + (f" Their favourite player is {fav}." if fav else "")
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
    if out.alternative_label and out.alternative_question:
        result["alternative"] = {"label": out.alternative_label, "question": out.alternative_question}
    return result
