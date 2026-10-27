"""What each agent writes, as structured output (PRD 14.10, 14.12).

These are the shapes the models fill in. They avoid open-ended objects so they work with strict JSON-schema
output; anything open (a metric's parameters) travels as a JSON string. The crew turns them into the published
hand-off contracts in `offball.contracts`.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Mode = Literal["casual", "learn", "analyst", "player", "audio", "broadcaster"]
MODES: tuple[Mode, ...] = ("casual", "learn", "analyst", "player", "audio", "broadcaster")
# The languages the Persona writes (PRD 23.1, M3). Each is written directly, not translated from English (14.12).
LANGS: tuple[str, ...] = ("en", "es", "fr")
Beat = Literal["run_start", "defender_follows", "gap_opens", "pass_into_gap", "shot", "goal", "after"]
# The Producer can also time a graphic from "now": the live clock plus the viewers' buffer.
ScheduleBeat = Literal["run_start", "defender_follows", "gap_opens", "pass_into_gap", "shot", "goal", "after", "now"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ScoutDecision(Strict):
    airtime: bool = Field(description="True if this moment should go on air now")
    priority: int = Field(ge=0, le=5, description="0 is the most important")
    want_counterfactual: bool = Field(description="True if a what-if replay would help viewers believe the cause")
    reason: str = Field(description="One sentence on why, for the producer's trace")


class ClaimOut(Strict):
    claim_id: str = Field(description="c1, c2, ... unique within the draft")
    kind: Literal["number", "statement"]
    text: str = Field(description="The claim in plain English, with its number and unit if it has one")
    metric: str | None = Field(description="For a number claim: the compute_metric name that produced it")
    params_json: str | None = Field(description="For a number claim: the exact params given to compute_metric, as JSON")
    value: float | None = Field(description="For a number claim: the value compute_metric returned")
    unit: str | None = Field(description="For a number claim: the unit compute_metric returned")
    subject_ids: list[str] = Field(description="Player or club IDs the claim is about")
    evidence_ids: list[str] = Field(description="Event and frame IDs from the tool results that support it")


class DraftOut(Strict):
    headline: str = Field(description="Why the moment matters, in one sentence")
    claims: list[ClaimOut] = Field(min_length=2, max_length=7)
    confidence: float = Field(ge=0, le=1, description="How sure the evidence makes you, 0 to 1")


class ClaimCheck(Strict):
    claim_id: str
    ok: bool
    recomputed: float | None = Field(description="The value compute_metric gave when you checked, for number claims")
    reason: str = Field(description="Why it passes or fails; for a failure, what the Explainer must change")


class VerdictOut(Strict):
    passed: bool = Field(description="True only if every claim is ok")
    checks: list[ClaimCheck]


class Localized(Strict):
    """The same words in each language the Persona writes."""

    en: str = Field(description="English")
    es: str = Field(description="Spanish, written directly in Spanish with the Spanish glossary")
    fr: str = Field(description="French, written directly in French with the French glossary")


class Line(Strict):
    beat: Beat = Field(description="The beat of the play this line belongs to")
    text: Localized = Field(description="What viewers read, and in audio mode what they hear")
    a11y_text: Localized = Field(description="What a screen reader announces: describe the picture, don't repeat the line")
    player_id: str | None = Field(description="Player focus only: the player this line follows; otherwise null")
    claim_ids: list[str] = Field(description="The verified claims this line relies on")


class ModeScript(Strict):
    mode: Mode
    lines: list[Line] = Field(min_length=1, max_length=12)
    runner_tag: Localized = Field(description="Two to four words shown over the runner")
    defender_tag: Localized = Field(description="Two to four words shown over the defender who was pulled away")
    receiver_tag: Localized = Field(description="Two to four words shown over the player who received in the space")
    ring_label: Localized = Field(description="Two to four words on the ring where space opens")
    stat_title: Localized = Field(description="Broadcaster stat card title, in capitals; empty for other modes")
    stat_claim_id: str | None = Field(description="Broadcaster: the verified number claim the stat card shows")
    glossary_terms: list[str] = Field(description="Glossary keys this script uses, such as decoy_run")


BLANK = Localized(en="", es="", fr="")


class LineFlag(Strict):
    mode: Mode
    line_index: int = Field(description="Index of the line in that mode's script, from 0")
    reason: str = Field(description="What is wrong, and in which language")


class ScriptCheck(Strict):
    flagged: list[LineFlag] = Field(description="Lines that state anything the verified claims don't support")


TextRef = Literal["line", "runner_tag", "defender_tag", "receiver_tag", "ring_label", "stat_title", "none"]
Anchor = Literal["none", "runner", "defender", "receiver", "passer", "run", "defender_move", "gap", "pass"]
Kind = Literal["caption", "run_arrow", "gap_ring", "pass_line", "player_tag", "stat_card", "badge"]


class PlannedOverlay(Strict):
    mode: Mode
    kind: Kind
    anchor: Anchor = Field(description="What the graphic is attached to on the pitch")
    text_ref: TextRef = Field(description="Which of the Persona's words it shows")
    line_index: int | None = Field(description="For text_ref 'line': the index of the line in that mode's script")
    start_beat: ScheduleBeat
    start_offset_s: float = Field(description="Seconds after start_beat; may be negative to lead the action")
    end_beat: ScheduleBeat
    end_offset_s: float
    priority: int = Field(ge=0, le=5, description="0 is the most important")
    approval: Literal["auto", "pending"] = Field(description="pending sends it to the producer's queue first")


class Schedule(Strict):
    overlays: list[PlannedOverlay] = Field(min_length=1, max_length=60)
    note: str = Field(description="One sentence for the producer's trace")


Flag = Literal["explainer.model_tier", "persona.live_languages", "producer.density", "tactician.enabled",
               "voice.enabled"]


class EngineerDecision(Strict):
    action: Literal["none", "set_flag"] = Field(description="set_flag applies one playbook mitigation; none if healthy")
    flag: Flag | None = Field(description="For set_flag: the degrade flag to change")
    value: str | None = Field(description="For set_flag: the flag's new value, one the playbook allows")
    severity: Literal["info", "warning", "critical"]
    summary: str = Field(description="One or two sentences for the producer: what you saw and what you did")
    evidence: list[str] = Field(description="The readings you relied on, such as 'explainer p95 4210 ms, budget 1000'")


class AnswerClaim(Strict):
    text: str
    verified: bool = Field(description="True only if a tool result you quote supports it")
    evidence: list[str] = Field(description="Event and frame IDs, or metric names with their values")


class AnswerOut(Strict):
    state: Literal["ok", "partial", "declined", "unknown"]
    claims: list[AnswerClaim]
    alternative_label: str | None = Field(description="For a declined or unknown question: a better question, short")
    alternative_question: str | None
    show_period: int | None = Field(description="The play that shows the answer on the pitch: its period, or null "
                                                "when no single play shows it")
    show_from_ms: int | None = Field(description="When that play starts, in ms into the period: a couple of seconds "
                                                 "before the key action")
    show_to_ms: int | None = Field(description="When it ends, in ms into the period: at most 15 s after it starts")
    show_player_ids: list[str] = Field(description="The players the answer is about, to ring while it plays")
    show_moment_id: str | None = Field(description="The detected moment the play is, if it is one")


class NumberUsed(Strict):
    name: str = Field(description="The number's name exactly as given, such as space_created_m2")
    value: float = Field(description="The value written, as given")


class TacticianOut(Strict):
    headline: Localized = Field(description="Three to six words: the verdict")
    plain: Localized = Field(description="One or two plain sentences for a casual viewer, at most one number")
    analyst: Localized = Field(description="One or two precise sentences with the numbers, units and interval")
    numbers: list[NumberUsed] = Field(description="Every number written in any field, with its name and value")
