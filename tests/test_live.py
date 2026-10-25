"""The emitter and the live service, on the 27 s around the showcase goal (no model needed)."""

from __future__ import annotations

import numpy as np
import pytest

from offball.services.emitter import EmitterConfig, FeedEmitter
from offball.services.live import LiveMatch
from offball.services.state import MatchState

from .conftest import GOAL_WINDOW


@pytest.fixture(scope="module")
def feed(m07):
    em = FeedEmitter(m07, EmitterConfig(**GOAL_WINDOW, duplicate_rate=0.05, late_rate=0.05))
    return em, list(em.messages())


def play(em, msgs):
    state = MatchState(em.match_id)
    q = state.subscribe(maxsize=100_000)
    live = LiveMatch(em.info, state)
    found = []
    for m in msgs:
        live.ingest(m.msg)
        if live.detection_due():
            found += live.detect_now()
    out = []
    while not q.empty():
        out.append(q.get_nowait())
    return live, found, out


def test_emitter_sends_in_order_with_faults(feed) -> None:
    em, msgs = feed
    due = [m.due_ms for m in msgs]
    assert due == sorted(due)
    seqs = [m.msg["seq"] for m in msgs]
    assert len(seqs) > len(set(seqs)), "duplicates are part of the feed"
    kinds = {m.msg["kind"] for m in msgs}
    assert kinds == {"status", "frame", "event"}
    frames = [m.msg["payload"] for m in msgs if m.msg["kind"] == "frame"]
    assert all(20 <= len(f["players"]) <= 22 for f in frames), "only players on the pitch; a red card leaves 21"
    assert frames[0]["t_ms"] == GOAL_WINDOW["from_ms"]


def test_live_dedupes_and_relays(feed) -> None:
    em, msgs = feed
    live, _, out = play(em, msgs)
    unique_frames = {m.msg["seq"] for m in msgs if m.msg["kind"] == "frame"}
    assert sum(1 for m in out if m["type"] == "frame") == len(unique_frames)
    assert any(m["type"] == "clock.sync" for m in out)
    statuses = [m for m in out if m["type"] == "match.status"]
    assert statuses[-1]["score"]["kes"] == statuses[0]["score"]["kes"] + 1, "the goal reaches the score"
    events = live.events
    assert [(e.period, e.t_ms) for e in events] == sorted((e.period, e.t_ms) for e in events)


def test_live_finds_the_decoy_run(feed) -> None:
    em, msgs = feed
    live, found, _ = play(em, msgs)
    # Other detectors find other moments in the build-up too (a run can be a decoy and a blind-side run at once);
    # the planted decoy run is found once.
    confirmed = [c for c in live.candidates() if c.status == "confirmed" and c.type == "decoy_run"]
    assert len(confirmed) == 1
    c = confirmed[0]
    assert (c.type, c.creator_id, c.dragged_ids, c.receiver_id) == ("decoy_run", "kes-09", ["ash-05"], "kes-10")
    assert abs(c.t_start_ms - 1_081_360) <= 200


def test_gaps_are_filled(m07) -> None:
    em = FeedEmitter(m07, EmitterConfig(**GOAL_WINDOW, faults=True, frame_drop_rate=0.05, duplicate_rate=0,
                                        late_rate=0))
    live, _, _ = play(em, list(em.messages()))
    pf = live.data().periods[2]
    window = pf.xy[GOAL_WINDOW["from_ms"] // 40: GOAL_WINDOW["to_ms"] // 40]
    assert not np.isnan(window[:, live.players.index("kes-09")]).any()
