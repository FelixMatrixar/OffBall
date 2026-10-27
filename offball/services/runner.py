"""A live run (PRD 11.4, 11.9): the emitter feeds the live service, and the crew explains what it finds.

With VALKEY_URL set, the feed travels through the match's stream on the event bus (PRD 11.5); without it, the
emitter hands each message straight to ingest. Every confirmed moment goes to the broadcast crew, a few at a time
(`OFFBALL_MAX_MOMENTS`, default 2): the rest wait their turn, so a busy spell can't flood the model with workflows.
Without a configured model the crew is off: frames, clock and score still stream, and no graphics air, because
only the agents may write them.
"""

from __future__ import annotations

import asyncio
import logging
import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path

from offball.agents.broadcast import Outcome, run_moment
from offball.agents.corrections import handle_correction
from offball.agents.crew import Crew
from offball.agents.engineer import check as engineer_check
from offball.mcp import tools as T
from offball.services.bus import ValkeyBus, bus_from_env
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
    # Whoever starts a run produces it (PRD 11.7): a random token, kept only with the run, so no key to keep secret.
    producer_token: str = field(default_factory=lambda: secrets.token_urlsafe(18))
    produced: bool = False  # started by a producer through POST /api/live-runs
    bus: ValkeyBus | None = field(default_factory=bus_from_env)
    run_id: str = field(default_factory=lambda: secrets.token_hex(8))

    def __post_init__(self) -> None:
        self.emitter = FeedEmitter(self.match_dir, self.config)
        self.match_id = self.emitter.match_id
        self.state = MatchState(self.match_id)
        STORE.matches[self.match_id] = self.state
        self.live = LiveMatch(self.emitter.info, self.state, speed=self.config.speed)
        self._moments: list[asyncio.Task] = []
        self._started: set[str] = set()
        self._slots = asyncio.Semaphore(max(1, int(os.environ.get("OFFBALL_MAX_MOMENTS", "2"))))
        self.state.on_append(self._on_envelope)

    def _on_envelope(self, env) -> None:
        """A feed correction sends what is on air back to the crew (PRD 14.11)."""
        if env.kind == "correction" and self.crew:
            self._moments.append(asyncio.create_task(self._correction(env.payload["event_id"])))

    async def _correction(self, event_id: str) -> None:
        try:
            async with self._slots:
                outcomes = await handle_correction(self.crew, self.state, self.match_id, event_id, self.settings)
        except Exception:  # the correction fails; the show goes on
            log.exception("Correction to %s failed", event_id)
            return
        self.outcomes.extend(outcomes)

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
            async with self._slots:
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

    async def _engineer(self) -> None:
        """The Engineer's own check, every minute of the run (PRD 14.11 `engineer` workflow)."""
        every = float(os.environ.get("OFFBALL_ENGINEER_EVERY_S", "60"))
        while not self.done.is_set():
            await asyncio.sleep(every)
            try:
                await engineer_check(self.crew, self.state)
            except Exception:  # the Engineer failing must never stop the show
                log.exception("The Engineer's check failed")

    async def _through_bus(self, bus: ValkeyBus) -> None:
        """The emitter writes the feed to the match's stream, and ingest reads it back from there (PRD 11.5)."""
        start = await bus.position(self.match_id)

        async def read() -> None:
            async for msg in bus.read(self.match_id, self.run_id, start):
                await self._sink(msg)

        reader = asyncio.create_task(read())
        try:
            await self.emitter.play(lambda msg: bus.append(self.match_id, self.run_id, msg), self.stop)
            await bus.end(self.match_id, self.run_id)
            await reader
        finally:
            reader.cancel()
            await bus.close()

    async def run(self) -> None:
        T.REGISTRY.register_live(self.match_id, self.live)
        beat = asyncio.create_task(self._heartbeat())
        watch = asyncio.create_task(self._engineer()) if self.crew else None
        try:
            if self.bus is None:
                await self.emitter.play(self._sink, self.stop)
            else:
                await self._through_bus(self.bus)
            while pending := [t for t in self._moments if not t.done()]:
                await asyncio.gather(*pending)  # corrections may add work while moments finish
        finally:
            T.REGISTRY.unregister_live(self.match_id)
            self.done.set()
            beat.cancel()
            if watch:
                watch.cancel()


RUNS: dict[str, LiveRun] = {}


def start_run(match_dir: Path, config: EmitterConfig, crew: Crew | None, restart: bool = False) -> LiveRun:
    """Join the match's run for this window, or start one. A finished run is joined, not replayed, so a viewer
    who reconnects after full time sees the final state instead of the match starting again. A run a producer
    started (`restart`, from POST /api/live-runs) is joined by every viewer while it plays, whatever window they
    ask for, so nobody can stop a producer's show by opening the stream."""
    match_id = match_dir.name
    current = RUNS.get(match_id)
    playing = current is not None and not current.done.is_set()
    if current and not restart and (current.config == config or (playing and current.produced)):
        return current
    if playing:
        current.stop.set()
    run = LiveRun(match_dir, config, crew, produced=restart)
    RUNS[match_id] = run
    asyncio.get_running_loop().create_task(run.run())
    return run


def current_state(match_id: str) -> MatchState | None:
    run = RUNS.get(match_id)
    return run.state if run else None
