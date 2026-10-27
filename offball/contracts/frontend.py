"""Shapes the frontend already reads, published as contracts (PRD 11.3; INTEGRATION.md sections 4 to 6).

Each model mirrors a TypeScript type in `web/src` field for field, including its camelCase names, so a backend that
sends them needs no change in the UI.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from offball.contracts.base import XY, Contract, Versioned
from offball.contracts.match import TrackedFrame

Words = dict[str, dict[str, str]]  # words per locale, then per field, as the language packs hold them


class FrameMessage(Contract):
    """`FrameMessage` in web/src/lib/feed/types.ts: one tracked frame on the stream (INTEGRATION.md note 1)."""

    type: Literal["frame"] = "frame"
    match_id: str
    frame: TrackedFrame


class AnswerClaim(Contract):
    text: str
    verified: bool
    evidence: list[str] = Field(description="Event and frame IDs, or metric names with their values")


class AnswerChart(Contract):
    title: str
    spec: dict[str, Any] = Field(description="A Vega-Lite spec without colours; the frontend themes it (VIS-7)")
    summary: str
    columns: list[str]
    rows: list[list[str | float]]


class Alternative(Contract):
    label: str
    question: str


class AnswerShow(Contract):
    """The play that shows an answer on the pitch: the app jumps there, rings the players and plays it."""

    period: int
    from_ms: int
    to_ms: int
    player_ids: list[str]
    moment_id: str | None = None


class Answer(Contract):
    """`Answer` in web/src/lib/pundit.ts: Ask OffBall's reply (INTEGRATION.md 6.1)."""

    question: str
    state: Literal["ok", "partial", "declined", "unknown"]
    claims: list[AnswerClaim]
    chart: AnswerChart | None = None
    tools: list[str] = Field(description="The tools the Pundit called, in order")
    alternative: Alternative | None = Field(default=None, description="For a declined or unknown question")
    corrected: bool | None = Field(default=None, description="A corrected event changed the answer")
    show: AnswerShow | None = Field(default=None, description="The play that shows the answer on the pitch")


class DecisionOption(Contract):
    option_id: str
    actual: bool | None = Field(default=None, description="True for what the player really did")
    value: float = Field(description="The option's modelled value, which ranks it")
    words: Words = Field(description="Per locale: label, detail, and for a changed decision world, plain and ring")


class DecisionPoint(Contract):
    """A decision in a moment that a viewer can change (INTEGRATION.md 6.2; `DecisionChoice` in the language packs)."""

    point_id: str
    player_id: str
    period: int
    t_ms: int
    words: Words = Field(description="Per locale: what and question")
    options: list[DecisionOption] = Field(description="Ranked by modelled value, from the observed state only")


class DecisionCounts(Contract):
    gapOpens: int = Field(description="Re-runs in which the gap opened")
    shots: int
    goals: int
    space: tuple[float, float, float] = Field(description="Space in m²: median and the 90% interval")
    xg: float = Field(description="The best chance's xG, median")
    offside: int | None = None


class PlannedPass(Contract):
    to: XY
    difficulty: float = Field(ge=0, le=10)


class Ring(Contract):
    at: XY
    open: bool


class DecisionResult(Contract):
    """The result of re-running a changed decision (INTEGRATION.md 6.2)."""

    option_id: str
    counterfactual_id: str
    result: DecisionCounts
    tracks: dict[str, list[tuple[int, float, float]]] = Field(description="Per player the change moved: [t_ms, x, y]")
    ball: list[tuple[int, float, float]] | None = None
    pass_: PlannedPass | None = Field(default=None, alias="pass", description="A pass that wasn't played")
    ring: Ring
    analyst: str = Field(description="The verdict with its numbers, for Analyst mode")


class DiagramPlayer(Contract):
    id: str
    at: XY


class DiagramRun(Contract):
    id: str
    from_: XY = Field(alias="from")
    to: XY


class DiagramPass(Contract):
    from_: XY = Field(alias="from")
    to: XY


class MomentDiagram(Contract):
    """`MomentDiagram` in web/src/lib/recap.ts, in metres."""

    players: list[DiagramPlayer]
    run: DiagramRun
    ring: XY
    pass_: DiagramPass | None = Field(default=None, alias="pass")
    ball: XY


class RecapMoment(Contract):
    """`RecapMoment` in web/src/lib/recap.ts: one moment, told with its result and spoiler-safe."""

    id: str = Field(description="The detected moment's ID")
    minute: int
    half: Literal[1, 2]
    team: str
    creator: str
    finisher: str
    title: str
    safeTitle: str
    text: str
    safeText: str
    space: tuple[float, float, float] = Field(description="Space Created in m², with its 90% interval")
    threat: float
    outcome: Literal["goal", "saved", "off target", "blocked"]
    replay: bool
    diagram: MomentDiagram


class RecapPackage(Contract):
    """`RecapPackage` in web/src/lib/recap.ts (INTEGRATION.md 6.4), with its moments."""

    kind: Literal["halftime", "fulltime"]
    moments: list[str] = Field(description="Moment IDs, in the order the recap tells them")
    spoilerSafe: bool
    publishedAt: str | None = Field(description="When the producer published it; null for the automatic package")
    stories: list[RecapMoment] = Field(default_factory=list, description="The moments themselves")


class Alert(Versioned):
    """A typed alert from a Fabric Activator rule, published to the `alerts` hub (PRD 17.4) for the Engineer and the
    producer console."""

    kind: Literal["alert"] = "alert"
    alert_id: str
    match_id: str | None = None
    rule: Literal["fatigue_gap", "momentum_swing", "latency_trend", "other"]
    severity: Literal["info", "warning", "critical"]
    summary: str
    properties: dict[str, Any] = Field(default_factory=dict, description="What the rule saw, as Activator passed it")
    raised_at: str = Field(description="ISO 8601 UTC timestamp")
    source: Literal["activator", "power-automate", "engineer"] = "activator"


class RoundMoment(Contract):
    """One match on the Space Centre's whip-around (`MatchdayGame` in web/src/lib/content.ts), with positions in
    metres rather than the stand-in's drawing units (INTEGRATION.md note 4)."""

    match_id: str
    home: str
    away: str
    hs: int
    as_: int = Field(alias="as")
    base: int = Field(description="Match clock in seconds when the moment opened")
    type: str
    value: float = Field(description="Space value, which ranks the round's moments")
    text: str
    gap: XY
    arrow: tuple[float, float, float, float] = Field(description="The run: from x, from y, to x, to y, in metres")


class RoundMoments(Contract):
    """`round.moments` on a round's stream: the moments ranked across the round's matches (PRD 11.6)."""

    type: Literal["round.moments"] = "round.moments"
    round_id: str
    moments: list[RoundMoment]
    sent_at: str
