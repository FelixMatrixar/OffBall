"""Match scripts: what the Match director asks the engine to play (PRD 12.5 layer 2)."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from offball.contracts.base import Contract
from offball.contracts.truth import MomentType

Outcome = Literal["goal", "shot", "chance", "none"]


class StoryMoment(Contract):
    """A moment requested as an intent with soft constraints; the engine must still make it happen."""

    key: str = Field(description="Short label, unique in the script, e.g. k03")
    type: MomentType
    team: str = Field(description="club_id of the team that creates the moment (attacks)")
    minute: float = Field(ge=0, le=95, description="Earliest match minute for the moment")
    window_minutes: float = Field(default=4.0, gt=0, le=20)
    creator_id: str | None = None
    dragged_id: str | None = None
    receiver_id: str | None = None
    outcome: Outcome = "chance"
    note: str = ""
    latest_minute: float | None = Field(default=None, ge=0, le=95, description="The moment must start by this minute")
    sure: bool = Field(default=False, description="Its final shot ends as `outcome` asks, rather than as drawn")


class ScorePath(Contract):
    """No goals before `minute` beyond `max_goals` per club; used to keep a script's story intact."""

    minute: float
    max_goals: dict[str, int]


class MatchScript(Contract):
    match_id: str
    home: str
    away: str
    seed: int
    brief: str = ""
    round: int | None = None
    moments: list[StoryMoment] = Field(default_factory=list, max_length=8)
    score_path: list[ScorePath] = Field(default_factory=list)
    half_minutes: float = Field(default=45.0, gt=0, le=45.0)
    home_attacks_right_first: bool = Field(default=True, description="The home side attacks towards x = 105 in "
                                           "the first half")
    subs_after_minute: float = Field(default=0.0, ge=0, le=95, description="No substitutions before this minute")

    def validate_against(self, league) -> list[str]:
        """Problems a script can have before it is played. An empty list means it can be dry-run."""
        problems = []
        clubs = {c.club_id for c in league.clubs}
        for cid in (self.home, self.away):
            if cid not in clubs:
                problems.append(f"Unknown club {cid}")
        if self.home == self.away:
            problems.append("Home and away must differ")
        keys = [m.key for m in self.moments]
        if len(keys) != len(set(keys)):
            problems.append("Moment keys must be unique")
        last = -1.0
        for m in sorted(self.moments, key=lambda m: m.minute):
            if m.team not in (self.home, self.away):
                problems.append(f"{m.key}: team {m.team} is not playing")
            if m.minute < last + 2.0:
                problems.append(f"{m.key}: moments need at least 2 minutes between them")
            if 44.0 < m.minute < 46.0:
                problems.append(f"{m.key}: avoid the half-time boundary")
            if m.minute > 2 * self.half_minutes - 1:
                problems.append(f"{m.key}: after the end of the match")
            for pid in (m.creator_id, m.dragged_id, m.receiver_id):
                if pid is not None:
                    try:
                        league.player(pid)
                    except KeyError:
                        problems.append(f"{m.key}: unknown player {pid}")
            last = m.minute
        return problems
