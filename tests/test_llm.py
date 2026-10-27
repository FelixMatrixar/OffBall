"""The model settings (PRD 14.13): GPT-6 Luna on both tiers, with the reasoning effort each tier asks for."""

from __future__ import annotations

from typing import Any

import pytest

from offball.agents import llm
from offball.agents.crew import Crew
from offball.agents.schemas import ScoutDecision


@pytest.fixture
def openrouter(monkeypatch):
    monkeypatch.setattr(llm, "load_dotenv", lambda *a, **k: None)
    for name in ("OFFBALL_MODEL_FAST", "OFFBALL_MODEL_REASONING", "OFFBALL_EFFORT_FAST", "OFFBALL_EFFORT_REASONING",
                 "AZURE_OPENAI_ENDPOINT"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    return monkeypatch


def test_both_tiers_default_to_luna_with_low_and_high_effort(openrouter) -> None:
    s = llm.ModelSettings.from_env()
    assert (s.deployment("fast"), s.deployment("reasoning")) == ("openai/gpt-6-luna", "openai/gpt-6-luna")
    assert (s.effort("fast"), s.effort("reasoning")) == ("low", "high")


def test_the_environment_overrides_the_model_and_effort(openrouter) -> None:
    openrouter.setenv("OFFBALL_MODEL_REASONING", "openai/gpt-6-sol")
    openrouter.setenv("OFFBALL_EFFORT_FAST", "minimal")
    s = llm.ModelSettings.from_env()
    assert s.deployment("reasoning") == "openai/gpt-6-sol"
    assert (s.effort("fast"), s.effort("reasoning")) == ("minimal", "high")


def test_a_foundry_deployment_keeps_its_own_effort(monkeypatch) -> None:
    monkeypatch.setattr(llm, "load_dotenv", lambda *a, **k: None)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example.openai.azure.com/")
    monkeypatch.setenv("OFFBALL_EFFORT_REASONING", "high")
    s = llm.ModelSettings.from_env()
    assert s.effort("fast") is None and s.effort("reasoning") is None


class _Recorder:
    """Stands in for an agent and keeps the options each call was given."""

    def __init__(self) -> None:
        self.options: list[dict[str, Any]] = []

    async def run(self, text: str, options: dict[str, Any], middleware: Any) -> Any:
        self.options.append(options)
        return None


async def test_the_effort_reaches_openrouters_request() -> None:
    import json

    import httpx
    from agent_framework import Agent
    from agent_framework_openai import OpenAIChatCompletionClient
    from openai import AsyncOpenAI

    sent: list[dict[str, Any]] = []
    answer = ScoutDecision(airtime=True, priority=0, want_counterfactual=False, reason="r").model_dump_json()

    def reply(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={
            "id": "c", "object": "chat.completion", "created": 0, "model": "openai/gpt-6-luna",
            "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": answer}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}})

    http = httpx.AsyncClient(transport=httpx.MockTransport(reply))
    client = OpenAIChatCompletionClient(model="openai/gpt-6-luna", async_client=AsyncOpenAI(
        base_url="https://openrouter.test/api/v1", api_key="k", http_client=http))
    crew = Crew(efforts={"reasoning": "high"})
    await crew._run("explainer", Agent(client, "Answer.", name="explainer"), "reasoning", "hi", ScoutDecision, None)
    assert sent[0]["model"] == "openai/gpt-6-luna" and sent[0]["reasoning_effort"] == "high"


async def test_each_call_asks_for_its_tiers_effort() -> None:
    crew = Crew(efforts={"reasoning": "high"})
    agent = _Recorder()
    await crew._run("explainer", agent, "reasoning", "text", ScoutDecision, None)  # type: ignore[arg-type]
    await crew._run("scout", agent, "fast", "text", ScoutDecision, None)  # type: ignore[arg-type]
    assert agent.options[0] == {"response_format": ScoutDecision, "reasoning_effort": "high"}
    assert agent.options[1] == {"response_format": ScoutDecision}
