"""Typed hand-offs between agents (PRD 14.3).

Agents never pass free text to each other. Each hand-off is one of these messages, appended to the
match-state store (event-sourced, so every hop is replayable) and announced on a queue.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from offball.contracts.base import XY, Contract, Versioned
from offball.contracts.overlay import Mode

DetectableType = Literal[
    "decoy_run",
    "overlap",
    "underlap",
    "third_man_run",
    "blind_side_run",
    "timed_run_in_behind",
    "false_9_drop",
    "pinning",
    "rotation",
    "set_piece_screen",
    "switch_of_play",
    "press_broken",
    "fatigue_gap",
    "space_lost",
    "rest_defence_exposed",
    "cover_shadow",
]


class Signal(Contract):
    name: str = Field(description="Metric name, e.g. defender_displacement_m")
    value: float
    threshold: float
    unit: str
    evidence_ids: list[str] = Field(default_factory=list)

    @property
    def ratio(self) -> float:
        if self.threshold == 0:
            return 1.0
        return self.value / self.threshold


class Candidate(Versioned):
    """A candidate moment from the interpret service: its type, participants and signal strengths."""

    kind: Literal["candidate"] = "candidate"
    candidate_id: str
    match_id: str
    period: int
    t_start_ms: int
    t_end_ms: int
    type: DetectableType
    team_id: str
    creator_id: str
    dragged_ids: list[str] = Field(default_factory=list)
    receiver_id: str | None = None
    gap_zone: list[XY] = Field(default_factory=list)
    run_from: XY | None = None
    run_to: XY | None = None
    signals: list[Signal] = Field(default_factory=list)
    strength: float = Field(description="Mean signal ratio, capped; 1.0 means every threshold is met")
    status: Literal["speculative", "confirmed", "discarded"] = "confirmed"
    space_created_m2: float | None = None
    epv_gain: float | None = None
    evidence_ids: list[str] = Field(default_factory=list)


class MomentPick(Versioned):
    """The Scout's airtime decision for one candidate."""

    kind: Literal["moment"] = "moment"
    candidate_id: str
    airtime: bool
    rank: int
    priority: int = Field(ge=0, le=5)
    reason: str
    want_counterfactual: bool = True
    decided_by: Literal["agent", "rule"] = "agent"


class Interval(Contract):
    median: float
    lo: float = Field(description="5th percentile")
    hi: float = Field(description="95th percentile")


class CounterfactualResult(Versioned):
    """The Tactician's proof of cause: the moment re-run with and without the run."""

    kind: Literal["counterfactual"] = "counterfactual"
    counterfactual_id: str
    candidate_id: str
    removed_player_id: str
    removed_action: str
    runs: int
    space_created_m2: Interval
    epv_gain: Interval
    gap_open_rate_with: float
    gap_open_rate_without: float
    ghost_tracks: dict[str, list[tuple[int, float, float]]] = Field(
        default_factory=dict, description="player_id -> [t_ms, x, y] for the median no-run re-run"
    )
    elapsed_ms: int = 0
    decided_by: Literal["agent", "rule"] = "agent"


class Claim(Contract):
    """One checkable statement. Numbers come from tool calls, so the Fact-checker can recompute them."""

    claim_id: str
    kind: Literal["number", "statement"]
    text: str = Field(description="English text of the claim")
    metric: str | None = Field(default=None, description="compute_metric name for number claims")
    params: dict[str, Any] = Field(default_factory=dict)
    value: float | None = None
    unit: str | None = None
    subject_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)


class Draft(Versioned):
    """The Explainer's structured explanation of a moment."""

    kind: Literal["draft"] = "draft"
    draft_id: str
    candidate_id: str
    attempt: int = 1
    headline: str
    claims: list[Claim]
    source: Literal["agent", "template"] = "agent"


class ClaimVerdict(Contract):
    claim_id: str
    ok: bool
    recomputed: float | None = None
    reason: str = ""


class Verdict(Versioned):
    """The Fact-checker's verdict on every claim of a draft."""

    kind: Literal["verdict"] = "verdict"
    draft_id: str
    candidate_id: str
    passed: bool
    verdicts: list[ClaimVerdict]
    checked_by: Literal["agent", "rule"] = "rule"


class Variant(Versioned):
    """The Persona's rendering of verified claims for one mode and language."""

    kind: Literal["variant"] = "variant"
    candidate_id: str
    mode: Mode
    locale: str
    caption: str
    speech_ssml: str | None = None
    a11y_text: str
    stat: dict[str, Any] | None = None
    glossary_terms: list[str] = Field(default_factory=list)
    translated_by: Literal["agent", "glossary", "fallback_en"] = "agent"


class ApprovalDecision(Versioned):
    kind: Literal["approval"] = "approval"
    overlay_id: str
    decision: Literal["approve", "hold", "skip", "retract"]
    by: Literal["producer", "auto"]
    note: str = ""


class FlagChange(Contract):
    flag: str
    old: Any
    new: Any
    revert_after_s: int = 600


class Incident(Versioned):
    """The Engineer's incident note: what it saw, what it changed, and the evidence."""

    kind: Literal["incident"] = "incident"
    incident_id: str
    severity: Literal["info", "warning", "critical"]
    summary: str
    evidence: list[str] = Field(default_factory=list, description="Queries run and metric readings cited")
    changes: list[FlagChange] = Field(default_factory=list)
    decided_by: Literal["agent", "rule"] = "agent"


class Envelope(Versioned):
    """How every hand-off is stored and announced."""

    seq: int
    match_id: str
    kind: str
    produced_by: str = Field(description="Agent or service name")
    wall_ms: int
    payload: dict[str, Any]
    trace_id: str | None = None
