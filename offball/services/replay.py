"""Replay builds (PRD 11.9): the real pipeline, run as fast as it goes, written out as a replay stream.

The feed goes through the live service exactly as in a live run. Each confirmed moment goes to the crew once
play has moved 8 s past it, so the crew sees how the move ended, as a broadcaster's replay would. The output is
the stream a viewer would have received, in match-time order, checked against the published contracts.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import jsonschema

from offball.agents.broadcast import Outcome, run_moment
from offball.agents.crew import Crew
from offball.mcp import tools as T
from offball.services.emitter import EmitterConfig, FeedEmitter
from offball.services.live import LiveMatch
from offball.services.state import STORE, MatchState, iso_now

ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = ROOT / "contracts"
SETTLE_MS = 8_000  # how far play moves past a moment before the crew explains it
LEAD_MS = 500  # a graphic arrives this long before it is due on screen


@dataclass
class ReplayResult:
    path: Path
    messages: int
    overlays: int
    outcomes: list[Outcome] = field(default_factory=list)
    invalid: list[str] = field(default_factory=list)


def _validators() -> dict[str, jsonschema.Draft202012Validator]:
    names = {"overlay.upsert": "overlay-upsert", "overlay.retract": "overlay-retract", "clock.sync": "clock-sync",
             "match.status": "match-status", "frame": "tracked-frame"}
    return {t: jsonschema.Draft202012Validator(json.loads((CONTRACTS / f"{n}.schema.json").read_text(encoding="utf-8")))
            for t, n in names.items()}


def check_messages(messages: list[dict]) -> list[str]:
    """Problems with any message, against the published JSON Schemas. Empty when every message is valid."""
    validators = _validators()
    problems = []
    for k, m in enumerate(messages):
        v = validators.get(m.get("type"))
        if v is None:
            problems.append(f"line {k + 1}: unknown type {m.get('type')}")
            continue
        payload = m["frame"] if m["type"] == "frame" else m
        for err in v.iter_errors(payload):
            problems.append(f"line {k + 1} ({m['type']}): {err.message}")
    return problems


async def build_replay(match_dir: Path, config: EmitterConfig, crew: Crew | None, out: Path,
                       settings: dict | None = None) -> ReplayResult:
    emitter = FeedEmitter(match_dir, config)
    match_id = emitter.match_id
    state = MatchState(match_id)
    STORE.matches[match_id] = state
    live = LiveMatch(emitter.info, state, speed=60)
    T.REGISTRY.register_live(match_id, live)
    pending: list[str] = []
    outcomes: list[Outcome] = []
    feed = list(emitter.messages())
    settings = {"min_gap_s": 20, "approval": "auto", "live": False, **(settings or {})}
    try:
        for item in feed:
            live.ingest(dict(item.msg, sent_at=iso_now()))
            if live.detection_due():
                for cand in live.detect_now():
                    state.append("candidate", cand, produced_by="interpret")
                    if cand.status == "confirmed" and cand.candidate_id not in pending:
                        pending.append(cand.candidate_id)
            if crew:
                period, now = live.clock
                for cid in list(pending):
                    c = next(x for x in live.candidates() if x.candidate_id == cid)
                    if (period, now) >= (c.period, c.t_end_ms + SETTLE_MS):
                        pending.remove(cid)
                        outcomes.append(await run_moment(crew, state, match_id, cid, settings))
        if crew:
            for cid in pending:
                outcomes.append(await run_moment(crew, state, match_id, cid, settings))
    finally:
        T.REGISTRY.unregister_live(match_id)

    # The stream a viewer would have received, in match-time order.
    timed: list[tuple[tuple[int, int], int, dict]] = []
    order = 0
    last_sync: tuple[int, int] | None = None
    seen: set[int] = set()
    for item in feed:
        m = item.msg
        if m["seq"] in seen:
            continue
        seen.add(m["seq"])
        p = m["payload"]
        if m["kind"] == "frame":
            key = (p["period"], p["t_ms"])
            timed.append((key, order, {"type": "frame", "match_id": match_id, "frame": p}))
            if last_sync is None or key[0] != last_sync[0] or key[1] - last_sync[1] >= 1000:
                last_sync = key
                timed.append((key, order + 1, {"type": "clock.sync", "match_id": match_id, "period": key[0],
                                               "t_ms": key[1], "speed": 1.0, "server_time": iso_now()}))
        elif m["kind"] == "status":
            timed.append(((p["period"], p["t_ms"]), order, {"type": "match.status", "match_id": match_id,
                                                            "status": p["status"], "period": p["period"],
                                                            "t_ms": p["t_ms"], "score": p["score"], "sent_at": iso_now()}))
        order += 2
    for o in state.live_overlays():
        timed.append(((o.period, o.t_start_ms - LEAD_MS), order, {"type": "overlay.upsert", "match_id": match_id,
                                                                  "overlay": o.model_dump(mode="json"),
                                                                  "sent_at": iso_now()}))
        order += 1
    timed.sort(key=lambda x: (x[0], x[1]))
    messages = [m for _, _, m in timed]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps(m, separators=(",", ":"), ensure_ascii=False) + "\n" for m in messages),
                   encoding="utf-8", newline="\n")
    return ReplayResult(out, len(messages), len(state.live_overlays()), outcomes, check_messages(messages))
