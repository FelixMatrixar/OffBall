"""The live service (PRD 11.4): ingest, interpret and relay for the matches it owns.

Ingest deduplicates the feed by sequence number, puts frames in their place by frame ID (so late or
out-of-order frames are fine), fills gaps of up to 0.4 s, and keeps events in time order with corrections
applied. Interpret runs the moment detectors over a rolling window every second of match time. Relay
publishes the client stream (frames, clock, score) to the match's subscribers.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass, field

import numpy as np

from offball.contracts import Candidate, Event, MatchInfo
from offball.core import FRAME_MS, detected_id
from offball.models.candidates import detect
from offball.models.match_data import MatchData, PeriodFrames
from offball.services.state import MatchState, iso_now

GAP_FILL_FRAMES = 10  # interpolate gaps up to 0.4 s (PRD 9.1)
WINDOW_MS = 15_000  # the interpret window
EDGE_MS = 1_000  # a run starting this close to the window's start may be cut short; skip it
SAME_MOMENT_MS = 3_000
STATUS_RANK = {"discarded": 0, "speculative": 1, "confirmed": 2}


class PeriodBuffer:
    """One period's frames, indexed by frame ID; grows as the period goes on."""

    def __init__(self, period: int, n_players: int, capacity: int = 4096) -> None:
        self.period = period
        self.p = n_players
        self.n = 0
        self._alloc(capacity)

    def _alloc(self, cap: int) -> None:
        def grow(old: np.ndarray | None, shape: tuple, fill: float) -> np.ndarray:
            new = np.full(shape, fill, dtype=np.float32)
            if old is not None:
                new[: len(old)] = old
            return new

        old = getattr(self, "xy", None)
        self.xy = grow(old, (cap, self.p, 2), np.nan)
        self.ori = grow(getattr(self, "ori", None), (cap, self.p), np.nan)
        self.ball = grow(getattr(self, "ball", None), (cap, 3), np.nan)
        have = np.zeros(cap, dtype=bool)
        if old is not None:
            have[: len(self.have)] = self.have
        self.have = have
        self.cap = cap

    def put(self, i: int, xy: np.ndarray, ori: np.ndarray, ball: np.ndarray) -> None:
        if i >= self.cap:
            self._alloc(max(self.cap * 2, i + 1))
        self.xy[i], self.ori[i], self.ball[i] = xy, ori, ball
        self.have[i] = True
        self.n = max(self.n, i + 1)
        self._fill_gap_before(i)

    def _fill_gap_before(self, i: int) -> None:
        lo = max(0, i - GAP_FILL_FRAMES - 1)
        prev = np.nonzero(self.have[lo:i])[0]
        if not len(prev):
            return
        j = lo + int(prev[-1])
        if i - j <= 1:
            return
        for k in range(j + 1, i):
            w = (k - j) / (i - j)
            self.xy[k] = self.xy[j] * (1 - w) + self.xy[i] * w
            self.ori[k] = self.ori[i]
            self.ball[k] = self.ball[j] * (1 - w) + self.ball[i] * w

    def view(self, i_from: int = 0, i_to: int | None = None) -> PeriodFrames:
        i_to = self.n if i_to is None else min(i_to, self.n)
        idx = np.arange(i_from, i_to)
        return PeriodFrames(self.period, (idx * FRAME_MS).astype(np.int64), self.xy[i_from:i_to],
                            self.ori[i_from:i_to], self.ball[i_from:i_to])


@dataclass
class LiveMatch:
    """A match as the live service sees it: only what has arrived so far."""

    info: MatchInfo
    state: MatchState
    speed: float = 1.0
    detect_every_ms: int = 1_000
    players: list[str] = field(default_factory=list)
    events: list[Event] = field(default_factory=list)
    _buffers: dict[int, PeriodBuffer] = field(default_factory=dict)
    _seen_seq: set[int] = field(default_factory=set)
    _event_keys: list[tuple[int, int, str]] = field(default_factory=list)
    _candidates: dict[str, Candidate] = field(default_factory=dict)
    _clock: tuple[int, int] = (1, 0)
    _last_sync: tuple[int, int] = (0, -1_000_000)
    _last_detect: tuple[int, int] = (0, -1_000_000)
    _data_cache: tuple[tuple[int, int], MatchData] | None = None
    corrections: list[tuple[str, str]] = field(default_factory=list)  # (corrected event ID, its replacement)

    def __post_init__(self) -> None:
        if not self.players:
            ids = [e.player_id for sheet in (self.info.home, self.info.away) for e in sheet.lineup]
            self.players = sorted(ids)
        self._col = {pid: k for k, pid in enumerate(self.players)}
        self.team_of = {pid: pid.split("-")[0] for pid in self.players}
        self.state.status = "pre_match"
        self.state.score = {self.info.home.club_id: 0, self.info.away.club_id: 0}

    # ------------------------------------------------------------------ the view tools read
    @property
    def match_id(self) -> str:
        return self.info.match_id

    @property
    def clock(self) -> tuple[int, int]:
        return self._clock

    def data(self) -> MatchData:
        """Everything observed so far, as the interpretation models and metric tools read it."""
        if self._data_cache and self._data_cache[0] == self._clock:
            return self._data_cache[1]
        md = MatchData(info=self.info, events=list(self.events), players=self.players, team_of=self.team_of,
                       periods={p: b.view() for p, b in sorted(self._buffers.items()) if b.n})
        self._data_cache = (self._clock, md)
        return md

    def candidates(self) -> list[Candidate]:
        return sorted(self._candidates.values(), key=lambda c: (c.period, c.t_start_ms))

    # ------------------------------------------------------------------ ingest and relay
    def ingest(self, msg: dict) -> None:
        seq = msg.get("seq")
        if seq in self._seen_seq:
            return  # a duplicate on the feed
        self._seen_seq.add(seq)
        kind, payload = msg["kind"], msg["payload"]
        if kind == "frame":
            self._frame(payload)
        elif kind in ("event", "correction"):
            self._event(Event.model_validate(payload), msg.get("corrects_event_id"))
        elif kind == "status":
            self._status(payload)

    def _frame(self, f: dict) -> None:
        period, t = f["period"], f["t_ms"]
        buf = self._buffers.get(period)
        if buf is None:
            buf = self._buffers[period] = PeriodBuffer(period, len(self.players))
        xy = np.full((len(self.players), 2), np.nan, dtype=np.float32)
        ori = np.full(len(self.players), np.nan, dtype=np.float32)
        for pid, (x, y, o) in f["players"].items():
            col = self._col.get(pid)
            if col is not None:
                xy[col] = (x, y)
                ori[col] = o
        buf.put(t // FRAME_MS, xy, ori, np.asarray(f["ball"], dtype=np.float32))
        if (period, t) > self._clock:
            self._clock = (period, t)
        self.state.clock = self._clock
        self.state.publish({"type": "frame", "match_id": self.match_id, "frame": f})
        self._maybe_sync()

    def _maybe_sync(self) -> None:
        period, t = self._clock
        if period != self._last_sync[0] or t - self._last_sync[1] >= 1000:
            self._last_sync = self._clock
            self.state.publish({"type": "clock.sync", "match_id": self.match_id, "period": period, "t_ms": t,
                                "speed": self.speed, "server_time": iso_now()})

    def sync_now(self) -> None:
        """Send clock.sync even in a quiet spell, so viewers never mistake silence for a stall."""
        period, t = self._clock
        self._last_sync = self._clock
        self.state.publish({"type": "clock.sync", "match_id": self.match_id, "period": period, "t_ms": t,
                            "speed": self.speed, "server_time": iso_now()})

    def _event(self, e: Event, corrects: str | None) -> None:
        if corrects:
            for k, old in enumerate(self.events):
                if old.event_id == corrects:
                    del self.events[k]
                    del self._event_keys[k]
                    break
            self.corrections.append((corrects, e.event_id))
        key = (e.period, e.t_ms, e.event_id)
        k = bisect.bisect_left(self._event_keys, key)
        if k < len(self._event_keys) and self._event_keys[k] == key:
            return
        self._event_keys.insert(k, key)
        self.events.insert(k, e)
        self._data_cache = None
        if corrects:
            # The crew re-checks whatever is on air that cites the corrected event (PRD 14.11).
            self.state.append("correction", {"event_id": corrects, "replacement_id": e.event_id,
                                             "period": self._clock[0], "t_ms": self._clock[1]}, produced_by="ingest")

    def _status(self, s: dict) -> None:
        self.state.status = s["status"]
        self.state.score = dict(s["score"])
        if (s["period"], s["t_ms"]) > self._clock:
            self._clock = (s["period"], s["t_ms"])
        self.state.publish({"type": "match.status", "match_id": self.match_id, "status": s["status"],
                            "period": s["period"], "t_ms": s["t_ms"], "score": dict(s["score"]), "sent_at": iso_now()})

    # ------------------------------------------------------------------ interpret
    def detection_due(self) -> bool:
        period, t = self._clock
        return period != self._last_detect[0] or t - self._last_detect[1] >= self.detect_every_ms

    def detect_now(self) -> list[Candidate]:
        """Run the detectors over the last 15 s; return candidates that are new or moved up in status."""
        self._last_detect = self._clock
        period, now = self._clock
        buf = self._buffers.get(period)
        if buf is None or buf.n < 50:
            return []
        win_from = max(0, now - WINDOW_MS)
        i_from = win_from // FRAME_MS
        window = MatchData(info=self.info, events=list(self.events), players=self.players, team_of=self.team_of,
                           periods={period: buf.view(i_from, now // FRAME_MS + 1)})
        changed = []
        for c in detect(window, period=period, t_from_ms=win_from, now_ms=now):
            if win_from > 0 and c.t_start_ms < win_from + EDGE_MS:
                continue
            known = next((k for k in self._candidates.values() if k.type == c.type and k.period == c.period
                          and k.creator_id == c.creator_id
                          and abs(k.t_start_ms - c.t_start_ms) < SAME_MOMENT_MS), None)
            if known is None:
                c.candidate_id = detected_id(self.match_id, len(self._candidates) + 1)
                self._candidates[c.candidate_id] = c
                changed.append(c)
            elif STATUS_RANK[c.status] > STATUS_RANK[known.status]:
                c.candidate_id = known.candidate_id
                self._candidates[c.candidate_id] = c
                changed.append(c)
        return changed


