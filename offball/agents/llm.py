"""Model clients for the agents (PRD 14.13).

Every agent decision and every line an agent writes comes from a model. There is no template or rule fallback:
without a configured model the agents refuse to start, and a call that fails after its retry airs nothing.

The models come from OpenRouter (ADR 0004). Until the agents run as prompt agents in Foundry Agent Service, through
the project's OpenRouter connection, the crew calls OpenRouter directly (ADR 0002). A Foundry resource's own
endpoint still works in OpenRouter's place, for a model deployed there.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from agent_framework_openai import OpenAIChatClient, OpenAIChatCompletionClient
from dotenv import load_dotenv

Tier = Literal["fast", "reasoning"]
Provider = Literal["openrouter", "foundry"]
ROOT = Path(__file__).resolve().parents[2]
PLACEHOLDER = "YOUR-RESOURCE"
OPENROUTER_URL = "https://openrouter.ai/api/v1"
# Each provider's default model per tier; OFFBALL_MODEL_FAST and OFFBALL_MODEL_REASONING override them. On
# OpenRouter both tiers are GPT-6 Luna, and the tiers differ in how hard the model thinks.
DEFAULT_MODELS: dict[Provider, tuple[str, str]] = {
    "openrouter": ("openai/gpt-6-luna", "openai/gpt-6-luna"),
    "foundry": ("gpt-5-mini", "gpt-5"),
}
# Reasoning effort per tier on OpenRouter: low keeps the fast tier inside budgets of a few hundred milliseconds, and
# high gives the Explainer, Fact-checker and Pundit room to think (PRD 14.10, 14.13). OFFBALL_EFFORT_FAST and
# OFFBALL_EFFORT_REASONING override them. A Foundry deployment keeps its own default.
DEFAULT_EFFORTS: tuple[str, str] = ("low", "high")


class ModelNotConfigured(RuntimeError):
    """No model is set, so no agent can run."""


def _env(name: str) -> str:
    return os.environ.get(name, "").strip()


@dataclass(frozen=True)
class ModelSettings:
    provider: Provider
    endpoint: str
    api_key: str | None
    api_version: str | None
    fast: str
    reasoning: str
    fast_effort: str | None = None
    reasoning_effort: str | None = None

    @classmethod
    def from_env(cls) -> ModelSettings:
        load_dotenv(ROOT / ".env", override=False)
        if key := _env("OPENROUTER_API_KEY"):
            provider: Provider = "openrouter"
            endpoint, api_key, api_version = _env("OPENROUTER_BASE_URL") or OPENROUTER_URL, key, None
        elif (endpoint := _env("AZURE_OPENAI_ENDPOINT")) and PLACEHOLDER not in endpoint:
            provider = "foundry"
            api_key, api_version = _env("AZURE_OPENAI_API_KEY") or None, _env("AZURE_OPENAI_API_VERSION") or None
        else:
            raise ModelNotConfigured(
                "The agents need a model. Copy .env.example to .env and set OPENROUTER_API_KEY to your OpenRouter "
                "key, or AZURE_OPENAI_ENDPOINT to a Foundry resource's endpoint."
            )
        fast, reasoning = DEFAULT_MODELS[provider]
        efforts = (None, None)
        if provider == "openrouter":
            efforts = (_env("OFFBALL_EFFORT_FAST") or DEFAULT_EFFORTS[0],
                       _env("OFFBALL_EFFORT_REASONING") or DEFAULT_EFFORTS[1])
        return cls(
            provider=provider,
            endpoint=endpoint,
            api_key=api_key,
            api_version=api_version,
            fast=_env("OFFBALL_MODEL_FAST") or fast,
            reasoning=_env("OFFBALL_MODEL_REASONING") or reasoning,
            fast_effort=efforts[0],
            reasoning_effort=efforts[1],
        )

    def deployment(self, tier: Tier) -> str:
        return self.fast if tier == "fast" else self.reasoning

    def effort(self, tier: Tier) -> str | None:
        """The reasoning effort to ask for on this tier, or None for the model's own default."""
        return self.fast_effort if tier == "fast" else self.reasoning_effort


def model_configured() -> bool:
    try:
        ModelSettings.from_env()
    except ModelNotConfigured:
        return False
    return True


def chat_client(tier: Tier, settings: ModelSettings | None = None) -> OpenAIChatClient | OpenAIChatCompletionClient:
    """A chat client for one tier: OpenRouter's, or the Foundry resource's Azure OpenAI endpoint."""
    s = settings or ModelSettings.from_env()
    if s.provider == "openrouter":
        # Chat Completions, which every model on OpenRouter serves; the Responses API covers only some of them.
        return OpenAIChatCompletionClient(model=s.deployment(tier), base_url=s.endpoint, api_key=s.api_key)
    kwargs: dict = {"model": s.deployment(tier), "azure_endpoint": s.endpoint}
    if s.api_version:
        kwargs["api_version"] = s.api_version
    if s.api_key:
        kwargs["api_key"] = s.api_key
    else:
        from azure.identity.aio import DefaultAzureCredential

        kwargs["credential"] = DefaultAzureCredential()
    return OpenAIChatClient(**kwargs)
