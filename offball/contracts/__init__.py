"""OffBall data contracts. Every format is versioned with schema_version and published as JSON Schema."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel

from offball.contracts.agents import (
    ApprovalDecision,
    Candidate,
    Claim,
    ClaimVerdict,
    CounterfactualResult,
    DetectableType,
    Draft,
    Envelope,
    FlagChange,
    Incident,
    Interval,
    MomentPick,
    Signal,
    Variant,
    Verdict,
)
from offball.contracts.base import XY, XYZ, Contract, Versioned
from offball.contracts.feed import (
    ClockSync,
    FeedMessage,
    MatchStatusMessage,
    OverlayRetract,
    OverlayUpsert,
    StatusPayload,
)
from offball.contracts.frontend import (
    Alert,
    Answer,
    DecisionPoint,
    DecisionResult,
    FrameMessage,
    RecapMoment,
    RecapPackage,
    RoundMoments,
)
from offball.contracts.match import Event, Kit, LineupEntry, MatchInfo, PeriodInfo, TeamSheet, TrackedFrame
from offball.contracts.overlay import LAYER_OF, MODES, Anchors, Mode, Overlay, Speech
from offball.contracts.truth import (
    MOMENT_TYPES,
    NULL_TYPES,
    AnswerKeyMoment,
    CounterfactualTruth,
    Intent,
    TrueProbability,
)

# Published schemas: file name -> model. Truth schemas are published too; the data itself is held out.
PUBLISHED: dict[str, type[BaseModel]] = {
    "match.schema.json": MatchInfo,
    "event.schema.json": Event,
    "tracked-frame.schema.json": TrackedFrame,
    "feed-message.schema.json": FeedMessage,
    "overlay.schema.json": Overlay,
    "overlay-upsert.schema.json": OverlayUpsert,
    "overlay-retract.schema.json": OverlayRetract,
    "clock-sync.schema.json": ClockSync,
    "match-status.schema.json": MatchStatusMessage,
    "intent.schema.json": Intent,
    "answer-key-moment.schema.json": AnswerKeyMoment,
    "true-probability.schema.json": TrueProbability,
    "agents/candidate.schema.json": Candidate,
    "agents/moment.schema.json": MomentPick,
    "agents/counterfactual.schema.json": CounterfactualResult,
    "agents/draft.schema.json": Draft,
    "agents/verdict.schema.json": Verdict,
    "agents/variant.schema.json": Variant,
    "agents/approval.schema.json": ApprovalDecision,
    "agents/incident.schema.json": Incident,
    "agents/envelope.schema.json": Envelope,
    # Shapes the frontend already reads (PRD 11.3).
    "frame-message.schema.json": FrameMessage,
    "answer.schema.json": Answer,
    "decision-point.schema.json": DecisionPoint,
    "decision-result.schema.json": DecisionResult,
    "recap.schema.json": RecapPackage,
    "alert.schema.json": Alert,
    "round-moments.schema.json": RoundMoments,
}


def published() -> dict[str, type[BaseModel]]:
    """Every published contract, with the Match director's script from the generator, which is imported late so the
    contracts never depend on the generator at import time."""
    from offball.generator.script import MatchScript

    return {**PUBLISHED, "match-script.schema.json": MatchScript}


def export_schemas(out_dir: Path) -> list[Path]:
    """Write every published JSON Schema under out_dir. Returns the files written."""
    written = []
    for name, model in published().items():
        path = out_dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        schema = model.model_json_schema()
        schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        schema["$id"] = f"https://offball.dev/contracts/{name}"
        path.write_text(json.dumps(schema, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
        written.append(path)
    return written


__all__ = [
    "LAYER_OF",
    "MODES",
    "MOMENT_TYPES",
    "NULL_TYPES",
    "PUBLISHED",
    "XY",
    "XYZ",
    "Alert",
    "Anchors",
    "Answer",
    "AnswerKeyMoment",
    "ApprovalDecision",
    "Candidate",
    "Claim",
    "ClaimVerdict",
    "ClockSync",
    "Contract",
    "CounterfactualResult",
    "CounterfactualTruth",
    "DecisionPoint",
    "DecisionResult",
    "DetectableType",
    "Draft",
    "Envelope",
    "Event",
    "FeedMessage",
    "FlagChange",
    "FrameMessage",
    "Incident",
    "Intent",
    "Interval",
    "Kit",
    "LineupEntry",
    "MatchInfo",
    "MatchStatusMessage",
    "Mode",
    "MomentPick",
    "Overlay",
    "OverlayRetract",
    "OverlayUpsert",
    "PeriodInfo",
    "RecapMoment",
    "RecapPackage",
    "RoundMoments",
    "Signal",
    "Speech",
    "StatusPayload",
    "TeamSheet",
    "TrackedFrame",
    "TrueProbability",
    "Variant",
    "Verdict",
    "Versioned",
    "export_schemas",
    "published",
]
