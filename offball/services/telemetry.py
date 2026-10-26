"""Traces of every agent hop (PRD 14.3, 18.8; AI-6).

A moment's run is one span; each agent call inside it is a child span carrying the agent, its tier, the match and
the candidate; each hand-off appended to the match state and each graphic sent is an event on the span it happened
in, with the envelope's `seq` or the overlay's ID and revision. Prompts, answers and a fan's question text are never
written to a span (PRD 18.6). Traces go over OTLP to the Aspire Dashboard on the VM (PRD 18.8), or any other
OpenTelemetry collector, when OTEL_EXPORTER_OTLP_ENDPOINT is set; to the console with OFFBALL_TRACE=console; and
nowhere otherwise.
"""

from __future__ import annotations

import logging
import os
from contextvars import ContextVar

from opentelemetry import trace

TRACER = trace.get_tracer("offball")
# The match and moment the current work belongs to, added to every agent span.
MOMENT: ContextVar[dict[str, str] | None] = ContextVar("offball_moment", default=None)

log = logging.getLogger("offball.telemetry")


def attributes() -> dict[str, str]:
    return {f"offball.{k}": v for k, v in (MOMENT.get() or {}).items()}


def event(name: str, **attrs: str | int) -> None:
    """An event on whatever span is current: a hand-off or a graphic sent."""
    span = trace.get_current_span()
    if span.is_recording():
        span.add_event(name, {f"offball.{k}": v for k, v in attrs.items()})


def setup_tracing() -> str:
    """Send traces where the environment says. Returns where they go."""
    from agent_framework.observability import configure_otel_providers

    if os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip():
        # The framework reads the endpoint, and any OTEL_EXPORTER_OTLP_* settings, from the environment.
        configure_otel_providers(service_name="offball", enable_sensitive_data=False)
        return "otlp"
    if os.environ.get("OFFBALL_TRACE", "").strip().lower() == "console":
        configure_otel_providers(service_name="offball", enable_console_exporters=True, enable_sensitive_data=False)
        return "console"
    return "off"
