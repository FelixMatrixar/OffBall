"""The model settings (PRD 14.13): GPT-6 Luna on both tiers, with each tier's reasoning effort and output cap."""

from __future__ import annotations

from typing import Any

import pytest

from offball.agents import llm
from offball.agents.crew import Crew
from offball.agents.schemas import ScoutDecision

SETTINGS = ("OFFBALL_MODEL_FAST", "OFFBALL_MODEL_REASONING", "OFFBALL_EFFORT_FAST", "OFFBALL_EFFORT_REASONING",
            "OFFBALL_MAX_TOKENS_FAST", "OFFBALL_MAX_TOKENS_REASONING", "AZURE_OPENAI_ENDPOINT")


@pytest.fixture
def openrouter(monkeypatch):
    monkeypatch.setattr(llm, "load_dotenv", lambda *a, **k: None)
    for name in SETTINGS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    return monkeypatch


def test_both_tiers_default_to_luna_with_their_effort_and_cap(openrouter) -> None:
    s = llm.ModelSettings.from_env()
    assert (s.deployment("fast"), s.deployment("reasoning")) == ("openai/gpt-6-luna", "openai/gpt-6-luna")
    assert s.call_options("fast") == {"max_tokens": 4000, "reasoning_effort": "low"}
    assert s.call_options("reasoning") == {"max_tokens": 16000, "reasoning_effort": "high"}


def test_the_environment_overrides_the_model_effort_and_cap(openrouter) -> None:
    openrouter.setenv("OFFBALL_MODEL_REASONING", "openai/gpt-6-sol")
    openrouter.setenv("OFFBALL_EFFORT_FAST", "minimal")
    openrouter.setenv("OFFBALL_MAX_TOKENS_REASONING", "24000")
    s = llm.ModelSettings.from_env()
    assert s.deployment("reasoning") == "openai/gpt-6-sol"
    assert s.call_options("fast") == {"max_tokens": 4000, "reasoning_effort": "minimal"}
    assert s.call_options("reasoning") == {"max_tokens": 24000, "reasoning_effort": "high"}


def test_a_cap_must_be_a_number(openrouter) -> None:
    openrouter.setenv("OFFBALL_MAX_TOKENS_FAST", "lots")
    with pytest.raises(ValueError, match="OFFBALL_MAX_TOKENS_FAST"):
        llm.ModelSettings.from_env()


def test_a_foundry_deployment_keeps_its_own_effort_but_is_capped(monkeypatch) -> None:
    monkeypatch.setattr(llm, "load_dotenv", lambda *a, **k: None)
    for name in SETTINGS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example.openai.azure.com/")
    monkeypatch.setenv("OFFBALL_EFFORT_REASONING", "high")
    s = llm.ModelSettings.from_env()
    assert s.call_options("fast") == {"max_tokens": 4000}
    assert s.call_options("reasoning") == {"max_tokens": 16000}


class _Recorder:
    """Stands in for an agent and keeps the options each call was given."""

    def __init__(self) -> None:
        self.options: list[dict[str, Any]] = []

    async def run(self, text: str, options: dict[str, Any], middleware: Any) -> Any:
        self.options.append(options)
        return None


async def test_the_cap_and_effort_reach_openrouters_request() -> None:
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
    crew = Crew(tier_options={"reasoning": {"max_tokens": 16000, "reasoning_effort": "high"}})
    await crew._run("explainer", Agent(client, "Answer.", name="explainer"), "reasoning", "hi", ScoutDecision, None)
    assert sent[0]["model"] == "openai/gpt-6-luna"
    assert (sent[0]["max_completion_tokens"], sent[0]["reasoning_effort"]) == (16000, "high")


async def test_each_call_asks_for_its_own_tiers_options() -> None:
    crew = Crew(tier_options={"fast": {"max_tokens": 4000}, "reasoning": {"max_tokens": 16000,
                                                                         "reasoning_effort": "high"}})
    agent = _Recorder()
    await crew._run("explainer", agent, "reasoning", "text", ScoutDecision, None)  # type: ignore[arg-type]
    await crew._run("scout", agent, "fast", "text", ScoutDecision, None)  # type: ignore[arg-type]
    assert agent.options[0] == {"response_format": ScoutDecision, "max_tokens": 16000, "reasoning_effort": "high"}
    assert agent.options[1] == {"response_format": ScoutDecision, "max_tokens": 4000}
