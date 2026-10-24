"""match.json, events.jsonl and tracking frames (PRD 12.8)."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from offball.contracts.base import XY, XYZ, Contract, Versioned

Role = Literal["GK", "RB", "CB", "LB", "RWB", "LWB", "DM", "CM", "AM", "RM", "LM", "RW", "LW", "ST"]
Pattern = Literal["plain", "hoops", "stripes", "halves", "sash"]


class Kit(Contract):
    primary: str = Field(pattern=r"^#[0-9a-f]{6}$")
    secondary: str = Field(pattern=r"^#[0-9a-f]{6}$")
    pattern: Pattern = "plain"


class LineupEntry(Contract):
    player_id: str
    name: str
    number: int = Field(ge=1, le=99)
    role: Role
    starter: bool = True


class TeamSheet(Contract):
    club_id: str
    name: str
    short_name: str = Field(min_length=3, max_length=3)
    kit: Kit = Field(description="The kit worn in this match, after the colour-vision check (PRD 16.3)")
    formation: str
    lineup: list[LineupEntry]


class PeriodInfo(Contract):
    period: int = Field(ge=1, le=4)
    duration_ms: int = Field(ge=0)
    attacks_left_to_right: str = Field(description="club_id of the team attacking towards x = 105 this period")


class MatchInfo(Versioned):
    """match.json: one file per match."""

    match_id: str
    seed: int
    engine: Literal["fast", "emergent"]
    generator_version: str
    competition: str = "OffBall League"
    season: str = "2026"
    round: int | None = None
    home: TeamSheet
    away: TeamSheet
    periods: list[PeriodInfo]
    final_score: dict[str, int] = Field(description="Goals per club_id")
    frame_rate: int = 25
    pitch: tuple[float, float] = (105.0, 68.0)
    synthetic: Literal[True] = Field(default=True, description="Every OffBall match is synthetic (rule 4.7)")


EventType = Literal[
    "period_start",
    "period_end",
    "pass",
    "carry",
    "shot",
    "save",
    "tackle",
    "interception",
    "clearance",
    "foul",
    "card",
    "offside",
    "ball_out",
    "substitution",
]


class Event(Versioned):
    """One line of events.jsonl, and the payload of an `event` feed message."""

    event_id: str
    possession_id: str | None = None
    period: int
    t_ms: int = Field(ge=0)
    team_id: str | None = None
    player_id: str | None = None
    type: EventType
    subtype: str | None = None
    start_xy: XY | None = None
    end_xy: XY | None = None
    outcome: str | None = None
    body_part: Literal["right_foot", "left_foot", "head", "other"] | None = None
    under_pressure: bool = False
    ball_speed_mps: float | None = None
    recipient_id: str | None = Field(
        default=None, description="Pass receiver; for a substitution, the player coming on"
    )
    opponent_id: str | None = Field(default=None, description="The player challenged, for tackles and fouls")
    related_event_ids: list[str] = Field(default_factory=list)


class TrackedFrame(Contract):
    """A 25 Hz frame as it travels on the feed. On disk, frames are one row each in tracking.parquet."""

    period: int
    frame_id: int
    t_ms: int
    ball: XYZ
    players: dict[str, tuple[float, float, float]] = Field(
        description="player_id -> [x, y, orientation in radians]; only players on the pitch"
    )
