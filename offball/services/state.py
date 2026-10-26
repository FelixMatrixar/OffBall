"""Match state: the shared, event-sourced store every agent and service reads and writes (PRD 14.3).

Agents never pass free text to each other. Each hand-off is a typed message appended here as an Envelope and
announced to subscribers, so every hop is replayable. Locally the store lives in memory and mirrors to JSONL;
on the VM the same interface is backed by PostgreSQL (keyed by match) and the relay (PRD 11.6, 11.8).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from offball.contracts import Candidate, Envelope, Overlay
from offball.models.match_data import MatchData
from offball.services.telemetry import event


def now_ms() -> int:
    return int(time.time() * 1000)


def iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + f".{now_ms() % 1000:03d}Z"


@dataclass
class TokenMeter:
    """Every model token a match has spent (PRD 14.10). At 80% of the budget only top-priority moments air, and
    at 100% no new moment starts (14.5)."""

    budget: int = field(default_factory=lambda: int(os.environ.get("TOKENS_PER_MATCH", "2000000")))
    used: int = 0

    def add(self, tokens: int) -> None:
        self.used += max(0, tokens)

    @property
    def share(self) -> float:
        return self.used / self.budget if self.budget > 0 else 0.0


@dataclass
class MatchState:
    match_id: str
    data: MatchData | None = None
    clock: tuple[int, int] = (1, 0)  # (period, t_ms) of the latest frame the pipeline has processed
    status: str = "pre_match"
    score: dict[str, int] = field(default_factory=dict)
    candidates: dict[str, Candidate] = field(default_factory=dict)
    overlays: dict[str, Overlay] = field(default_factory=dict)
    retracted: set[str] = field(default_factory=set)
    envelopes: list[Envelope] = field(default_factory=list)
    partner_log: list[dict] = field(default_factory=list)
    tokens: TokenMeter = field(default_factory=TokenMeter)
    mirror_dir: Path | None = None
    _subscribers: list[asyncio.Queue] = field(default_factory=list)
    _listeners: list[Callable[[Envelope], None]] = field(default_factory=list)

    # ------------------------------------------------------------------ hand-offs
    def append(self, kind: str, payload: BaseModel | dict, produced_by: str, trace_id: str | None = None) -> Envelope:
        body = payload.model_dump(mode="json") if isinstance(payload, BaseModel) else payload
        env = Envelope(seq=len(self.envelopes) + 1, match_id=self.match_id, kind=kind, produced_by=produced_by,
                       wall_ms=now_ms(), payload=body, trace_id=trace_id)
        self.envelopes.append(env)
        event("handoff", seq=env.seq, kind=kind, by=produced_by)
        if kind == "candidate":
            self.candidates[body["candidate_id"]] = Candidate.model_validate(body)
        self._mirror("envelopes.jsonl", env.model_dump(mode="json"))
        for fn in list(self._listeners):
            fn(env)
        return env

    def of_kind(self, kind: str) -> list[Envelope]:
        return [e for e in self.envelopes if e.kind == kind]

    def on_append(self, fn: Callable[[Envelope], None]) -> None:
        self._listeners.append(fn)

    # ------------------------------------------------------------------ overlays and the partner feed
    def upsert_overlay(self, overlay: Overlay) -> dict:
        self.overlays[overlay.overlay_id] = overlay
        event("overlay", overlay_id=overlay.overlay_id, rev=overlay.rev, mode=overlay.mode, kind=overlay.kind)
        msg = {"type": "overlay.upsert", "match_id": self.match_id, "overlay": overlay.model_dump(mode="json"),
               "sent_at": iso_now()}
        self._mirror("overlays.jsonl", overlay.model_dump(mode="json"))
        self.publish(msg)
        return msg

    def publish_revision(self, overlay: Overlay) -> dict | None:
        """Send a graphic once (BE-7): nothing when the same content already went out under its ID, or the next
        revision when it changed. A step that runs again therefore never airs a duplicate."""
        old = self.overlays.get(overlay.overlay_id)
        if old is not None:
            if old.model_dump(exclude={"rev"}) == overlay.model_dump(exclude={"rev"}):
                return None
            overlay = overlay.model_copy(update={"rev": old.rev + 1})
        return self.upsert_overlay(overlay)

    def retract_overlay(self, overlay_id: str, reason: str, corrects_event_id: str | None = None,
                        replacement_id: str | None = None) -> dict:
        self.retracted.add(overlay_id)
        msg = {"type": "overlay.retract", "match_id": self.match_id, "overlay_id": overlay_id, "reason": reason,
               "corrects_event_id": corrects_event_id, "replacement_id": replacement_id, "sent_at": iso_now()}
        self.publish(msg)
        return msg

    def live_overlays(self) -> list[Overlay]:
        return [o for oid, o in self.overlays.items() if oid not in self.retracted]

    def publish(self, msg: dict) -> None:
        if msg.get("type") != "frame":  # frames are already in the feed; keep the log to what the crew adds
            self.partner_log.append(msg)
            self._mirror("partner.jsonl", msg)
        for q in list(self._subscribers):
            # A slow subscriber drops messages rather than stalling the show.
            with contextlib.suppress(asyncio.QueueFull):
                q.put_nowait(msg)

    def subscribe(self, maxsize: int = 1000) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=maxsize)
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        if q in self._subscribers:
            self._subscribers.remove(q)

    def _mirror(self, name: str, row: dict[str, Any]) -> None:
        if self.mirror_dir is None:
            return
        self.mirror_dir.mkdir(parents=True, exist_ok=True)
        with (self.mirror_dir / name).open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


class StateStore:
    """All matches the pipeline knows about."""

    def __init__(self, mirror_root: Path | None = None) -> None:
        self.matches: dict[str, MatchState] = {}
        self.mirror_root = mirror_root

    def get(self, match_id: str) -> MatchState:
        try:
            return self.matches[match_id]
        except KeyError as exc:
            raise KeyError(f"Unknown match {match_id}") from exc

    def ensure(self, match_id: str, data: MatchData | None = None) -> MatchState:
        st = self.matches.get(match_id)
        if st is None:
            mirror = self.mirror_root / match_id if self.mirror_root else None
            st = MatchState(match_id=match_id, data=data, mirror_dir=mirror)
            if data is not None:
                st.score = {data.home: 0, data.away: 0}
            self.matches[match_id] = st
        elif data is not None:
            st.data = data
        return st

    def load_match(self, match_dir: Path) -> MatchState:
        data = MatchData.load(match_dir)
        st = self.ensure(data.match_id, data)
        last = max(data.periods)
        st.clock = (last, int(data.periods[last].t_ms[-1]))
        st.status = "full_time"
        st.score = dict(data.info.final_score)
        return st


STORE = StateStore()
