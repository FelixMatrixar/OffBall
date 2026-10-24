"""The feed emitter (PRD 12.5 layer 5): replays a generated match as a live feed, faults included.

It sends status changes, 25 Hz frames and ball events in match-time order at 1x to 60x, with the faults a
real feed has: about 1% of events late, about 1% of messages sent twice, and optional frame drops.
"""

from __future__ import annotations

import asyncio
import json
import random
import time
from collections.abc import Awaitable, Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

from offball.contracts import Event, MatchInfo
from offball.core import SCHEMA_VERSION


@dataclass(frozen=True)
class EmitterConfig:
    speed: float = 1.0
    period: int | None = None  # start in this period; None plays from the first
    from_ms: int = 0  # start this far into the start period
    to_ms: int | None = None  # stop this far into the start period; None plays to the end of the match
    faults: bool = True
    late_rate: float = 0.01
    late_by_ms: tuple[int, int] = (400, 1500)
    duplicate_rate: float = 0.01
    frame_drop_rate: float = 0.0
    seed: int = 7


@dataclass(order=True)
class Timed:
    due_ms: int  # match time, in ms from the start of the replay, at which the message goes out
    order: int
    msg: dict


def _iso(epoch_s: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(epoch_s)) + f".{int(epoch_s * 1000) % 1000:03d}Z"


class FeedEmitter:
    def __init__(self, match_dir: Path, config: EmitterConfig | None = None) -> None:
        self.dir = match_dir
        self.config = config or EmitterConfig()
        self.info = MatchInfo.model_validate_json((match_dir / "match.json").read_text(encoding="utf-8"))
        self.match_id = self.info.match_id
        self.events = [Event.model_validate_json(line) for line in
                       (match_dir / "events.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]

    # ------------------------------------------------------------------ the window being replayed
    def _span(self) -> list[tuple[int, int, int]]:
        """(period, from_ms, to_ms) for every period the replay covers."""
        c = self.config
        out = []
        for p in sorted(self.info.periods, key=lambda p: p.period):
            if c.period is not None and p.period < c.period:
                continue
            start = c.from_ms if p.period == c.period else 0
            end = p.duration_ms
            if c.period is not None and p.period == c.period and c.to_ms is not None:
                end = min(end, c.to_ms)
                out.append((p.period, start, end))
                break
            out.append((p.period, start, end))
        return out

    def messages(self) -> Iterator[Timed]:
        """Every message of the replay, in the order it goes out."""
        c = self.config
        rng = random.Random(c.seed)
        table = pq.read_table(self.dir / "tracking.parquet")
        names = table.column_names
        players = sorted({n[:-2] for n in names if n.endswith("_x") and not n.startswith("ball")})
        period_col = table.column("period").to_numpy()
        t_col = table.column("t_ms").to_numpy()
        out: list[Timed] = []
        seq = 0
        offset = 0  # match time of each period's start, measured from the start of the replay
        score = {self.info.home.club_id: 0, self.info.away.club_id: 0}
        order = 0

        def add(due: int, kind: str, payload: dict, corrects: str | None = None) -> None:
            nonlocal seq, order
            seq += 1
            msg = {"schema_version": SCHEMA_VERSION, "seq": seq, "match_id": self.match_id, "kind": kind,
                   "sent_at": "", "payload": payload, "corrects_event_id": corrects}
            out.append(Timed(due, order, msg))
            order += 1
            if c.faults and kind != "status" and rng.random() < c.duplicate_rate:
                out.append(Timed(due + rng.randint(20, 300), order, dict(msg)))
                order += 1

        span = self._span()
        # The score already on the board when the replay starts.
        first_period, first_start = span[0][0], span[0][1]
        for e in self.events:
            if (e.period, e.t_ms) < (first_period, first_start) and e.type == "shot" and e.outcome == "goal" \
                    and e.team_id in score:
                score[e.team_id] += 1
        for period, start, end in span:
            add(offset, "status", {"status": "in_play", "period": period, "t_ms": start, "score": dict(score)})
            sel = np.nonzero((period_col == period) & (t_col >= start) & (t_col <= end))[0]
            sub = table.take(sel)
            cols = {n: sub.column(n).to_numpy(zero_copy_only=False) for n in sub.column_names}
            for k in range(len(sel)):
                t = int(cols["t_ms"][k])
                if c.faults and c.frame_drop_rate and rng.random() < c.frame_drop_rate:
                    continue
                on_pitch = {}
                for pid in players:
                    x = cols[f"{pid}_x"][k]
                    if np.isnan(x):
                        continue
                    on_pitch[pid] = [round(float(x), 2), round(float(cols[f"{pid}_y"][k]), 2),
                                     round(float(cols[f"{pid}_o"][k]), 3)]
                frame = {"period": period, "frame_id": t // 40, "t_ms": t,
                         "ball": [round(float(cols["ball_x"][k]), 2), round(float(cols["ball_y"][k]), 2),
                                  round(float(cols["ball_z"][k]), 2)],
                         "players": on_pitch}
                add(offset + t - start, "frame", frame)
            for e in self.events:
                if e.period != period or not (start <= e.t_ms <= end):
                    continue
                due = offset + e.t_ms - start
                if c.faults and rng.random() < c.late_rate:
                    due += rng.randint(*c.late_by_ms)
                add(due, "event", e.model_dump(mode="json"))
                if e.type == "shot" and e.outcome == "goal" and e.team_id in score:
                    score[e.team_id] += 1
                    add(due + 1, "status", {"status": "in_play", "period": period, "t_ms": e.t_ms, "score": dict(score)})
            offset += end - start
            last = period == max(p.period for p in self.info.periods)
            finished = end >= next(p.duration_ms for p in self.info.periods if p.period == period)
            if finished:
                status = "full_time" if last else "half_time"
                add(offset, "status", {"status": status, "period": period, "t_ms": end, "score": dict(score)})
        out.sort()
        return iter(out)

    async def play(self, sink: Callable[[dict], Awaitable[None] | None], stop: asyncio.Event | None = None) -> None:
        """Send every message to `sink` in real time at the configured speed."""
        t0 = time.monotonic()
        for item in self.messages():
            if stop is not None and stop.is_set():
                return
            wait = item.due_ms / 1000 / self.config.speed - (time.monotonic() - t0)
            if wait > 0:
                await asyncio.sleep(wait)
            msg = dict(item.msg, sent_at=_iso(time.time()))
            result = sink(msg)
            if asyncio.iscoroutine(result):
                await result


def write_jsonl(emitter: FeedEmitter, path: Path) -> int:
    """Write the replay's messages as JSONL, in send order. Returns how many were written."""
    n = 0
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        for item in emitter.messages():
            fh.write(json.dumps(item.msg, separators=(",", ":")) + "\n")
            n += 1
    return n
