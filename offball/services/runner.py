"""A live run (PRD 11.4, 11.9): the emitter feeds the live service, and the crew explains what it finds.

Every confirmed moment goes to the broadcast crew. Without a configured model the crew is off: frames, clock
and score still stream, and no graphics air, because only the agents may write them.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path

from offball.agents.broadcast import Outcome, run_moment
from offball.agents.crew import Crew
from offball.mcp import tools as T
from offball.services.emitter import EmitterConfig, FeedEmitter
from offball.services.live import LiveMatch
from offball.services.state import STORE, MatchState

log = logging.getLogger("offball.run")


@dataclass
class LiveRun:
    match_dir: Path
    config: EmitterConfig
    crew: Crew | None = None
    settings: dict = field(default_factory=lambda: {"min_gap_s": 20, "approval": "auto"})
    outcomes: list[Outcome] = field(default_factory=list)
    done: asyncio.Event = field(default_factory=asyncio.Event)
    stop: asyncio.Event = field(default_factory=asyncio.Event)

    def __post_init__(self) -> None:
        self.emitter = FeedEmitter(self.match_dir, self.config)
        self.match_id = self.emitter.match_id
        self.state = MatchState(self.match_id)
        STORE.matches[self.match_id] = self.state
        self.live = LiveMatch(self.emitter.info, self.state, speed=self.config.speed)
        self._moments: list[asyncio.Task] = []
        self._started: set[str] = set()

    async def _sink(self, msg: dict) -> None:
        self.live.ingest(msg)
        if not self.live.detection_due():
            return
        for cand in self.live.detect_now():
            self.state.append("candidate", cand, produced_by="interpret")
            if self.crew and cand.status == "confirmed" and cand.candidate_id not in self._started:
                self._started.add(cand.candidate_id)
                self._moments.append(asyncio.create_task(self._moment(cand.candidate_id)))

    async def _moment(self, candidate_id: str) -> None:
        try:
            outcome = await run_moment(self.crew, self.state, self.match_id, candidate_id, self.settings)
        except Exception as exc:  # the moment fails; the show goes on
            log.exception("Moment %s failed", candidate_id)
            outcome = Outcome(candidate_id, "failed", [], f"{type(exc).__name__}: {exc}")
        self.outcomes.append(outcome)
        log.info("%s: %s %s", candidate_id, outcome.status, outcome.note)

    async def _heartbeat(self) -> None:
        while not self.done.is_set():
            await asyncio.sleep(1.0)
            self.live.sync_now()

    async def run(self) -> None:
        T.REGISTRY.register_live(self.match_id, self.live)
        beat = asyncio.create_task(self._heartbeat())
        try:
            await self.emitter.play(self._sink, self.stop)
            if self._moments:
                await asyncio.gather(*self._moments)
        finally:
            T.REGISTRY.unregister_live(self.match_id)
            self.done.set()
            beat.cancel()


RUNS: dict[str, LiveRun] = {}


def start_run(match_dir: Path, config: EmitterConfig, crew: Crew | None) -> LiveRun:
    """Join the match's run for this window, or start one. A finished run is joined, not replayed, so a viewer
    who reconnects after full time sees the final state instead of the match starting again."""
    match_id = match_dir.name
    current = RUNS.get(match_id)
    if current and current.config == config:
        return current
    if current and not current.done.is_set():
        current.stop.set()
    run = LiveRun(match_dir, config, crew)
    RUNS[match_id] = run
    asyncio.get_running_loop().create_task(run.run())
    return run


def current_state(match_id: str) -> MatchState | None:
    run = RUNS.get(match_id)
    return run.state if run else None
