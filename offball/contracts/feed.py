"""The live feed (PRD 12.8) and the partner overlay protocol (PRD 15.7)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from offball.contracts.base import Contract, Versioned
from offball.contracts.overlay import Overlay

MatchStatus = Literal["pre_match", "in_play", "half_time", "full_time", "interrupted"]


class StatusPayload(Contract):
    status: MatchStatus
    period: int
    t_ms: int
    score: dict[str, int]


class FeedMessage(Versioned):
    """A message on the match feed, from the emitter to ingest."""

    seq: int = Field(ge=0, description="Sequence number per match, for dedup and reorder")
    match_id: str
    kind: Literal["event", "frame", "correction", "status"]
    sent_at: str = Field(description="ISO 8601 UTC timestamp")
    payload: dict[str, Any]
    corrects_event_id: str | None = None


class OverlayUpsert(Contract):
    type: Literal["overlay.upsert"] = "overlay.upsert"
    match_id: str
    overlay: Overlay
    sent_at: str


class OverlayRetract(Contract):
    type: Literal["overlay.retract"] = "overlay.retract"
    match_id: str
    overlay_id: str
    reason: Literal["correction", "producer", "superseded", "expired"]
    corrects_event_id: str | None = None
    replacement_id: str | None = None
    sent_at: str


class ClockSync(Contract):
    type: Literal["clock.sync"] = "clock.sync"
    match_id: str
    period: int
    t_ms: int
    speed: float = Field(default=1.0, description="Playback speed, 0.25x to 60x")
    server_time: str


class MatchStatusMessage(Contract):
    type: Literal["match.status"] = "match.status"
    match_id: str
    status: MatchStatus
    period: int
    t_ms: int
    score: dict[str, int]
    sent_at: str


PartnerMessage = OverlayUpsert | OverlayRetract | ClockSync | MatchStatusMessage
