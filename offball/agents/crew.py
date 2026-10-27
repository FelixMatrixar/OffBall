"""The broadcast and fan crews' agents (PRD 14.1, 14.13): instructions, tools and model tier for each.

Every agent's output is structured (`offball.agents.schemas`). A call that fails, runs past its time limit or
returns something unusable is asked once more after a short backoff; if it fails again the step gives up and
nothing airs. There is no template or rule to fall back on. Every call's tokens go on the match's meter
(PRD 14.10).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypeVar

from agent_framework import Agent, MCPStreamableHTTPTool, SupportsChatGetResponse, tool
from opentelemetry.trace import Status, StatusCode
from pydantic import BaseModel, ValidationError

from offball.agents.llm import ModelSettings, Tier, chat_client
from offball.mcp import tools as T
from offball.services import telemetry
from offball.services.flags import FLAG_STORE, FlagStore
from offball.services.state import TokenMeter
from offball.services.telemetry import TRACER

log = logging.getLogger("offball.crew")
INSTRUCTIONS = Path(__file__).parent / "instructions"
M = TypeVar("M", bound=BaseModel)

# Which tools each agent may use (PRD 14.1), and its model tier (PRD 14.13).
TOOLSETS: dict[str, list[Callable[..., Any]]] = {
    "scout": [],
    "explainer": [T.list_metrics, T.compute_metric, T.moment_card, T.events_between, T.positions_at, T.player_summary,
                  T.match_facts, T.glossary],
    "factchecker": [T.compute_metric, T.moment_card, T.events_between, T.positions_at, T.get_evidence],
    "persona": [T.glossary],
    "producer": [],
    "tactician": [],
    "pundit": [T.match_facts, T.list_candidates, T.moment_card, T.list_metrics, T.compute_metric, T.events_between,
               T.positions_at, T.player_summary, T.get_evidence, T.glossary],
    # The Engineer reads telemetry the code hands it; on the VM it also gets Azure MCP Server, for Foundry (PRD 14.8).
    "engineer": [],
}
TIERS: dict[str, Tier] = {"scout": "fast", "explainer": "reasoning", "factchecker": "reasoning", "persona": "fast",
                          "producer": "fast", "tactician": "fast", "pundit": "reasoning", "engineer": "fast"}
# Each agent's p95 time budget per call (PRD 14.10): what the Engineer measures latency against.
BUDGET_MS: dict[str, int] = {"scout": 300, "explainer": 1000, "factchecker": 600, "persona": 500, "producer": 200,
                             "tactician": 3000, "pundit": 6000, "engineer": 60000}
# The hard limit on one call, after which it counts as failed. Far above the budgets, which are p95 targets.
TIME_LIMIT_S: dict[str, float] = {"scout": 30, "explainer": 120, "factchecker": 120, "persona": 60, "producer": 60,
                                  "tactician": 60, "pundit": 90, "engineer": 60}
RETRY_BACKOFF_S = 0.5


class AgentFailed(RuntimeError):
    """An agent couldn't produce a usable answer after its retry."""


def parse_faults(spec: str) -> dict[str, tuple[str, int]]:
    """FAULTS, for dev and soak tests only (PRD 14.5, 18.14): `latency:explainer:4000,error:scout` adds 4 s to every
    Explainer call and makes every Scout call fail."""
    out = {}
    for part in filter(None, (p.strip() for p in spec.split(","))):
        kind, _, rest = part.partition(":")
        agent, _, ms = rest.partition(":")
        if kind in ("latency", "error") and agent:
            out[agent] = (kind, int(ms or 0))
    return out


@dataclass
class Telemetry:
    """Every agent call's duration and result, newest last: what the Engineer reads locally (PRD 14.8, 18.8)."""

    calls: deque = field(default_factory=lambda: deque(maxlen=1000))

    def record(self, agent: str, tier: str, ms: float, ok: bool) -> None:
        self.calls.append({"agent": agent, "tier": tier, "ms": round(ms), "ok": ok, "at": time.time()})

    def summary(self, window_s: float = 300) -> dict[str, dict[str, Any]]:
        """Per agent over the last `window_s`: calls, failures, p95 time against its budget, and the tier it ran on."""
        since = time.time() - window_s
        out: dict[str, dict[str, Any]] = {}
        for c in self.calls:
            if c["at"] < since:
                continue
            s = out.setdefault(c["agent"], {"calls": 0, "failures": 0, "ms": [], "tier": c["tier"]})
            s["calls"] += 1
            s["failures"] += 0 if c["ok"] else 1
            s["ms"].append(c["ms"])
            s["tier"] = c["tier"]
        for agent, s in out.items():
            ms = sorted(s.pop("ms"))
            s["p95_ms"] = ms[min(len(ms) - 1, int(0.95 * len(ms)))]
            s["budget_ms"] = BUDGET_MS.get(agent)
        return out


def _tokens(response: Any) -> int:
    usage = getattr(response, "usage_details", None) or {}
    total = usage.get("total_token_count")
    if total is None:
        total = (usage.get("input_token_count") or 0) + (usage.get("output_token_count") or 0)
    return int(total or 0)


def instructions(name: str) -> str:
    return (INSTRUCTIONS / f"{name}.md").read_text(encoding="utf-8")


def _tools_for(name: str) -> list[Any]:
    """In-process tools, or the same tools through the OffBall MCP server when OFFBALL_MCP_URL is set."""
    allowed = [fn.__name__ for fn in TOOLSETS[name]]
    if not allowed:
        return []
    url = os.environ.get("OFFBALL_MCP_URL", "").strip()
    if url:
        return [MCPStreamableHTTPTool(name="offball", url=url, allowed_tools=allowed, load_prompts=False)]
    return [tool(fn) for fn in TOOLSETS[name]]


@dataclass
class Crew:
    """The agents, built once and shared by every moment and question."""

    clients: dict[Tier, SupportsChatGetResponse] = field(default_factory=dict)
    agents: dict[str, Agent] = field(default_factory=dict)
    flags: FlagStore = field(default_factory=lambda: FLAG_STORE)
    telemetry: Telemetry = field(default_factory=Telemetry)
    faults: dict[str, tuple[str, int]] = field(default_factory=lambda: parse_faults(os.environ.get("FAULTS", "")))
    # What every call on a tier asks for: its output cap and reasoning effort (PRD 14.13).
    tier_options: dict[Tier, dict[str, Any]] = field(default_factory=dict)
    _other_tier: dict[tuple[str, Tier], Agent] = field(default_factory=dict)

    @classmethod
    def from_env(cls) -> Crew:
        s = ModelSettings.from_env()
        tiers: tuple[Tier, ...] = ("fast", "reasoning")
        return cls.with_clients({t: chat_client(t, s) for t in tiers},
                                tier_options={t: s.call_options(t) for t in tiers})

    @classmethod
    def with_clients(cls, clients: dict[Tier, SupportsChatGetResponse], **kwargs: Any) -> Crew:
        crew = cls(clients=clients, **kwargs)
        for name, tier in TIERS.items():
            crew.agents[name] = Agent(clients[tier], instructions(name), name=name, tools=_tools_for(name))
        return crew

    def tier_of(self, name: str) -> Tier:
        """The agent's tier, unless a degrade flag (`<agent>.model_tier`) moves it (PRD 14.7)."""
        flag = f"{name}.model_tier"
        return self.flags.get(flag) if flag in self.flags.values else TIERS[name]  # type: ignore[return-value]

    def _agent(self, name: str) -> tuple[Agent, Tier]:
        tier = self.tier_of(name)
        if tier == TIERS[name]:
            return self.agents[name], tier
        if (name, tier) not in self._other_tier:
            self._other_tier[(name, tier)] = Agent(self.clients[tier], instructions(name), name=name,
                                                   tools=_tools_for(name))
        return self._other_tier[(name, tier)], tier

    async def _run(self, name: str, agent: Agent, tier: Tier, text: str, schema: type[M], middleware) -> Any:
        """One call, with any injected fault first, inside the agent's time limit."""
        async with asyncio.timeout(TIME_LIMIT_S.get(name, 60)):
            kind, ms = self.faults.get(name, ("", 0))
            if kind == "latency":
                await asyncio.sleep(ms / 1000)
            elif kind == "error":
                raise RuntimeError(f"injected fault for {name}")
            options = {"response_format": schema, **self.tier_options.get(tier, {})}
            return await agent.run(text, options=options, middleware=middleware)

    async def ask(self, name: str, prompt: str, schema: type[M], middleware: Sequence[Any] | None = None,
                  meter: TokenMeter | None = None) -> M:
        """Run one agent and return its structured answer, asking once more if the first answer is unusable."""
        agent, tier = self._agent(name)
        with TRACER.start_as_current_span(f"agent {name}", attributes={"offball.agent": name, "offball.tier": tier,
                                                                       **telemetry.attributes()}) as span:
            try:
                value = await self._ask(name, agent, tier, prompt, schema, middleware, meter, span)
            except AgentFailed as exc:
                span.set_status(Status(StatusCode.ERROR, str(exc)[:200]))
                raise
            return value

    async def _ask(self, name: str, agent: Agent, tier: Tier, prompt: str, schema: type[M], middleware, meter,
                   span) -> M:
        problem = ""
        for attempt in (1, 2):
            span.set_attribute("offball.attempts", attempt)
            text = prompt if attempt == 1 else (
                f"{prompt}\n\nYour previous answer couldn't be used: {problem}\nAnswer again, following the schema.")
            started = time.monotonic()
            try:
                response = await self._run(name, agent, tier, text, schema, middleware)
                if meter is not None:
                    meter.add(_tokens(response))
                value = response.value
                if value is None:
                    value = schema.model_validate_json(response.text)
                self.telemetry.record(name, tier, (time.monotonic() - started) * 1000, ok=True)
                return value
            except (ValidationError, ValueError) as exc:
                problem = str(exc)[:600]
                log.warning("%s gave an unusable answer (attempt %d): %s", name, attempt, problem)
            except TimeoutError:
                problem = f"no answer within {TIME_LIMIT_S.get(name, 60):g} s"
                log.warning("%s timed out (attempt %d)", name, attempt)
            except Exception as exc:  # a model or network failure
                problem = f"{type(exc).__name__}: {exc}"[:600]
                log.warning("%s failed (attempt %d): %s", name, attempt, problem)
            self.telemetry.record(name, tier, (time.monotonic() - started) * 1000, ok=False)
            if attempt == 1:
                await asyncio.sleep(RETRY_BACKOFF_S)
        raise AgentFailed(f"{name}: {problem}")


def as_json(value: Any) -> str:
    """Compact JSON for prompts."""
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
