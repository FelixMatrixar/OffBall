"""Model clients for the agents (PRD 14.13).

Every agent decision and every line an agent writes comes from a model. There is no template or rule fallback:
without a configured model the agents refuse to start, and a call that fails after its retry airs nothing.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from agent_framework_openai import OpenAIChatClient
from dotenv import load_dotenv

Tier = Literal["fast", "reasoning"]
ROOT = Path(__file__).resolve().parents[2]
PLACEHOLDER = "YOUR-RESOURCE"


class ModelNotConfigured(RuntimeError):
    """No model endpoint is set, so no agent can run."""


@dataclass(frozen=True)
class ModelSettings:
    endpoint: str
    api_key: str | None
    api_version: str | None
    fast: str
    reasoning: str

    @classmethod
    def from_env(cls) -> ModelSettings:
        load_dotenv(ROOT / ".env", override=False)
        endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT", "").strip()
        if not endpoint or PLACEHOLDER in endpoint:
            raise ModelNotConfigured(
                "The agents need a model. Copy .env.example to .env and set AZURE_OPENAI_ENDPOINT to your "
                "Foundry resource's endpoint, with its key or an Azure sign-in."
            )
        return cls(
            endpoint=endpoint,
            api_key=os.environ.get("AZURE_OPENAI_API_KEY", "").strip() or None,
            api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "").strip() or None,
            fast=os.environ.get("OFFBALL_MODEL_FAST", "").strip() or "gpt-5-mini",
            reasoning=os.environ.get("OFFBALL_MODEL_REASONING", "").strip() or "gpt-5",
        )

    def deployment(self, tier: Tier) -> str:
        return self.fast if tier == "fast" else self.reasoning


def model_configured() -> bool:
    try:
        ModelSettings.from_env()
    except ModelNotConfigured:
        return False
    return True


def chat_client(tier: Tier, settings: ModelSettings | None = None) -> OpenAIChatClient:
    """A chat client for one tier, on the Foundry resource's Azure OpenAI endpoint."""
    s = settings or ModelSettings.from_env()
    kwargs: dict = {"model": s.deployment(tier), "azure_endpoint": s.endpoint}
    if s.api_version:
        kwargs["api_version"] = s.api_version
    if s.api_key:
        kwargs["api_key"] = s.api_key
    else:
        from azure.identity.aio import DefaultAzureCredential

        kwargs["credential"] = DefaultAzureCredential()
    return OpenAIChatClient(**kwargs)
