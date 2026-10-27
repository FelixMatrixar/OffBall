"""The event bus (PRD 11.5): one Valkey stream per hub and match, `{hub}.{match_id}`.

With VALKEY_URL set, a live run's emitter appends every feed message to `feed.{match_id}`, and the live service
reads them back from there, so the feed reaches ingest the way a real feed or the vision tracker would send it.
Without it, the emitter hands each message straight to ingest in the same process, as in tests and replay builds.

Each match has exactly one owner (PRD 11.6), so the live service reads the stream by position rather than through
a consumer group: a run notes where the stream ended when it started, and reads every entry after that which
carries its run ID, until its end marker. Re-reading is safe, because ingest drops any `seq` it has seen. Streams
are trimmed to a day as they are written.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import AsyncIterator
from typing import Any

FEED = "feed"
KEEP_MS = 86_400_000  # streams keep a day (PRD 11.5)
BLOCK_MS = 1_000
BATCH = 500


def stream_key(hub: str, match_id: str) -> str:
    return f"{hub}.{match_id}"


def bus_url() -> str | None:
    return os.environ.get("VALKEY_URL", "").strip() or None


class ValkeyBus:
    """The feed hub on Valkey Streams. One per live run, so its connection belongs to the run's event loop."""

    def __init__(self, url: str | None = None, client: Any = None) -> None:
        self.url = url or bus_url()
        self._client = client

    @property
    def client(self) -> Any:
        if self._client is None:
            import valkey.asyncio as valkey

            self._client = valkey.from_url(self.url, decode_responses=True)
        return self._client

    async def position(self, match_id: str) -> str:
        """Where the match's feed stream ends now: a run reads only what comes after it."""
        last = await self.client.xrevrange(stream_key(FEED, match_id), count=1)
        return last[0][0] if last else "0-0"

    async def append(self, match_id: str, run_id: str, msg: dict) -> str:
        fields = {"run": run_id, "m": json.dumps(msg, separators=(",", ":"))}
        return await self.client.xadd(stream_key(FEED, match_id), fields, minid=self._oldest(), approximate=True)

    async def end(self, match_id: str, run_id: str) -> None:
        """The run's last entry: its reader stops here."""
        await self.client.xadd(stream_key(FEED, match_id), {"run": run_id, "end": "1"}, minid=self._oldest(),
                               approximate=True)

    async def read(self, match_id: str, run_id: str, after: str) -> AsyncIterator[dict]:
        """Every feed message of the run, in stream order, from `after` to the run's end marker."""
        key, last = stream_key(FEED, match_id), after
        while True:
            reply = await self.client.xread({key: last}, count=BATCH, block=BLOCK_MS)
            for _, entries in reply or []:
                for entry_id, fields in entries:
                    last = entry_id
                    if fields.get("run") != run_id:
                        continue  # another run of the same match, before this one stopped
                    if "end" in fields:
                        return
                    yield json.loads(fields["m"])

    async def ping(self) -> bool:
        return bool(await self.client.ping())

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    @staticmethod
    def _oldest() -> str:
        return str(int(time.time() * 1000) - KEEP_MS)


def bus_from_env() -> ValkeyBus | None:
    """The bus when VALKEY_URL is set; None means the feed goes straight to ingest."""
    url = bus_url()
    return ValkeyBus(url) if url else None
