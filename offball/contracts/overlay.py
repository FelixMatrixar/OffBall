"""overlays.jsonl: timed, anchored, revisable graphics and lines (PRD 12.8, 15.2)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from offball.contracts.base import XY, Contract, Versioned

OverlayKind = Literal[
    "control_field",
    "gap_ring",
    "run_arrow",
    "pass_line",
    "ghost",
    "offside_line",
    "shape_lines",
    "player_tag",
    "badge",
    "caption",
    "stat_card",
    "chart",
    "correction",
]
Mode = Literal["casual", "learn", "analyst", "player", "audio", "broadcaster"]
Approval = Literal["auto", "pending", "approved", "held", "skipped", "rejected"]
MODES: tuple[Mode, ...] = ("casual", "learn", "analyst", "player", "audio", "broadcaster")
LAYER_OF: dict[str, str] = {
    "control_field": "field",
    "gap_ring": "pitch",
    "run_arrow": "pitch",
    "pass_line": "pitch",
    "ghost": "pitch",
    "offside_line": "shape",
    "shape_lines": "shape",
    "player_tag": "labels",
    "badge": "labels",
    "caption": "dom",
    "stat_card": "dom",
    "chart": "dom",
    "correction": "dom",
}


class Anchors(Contract):
    """Where a graphic sits. Renderers resolve player anchors against the frame clock."""

    player_id: str | None = None
    player_ids: list[str] | None = None
    from_xy: XY | None = None
    to_xy: XY | None = None
    centre_xy: XY | None = None
    radius_m: float | None = None
    polygon: list[XY] | None = None
    ghost_track_id: str | None = None


class Speech(Contract):
    ssml_ref: str
    voice: str = "narrator-1"
    ssml: str | None = Field(default=None, description="Speech markup; renderers synthesise it or fetch ssml_ref")
    pan: float | None = Field(default=None, ge=-1, le=1, description="Stereo pan for audio cues: -1 left, 1 right")


class Overlay(Versioned):
    overlay_id: str
    rev: int = Field(default=1, ge=1)
    match_id: str
    period: int
    t_start_ms: int
    t_end_ms: int
    kind: OverlayKind
    layer: str
    priority: int = Field(default=2, ge=0, le=5, description="0 is most important")
    mode: Mode
    anchors: Anchors = Field(default_factory=Anchors)
    text: dict[str, str] = Field(default_factory=dict, description="Text per locale")
    speech: dict[str, Speech] = Field(default_factory=dict)
    a11y_text: dict[str, str] = Field(default_factory=dict)
    chart: dict[str, Any] | None = Field(default=None, description="A Vega-Lite spec, themed by the client (VIS-7)")
    data: dict[str, Any] | None = Field(default=None, description="Numbers for stat cards, with units")
    evidence_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(default=1.0, ge=0, le=1)
    approval: Approval = "auto"
    counterfactual_id: str | None = None
    detected_moment_id: str | None = None
    ai_generated: bool = True
    labels: list[str] = Field(default_factory=lambda: ["synthetic-data", "ai-generated"])
