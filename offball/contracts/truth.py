"""Held-out truth: intents, answer key and counterfactual truth (PRD 12.8, 12.9).

These files are written to a separate store that only the evaluator reads. Nothing in the live
pipeline (ingest, interpret, agents, MCP) may import or open them.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from offball.contracts.base import XY, Contract, Versioned

MomentType = Literal[
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
    "null_run",
    "null_overlap",
]
MOMENT_TYPES: tuple[str, ...] = MomentType.__args__  # type: ignore[attr-defined]
NULL_TYPES = frozenset({"null_run", "null_overlap"})


class Intent(Contract):
    """intents.jsonl: a player decision, logged when a player's intent changes."""

    player_id: str
    period: int
    t_ms: int
    intent: str
    utility: float
    target_xy: XY | None = None
    checkpoint_id: str | None = None
    moment_id: str | None = None


class CounterfactualTruth(Contract):
    space_created_m2: float = Field(description="Gap-zone area the run created, against the no-run re-runs")
    epv_gain: float = Field(description="Gain in possession value attributable to the run")
    gap_opens_without_run: bool
    runs: int = Field(default=0, description="Re-runs behind these numbers")


class AnswerKeyMoment(Versioned):
    """answer_key.json: a labelled moment, planted by the director or labelled by the oracle."""

    moment_id: str
    match_id: str
    source: Literal["planted", "oracle"]
    type: MomentType
    period: int
    t_start_ms: int
    t_end_ms: int
    team_id: str
    creator_id: str
    dragged_ids: list[str] = Field(default_factory=list)
    receiver_id: str | None = None
    gap_zone: list[XY] = Field(default_factory=list)
    expected: dict[str, float] = Field(default_factory=dict)
    observed: dict[str, float] = Field(default_factory=dict, description="Signal values the generator measured")
    counterfactual: CounterfactualTruth | None = None
    is_null: bool = False
    outcome: str | None = None
    attempts: int = 1


class TrueProbability(Contract):
    """probabilities.jsonl: the true success probability of each pass and shot, ground truth for xPass and xG."""

    event_id: str
    kind: Literal["pass", "shot"]
    p_success: float = Field(ge=0, le=1)
    features: dict[str, Any] = Field(default_factory=dict)
