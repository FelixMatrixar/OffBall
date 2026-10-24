"""The broadcast and fan crews' agents (PRD 14.1, 14.13): instructions, tools and model tier for each.

Every agent's output is structured (`offball.agents.schemas`). A call that fails or returns something
unusable is asked once more; if it fails again the step gives up and nothing airs. There is no template
or rule to fall back on.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypeVar

from agent_framework import Agent, MCPStreamableHTTPTool, SupportsChatGetResponse, tool
from pydantic import BaseModel, ValidationError

from offball.agents.llm import Tier, chat_client
from offball.mcp import tools as T

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
    "pundit": [T.match_facts, T.list_candidates, T.moment_card, T.list_metrics, T.compute_metric, T.events_between,
               T.positions_at, T.player_summary, T.get_evidence, T.glossary],
}
TIERS: dict[str, Tier] = {"scout": "fast", "explainer": "reasoning", "factchecker": "reasoning", "persona": "fast",
                          "producer": "fast", "pundit": "reasoning"}


class AgentFailed(RuntimeError):
    """An agent couldn't produce a usable answer after its retry."""


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

    @classmethod
    def from_env(cls) -> Crew:
        return cls.with_clients({"fast": chat_client("fast"), "reasoning": chat_client("reasoning")})

    @classmethod
    def with_clients(cls, clients: dict[Tier, SupportsChatGetResponse]) -> Crew:
        crew = cls(clients=clients)
        for name, tier in TIERS.items():
            crew.agents[name] = Agent(clients[tier], instructions(name), name=name, tools=_tools_for(name))
        return crew

    async def ask(self, name: str, prompt: str, schema: type[M], middleware: Sequence[Any] | None = None) -> M:
        """Run one agent and return its structured answer, asking once more if the first answer is unusable."""
        agent = self.agents[name]
        problem = ""
        for attempt in (1, 2):
            text = prompt if attempt == 1 else (
                f"{prompt}\n\nYour previous answer couldn't be used: {problem}\nAnswer again, following the schema.")
            try:
                response = await agent.run(text, options={"response_format": schema}, middleware=middleware)
                value = response.value
                if value is None:
                    value = schema.model_validate_json(response.text)
                return value
            except (ValidationError, ValueError) as exc:
                problem = str(exc)[:600]
                log.warning("%s gave an unusable answer (attempt %d): %s", name, attempt, problem)
            except Exception as exc:  # a model or network failure
                problem = f"{type(exc).__name__}: {exc}"[:600]
                log.warning("%s failed (attempt %d): %s", name, attempt, problem)
        raise AgentFailed(f"{name}: {problem}")


def as_json(value: Any) -> str:
    """Compact JSON for prompts."""
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
