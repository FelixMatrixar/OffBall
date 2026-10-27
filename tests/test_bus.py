"""The event bus (PRD 11.5): a live run's feed through the match's stream reaches ingest exactly as it does
directly. The stand-in client below keeps only the stream commands the bus uses; the last test runs against a
real Valkey when VALKEY_URL is set (CI starts one)."""

from __future__ import annotations

import asyncio
import os
from collections import defaultdict

import pytest

from offball.services.bus import ValkeyBus
from offball.services.emitter import EmitterConfig
from offball.services.runner import LiveRun

from .conftest import GOAL_WINDOW


def _key(entry_id: str) -> tuple[int, int]:
    ms, n = entry_id.split("-")
    return int(ms), int(n)


class StreamsInMemory:
    """XADD, XREVRANGE and XREAD on one process's memory, with Valkey's reply shapes."""

    def __init__(self) -> None:
        self.streams: dict[str, list[tuple[str, dict]]] = defaultdict(list)
        self._n = 0

    async def xadd(self, name, fields, minid=None, approximate=True):
        self._n += 1
        entry_id = f"{self._n}-0"
        self.streams[name].append((entry_id, dict(fields)))
        return entry_id

    async def xrevrange(self, name, max="+", min="-", count=None):
        return list(reversed(self.streams.get(name, [])))[:count]

    async def xread(self, streams, count=None, block=None):
        ((name, after),) = streams.items()
        for _ in range(max(1, (block or 0) // 10)):
            entries = [e for e in self.streams.get(name, []) if _key(e[0]) > _key(after)][:count]
            if entries:
                return [[name, entries]]
            await asyncio.sleep(0.01)
        return []

    async def ping(self):
        return True

    async def aclose(self):
        pass


async def _play(m07, bus: ValkeyBus | None) -> tuple[list[dict], set[str]]:
    run = LiveRun(m07, EmitterConfig(**GOAL_WINDOW, speed=60), bus=bus)
    queue = run.state.subscribe(maxsize=100_000)
    await run.run()
    got = []
    while not queue.empty():
        m = queue.get_nowait()
        if m["type"] != "clock.sync":  # the heartbeat's syncs follow the wall clock, not the feed
            got.append({k: v for k, v in m.items() if k not in ("sent_at", "server_time")})
    return got, set(run.state.candidates)


async def test_the_feed_through_the_bus_matches_the_direct_path(m07) -> None:
    direct, direct_candidates = await _play(m07, None)
    store = StreamsInMemory()
    through, through_candidates = await _play(m07, ValkeyBus("valkey://stand-in", client=store))
    assert through == direct
    assert through_candidates == direct_candidates
    entries = store.streams["feed.m07"]
    assert entries[-1][1].get("end") == "1"
    assert sum("m" in fields for _, fields in entries) > len([m for m in direct if m["type"] == "frame"])


async def test_a_new_run_reads_only_its_own_entries(m07) -> None:
    store = StreamsInMemory()
    first, _ = await _play(m07, ValkeyBus("valkey://stand-in", client=store))
    second, _ = await _play(m07, ValkeyBus("valkey://stand-in", client=store))
    assert second == first
    assert sum("end" in fields for _, fields in store.streams["feed.m07"]) == 2


async def test_health_names_the_bus(monkeypatch) -> None:
    from offball.services.api import health

    monkeypatch.delenv("VALKEY_URL", raising=False)
    assert health()["bus"] == "in-process"
    monkeypatch.setenv("VALKEY_URL", "valkey://localhost:6379/0")
    assert health()["bus"] == "valkey"


@pytest.mark.skipif(not os.environ.get("VALKEY_URL"), reason="needs a Valkey server at VALKEY_URL")
async def test_the_feed_through_a_real_valkey(m07) -> None:
    direct, _ = await _play(m07, None)
    through, _ = await _play(m07, ValkeyBus(os.environ["VALKEY_URL"]))
    assert through == direct
