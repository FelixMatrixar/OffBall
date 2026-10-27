"""Whole matches for the web app's match player: the timeline, tracked frames a window at a time, every detected
moment with the graphics the crew made for it, and what-ifs from the counterfactual workers.

The player asks for frames a window at a time, so a viewer can jump anywhere in the 90 minutes. Graphics come from
the broadcast crew, never from code: `offball graphics <match>` takes every confirmed moment through the crew ahead
of time, as a replay build does (PRD 11.9), each moment seeing the match only as far as 8 s past its end. A moment
the crew hasn't explained can be sent to it when a viewer opens it, within a token budget per match. What-ifs replay
a moment in the match engine with the creator making an alternative (`offball.models.counterfactual`), and the
Tactician puts the result into words.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np

from offball.agents import tactician
from offball.agents.broadcast import Outcome, run_moment
from offball.agents.crew import Crew
from offball.contracts import Candidate
from offball.mcp import tools as T
from offball.models import counterfactual as CF
from offball.models import credit as CR
from offball.services.replay import SETTLE_MS
from offball.services.state import MatchState

log = logging.getLogger("offball.fullmatch")
GRAPHICS = T.ROOT / "replays" / "graphics"  # git ignores replays/
WHATIFS = T.ROOT / "replays" / "cache" / "whatif"
MAX_WINDOW_MS = 60_000  # the longest window one frames call returns
# A what-if is measured when the gap is used, as credit is, but never sooner than this after the moment starts, so
# a moment whose pass comes at once still has a decision to replay.
MIN_WHATIF_MS = 2500
# A whole match built ahead of time airs about a graphic a minute, as a broadcast would; viewers can ask for the rest.
BUILD_SETTINGS = {"min_gap_s": 60, "approval": "auto", "live": False}
ASKED_SETTINGS = {"min_gap_s": 0, "approval": "auto", "live": False, "requested_by_viewer": True}


# ------------------------------------------------------------------------------------------------ the timeline


def _candidates(match_id: str) -> list[Candidate]:
    return sorted(T.REGISTRY.candidates(match_id), key=lambda c: (c.period, c.t_start_ms))


def _outcome(md, c: Candidate) -> str:
    """What the moment led to: the attacking side's goal or shot within 8 s of its end, or nothing."""
    shot = next((e for e in md.events_between(c.period, c.t_start_ms, c.t_end_ms + 8000)
                 if e.type == "shot" and e.team_id == c.team_id), None)
    return "none" if shot is None else "goal" if shot.outcome == "goal" else "shot"


def timeline(match_id: str) -> dict[str, Any]:
    """Everything the match player needs before the first frame: clubs, kits, line-ups, periods, goals and every
    detected moment, with whether the crew has explained it."""
    md = T.REGISTRY.data(match_id)
    info = md.info
    built = load_graphics(match_id)["moments"]

    def club(sheet) -> dict[str, Any]:
        return {"club_id": sheet.club_id, "name": sheet.name, "short": sheet.short_name,
                "kit": sheet.kit.model_dump(mode="json") if sheet.kit else None}

    players = [{"player_id": e.player_id, "name": e.name, "number": e.number, "role": e.role,
                "club_id": sheet.club_id, "starter": e.starter}
               for sheet in (info.home, info.away) for e in sheet.lineup]
    goals = [{"event_id": e.event_id, "period": e.period, "t_ms": e.t_ms, "club_id": e.team_id,
              "player_id": e.player_id} for e in md.events if e.type == "shot" and e.outcome == "goal"]
    moments = []
    for c in _candidates(match_id):
        b = built.get(c.candidate_id, {})
        moments.append({"candidate_id": c.candidate_id, "type": c.type, "status": c.status, "period": c.period,
                        "t_start_ms": c.t_start_ms, "t_end_ms": c.t_end_ms, "club_id": c.team_id,
                        "creator_id": c.creator_id, "dragged_ids": c.dragged_ids, "receiver_id": c.receiver_id,
                        "strength": c.strength, "outcome": _outcome(md, c),
                        "graphics": b.get("status", "not_built"), "graphics_note": b.get("note", ""),
                        "whatif": CF.default_alternative(c.type)})
    return {"match_id": match_id, "home": club(info.home), "away": club(info.away),
            "periods": [p.model_dump(mode="json") for p in info.periods], "frame_rate": info.frame_rate,
            "players": players, "goals": goals, "moments": moments,
            "alternatives": list(CF.ALTERNATIVES)}


def frames(match_id: str, period: int, from_ms: int, to_ms: int) -> dict[str, Any]:
    """Tracked frames from from_ms to to_ms, at most a minute: positions in metres, 2 decimals, null off the
    pitch. `xy[k]` is [x0, y0, x1, y1, ...] in the order of `ids`."""
    md = T.REGISTRY.data(match_id)
    if period not in md.periods:
        raise ValueError(f"{match_id} has no period {period}")
    to_ms = min(to_ms, from_ms + MAX_WINDOW_MS)
    pf = md.periods[period]
    a = int(np.searchsorted(pf.t_ms, from_ms, "left"))
    b = int(np.searchsorted(pf.t_ms, to_ms, "right"))
    xy = np.round(pf.xy[a:b].reshape(b - a, -1).astype(np.float64), 2)
    rows = [[None if v != v else v for v in row] for row in xy.tolist()]
    return {"match_id": match_id, "period": period, "from_ms": from_ms, "to_ms": to_ms, "ids": md.players,
            "t": pf.t_ms[a:b].tolist(), "ball": np.round(pf.ball[a:b].astype(np.float64), 2).tolist(), "xy": rows}


# ------------------------------------------------------------------------------------------------ graphics


def _graphics_path(match_id: str) -> Path:
    return GRAPHICS / f"{match_id}.json"


def load_graphics(match_id: str) -> dict[str, Any]:
    """The graphics the crew made for a match: {"overlays": [...], "moments": {candidate_id: outcome}}."""
    path = _graphics_path(match_id)
    if not path.exists():
        return {"overlays": [], "moments": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def _save_graphics(match_id: str, data: dict[str, Any]) -> None:
    path = _graphics_path(match_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, separators=(",", ":"), ensure_ascii=False), encoding="utf-8", newline="\n")
    tmp.replace(path)


def _record(match_id: str, state: MatchState, outcome: Outcome) -> dict[str, Any]:
    """Keep a moment's outcome and its graphics, replacing whatever an earlier attempt left."""
    data = load_graphics(match_id)
    cid = outcome.candidate_id
    mine = [o.model_dump(mode="json") for o in state.live_overlays() if o.detected_moment_id == cid]
    data["overlays"] = [o for o in data["overlays"] if o.get("detected_moment_id") != cid] + mine
    pick = next((e.payload for e in reversed(state.of_kind("moment")) if e.payload.get("candidate_id") == cid), {})
    data["moments"][cid] = {"status": outcome.status, "note": outcome.note, "overlay_ids": [o["overlay_id"] for o in mine],
                            "airtime": pick.get("airtime"), "priority": pick.get("priority"),
                            "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    _save_graphics(match_id, data)
    return data["moments"][cid]


async def explain_moment(crew: Crew, state: MatchState, match_id: str, c: Candidate, settings: dict) -> Outcome:
    """One moment through the crew, seeing the match only as far as 8 s past the moment's end."""
    token = T.VIEWER_CLOCK.set((c.period, c.t_end_ms + SETTLE_MS))
    try:
        return await run_moment(crew, state, match_id, c.candidate_id, settings)
    except Exception as exc:  # the moment fails; the build goes on
        log.exception("Moment %s failed", c.candidate_id)
        return Outcome(c.candidate_id, "failed", [], f"{type(exc).__name__}: {exc}")
    finally:
        T.VIEWER_CLOCK.reset(token)


async def build_graphics(crew: Crew, match_id: str, concurrency: int = 4, limit: int | None = None,
                         redo: bool = False, tokens: int = 20_000_000, min_gap_s: int | None = None,
                         progress: Callable[[str, dict], None] | None = None) -> MatchState:
    """Take every confirmed moment of a match through the crew, in match order, a few at a time, saving after each
    one, so an interrupted build picks up where it stopped. The Scout sees what already aired, as in a live run, and
    keeps to the producer's spacing; the build stops starting moments once its token budget is spent."""
    data = load_graphics(match_id)
    state = MatchState(match_id)
    state.tokens.budget = tokens
    for cid, m in data["moments"].items():  # what earlier builds aired, for the Scout's spacing
        if m.get("airtime") is not None:
            state.append("moment", {"candidate_id": cid, "airtime": m["airtime"], "priority": m.get("priority")},
                         produced_by="scout")
    # A moment the crew failed on goes through again; one it published or kept off air doesn't, unless asked.
    done = {cid for cid, m in data["moments"].items() if m.get("status") != "failed"}
    todo = [c for c in _candidates(match_id) if c.status == "confirmed" and (redo or c.candidate_id not in done)]
    if limit is not None:
        todo = todo[:limit]
    slots = asyncio.Semaphore(concurrency)
    settings = {**BUILD_SETTINGS, **({"min_gap_s": min_gap_s} if min_gap_s is not None else {})}

    async def one(c: Candidate) -> None:
        async with slots:
            outcome = await explain_moment(crew, state, match_id, c, settings)
            kept = _record(match_id, state, outcome)
            if progress:
                progress(c.candidate_id, {**kept, "tokens": state.tokens.used})

    await asyncio.gather(*(one(c) for c in todo))
    return state


class AskedMoments:
    """Moments a viewer opened before the crew had explained them: one crew run per moment at a time, a few at once,
    within a token budget per match for the life of the process."""

    def __init__(self) -> None:
        self.states: dict[str, MatchState] = {}
        self.running: dict[tuple[str, str], asyncio.Task] = {}
        self.slots = asyncio.Semaphore(int(os.environ.get("OFFBALL_ASKED_AT_ONCE", "2")))

    def state(self, match_id: str) -> MatchState:
        if match_id not in self.states:
            s = MatchState(match_id)
            s.tokens.budget = int(os.environ.get("OFFBALL_ASKED_TOKENS", "4000000"))
            self.states[match_id] = s
        return self.states[match_id]

    async def explain(self, crew: Crew, match_id: str, candidate_id: str) -> dict[str, Any]:
        key = (match_id, candidate_id)
        if key not in self.running:
            c = T.candidate(match_id, candidate_id)
            self.running[key] = asyncio.create_task(self._run(crew, match_id, c))
        try:
            return await asyncio.shield(self.running[key])
        finally:
            if self.running.get(key) is not None and self.running[key].done():
                self.running.pop(key, None)

    async def _run(self, crew: Crew, match_id: str, c: Candidate) -> dict[str, Any]:
        async with self.slots:
            state = self.state(match_id)
            outcome = await explain_moment(crew, state, match_id, c, ASKED_SETTINGS)
            kept = _record(match_id, state, outcome)
        data = load_graphics(match_id)
        return {**kept, "overlays": [o for o in data["overlays"] if o.get("detected_moment_id") == c.candidate_id]}


ASKED = AskedMoments()


# ------------------------------------------------------------------------------------------------ what-ifs


def _whatif_path(match_id: str, candidate_id: str, option: str) -> Path:
    match_dir = T.REGISTRY.match_dirs()[match_id]
    manifest = match_dir / "manifest.json"
    digest = hashlib.sha256((manifest.read_bytes() if manifest.exists() else b"")
                            + Path(CF.__file__).read_bytes()).hexdigest()[:12]
    return WHATIFS / match_id / f"{candidate_id}-{option}-{digest}.json"


def _dist(a, b) -> float:
    return round(float(np.hypot(a[0] - b[0], a[1] - b[1])), 1)


def whatif(match_id: str, candidate_id: str, option: str) -> dict[str, Any]:
    """Replay a moment with its creator making the alternative: the measured difference, the median paths of the
    players who were free to react, and where the gap is. Cached on disk."""
    if option not in CF.ALTERNATIVES:
        raise ValueError(f"Unknown alternative {option}; the alternatives are {', '.join(CF.ALTERNATIVES)}")
    path = _whatif_path(match_id, candidate_id, option)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    md = T.REGISTRY.data(match_id)
    c = T.candidate(match_id, candidate_id)
    started = time.monotonic()
    t_m = max(CR.measure_instant(md, c.team_id, c.period, c.t_start_ms, c.t_end_ms, c.receiver_id),
              min(c.t_start_ms + MIN_WHATIF_MS, c.t_end_ms))
    cf = CF.counterfactual(md, c.type, c.team_id, c.creator_id, c.dragged_ids, c.period, c.t_start_ms, t_m,
                           c.gap_zone, instead_kind=option)
    pf = md.periods[c.period]
    b = pf.index_of(t_m)
    numbers: dict[str, Any] = {
        "space_created_m2": cf.space_created_m2, "space_lo_m2": cf.space_interval_m2[0],
        "space_hi_m2": cf.space_interval_m2[1], "gap_open_pct_without": round(100 * cf.gap_open_rate_without),
        "replays": cf.replays,
    }
    for pid, track in cf.ghosts.items():
        real = pf.xy[b, md.players.index(pid)]
        name = "creator_shift_m" if pid == c.creator_id else f"defender_shift_m.{pid}"
        numbers[name] = _dist(track[-1][1:], real)
    xs, ys = [p[0] for p in c.gap_zone], [p[1] for p in c.gap_zone]
    out = {"match_id": match_id, "candidate_id": candidate_id, "option_id": option,
           "counterfactual_id": f"{candidate_id}-cf-{option}", "period": c.period, "t_start_ms": cf.t_start_ms,
           "t_measure_ms": t_m, "numbers": numbers, "threat": [cf.threat_created, *cf.threat_interval],
           "tracks": {pid: [list(p) for p in track] for pid, track in cf.ghosts.items()},
           "ring": {"at": [round((min(xs) + max(xs)) / 2, 1), round((min(ys) + max(ys)) / 2, 1)],
                    "rx_m": round((max(xs) - min(xs)) / 2, 1), "ry_m": round((max(ys) - min(ys)) / 2, 1),
                    "open": cf.gap_open_rate_without > 0.5},
           "elapsed_ms": round((time.monotonic() - started) * 1000)}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8", newline="\n")
    return out


async def whatif_words(crew: Crew, match_id: str, candidate_id: str, option: str) -> dict[str, Any] | None:
    """The Tactician's words for a what-if, cached beside its numbers. None when it couldn't give faithful ones."""
    result = await asyncio.to_thread(whatif, match_id, candidate_id, option)
    path = _whatif_path(match_id, candidate_id, option).with_suffix(".words.json")
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    c = T.candidate(match_id, candidate_id)
    token = T.VIEWER_CLOCK.set((c.period, c.t_end_ms + SETTLE_MS))
    try:
        card = T.moment_card(match_id, candidate_id)
    finally:
        T.VIEWER_CLOCK.reset(token)
    out = await tactician.explain(crew, card, option, result["numbers"])
    if out is None:
        return None
    words = {"headline": out.headline.model_dump(), "plain": out.plain.model_dump(),
             "analyst": out.analyst.model_dump(), "ai_generated": True}
    path.write_text(json.dumps(words, ensure_ascii=False, separators=(",", ":")), encoding="utf-8", newline="\n")
    return words
