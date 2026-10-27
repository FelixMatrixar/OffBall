"""The OffBall MCP tools (PRD 14.8): what agents read about a match, and the numbers they may quote.

Every tool works on observed data only (tracking, events, candidates), never on the held-out truth. During a
live match, a tool refuses to read past the live clock, so no agent can see what hasn't happened yet. The same
functions back the MCP server and the agents' in-process tools, so both transports answer identically.
"""

from __future__ import annotations

import hashlib
import json
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from offball.contracts import Candidate, Event
from offball.core import FRAME_MS, clock_label, parse_event_ref, parse_frame_ref
from offball.models import metrics
from offball.models.candidates import detect
from offball.models.match_data import MatchData

ROOT = Path(__file__).resolve().parents[2]
DATASETS = ROOT / "datasets"
CANDIDATE_CACHE = ROOT / "replays" / "cache" / "candidates"  # git ignores replays/
DETECTORS = [ROOT / "offball" / "models" / name for name in ("candidates.py", "candidates_extra.py", "runs.py",
                                                              "pitch_control.py", "metrics.py", "match_data.py")]
LOCALES = ROOT / "offball" / "agents" / "locales"
LOCALE_CODES = ("en", "es", "pt", "fr", "ar", "hi", "id", "zh", "ja", "sw")


class LiveView(Protocol):
    """A match being played: the data observed so far, the live clock and the candidates found so far."""

    def data(self) -> MatchData: ...

    @property
    def clock(self) -> tuple[int, int]: ...

    def candidates(self) -> list[Candidate]: ...


@dataclass
class Registry:
    """Matches the tools can see: finished matches from the datasets folder, and live matches as they play."""

    roots: list[Path] = field(default_factory=lambda: [DATASETS])
    _done: dict[str, MatchData] = field(default_factory=dict)
    _done_candidates: dict[str, list[Candidate]] = field(default_factory=dict)
    _live: dict[str, LiveView] = field(default_factory=dict)

    def match_dirs(self) -> dict[str, Path]:
        out: dict[str, Path] = {}
        for root in self.roots:
            for info in sorted(root.glob("*/*/match.json")):
                out[info.parent.name] = info.parent
        return out

    def register_live(self, match_id: str, view: LiveView) -> None:
        self._live[match_id] = view

    def unregister_live(self, match_id: str) -> None:
        self._live.pop(match_id, None)

    def is_live(self, match_id: str) -> bool:
        return match_id in self._live

    def data(self, match_id: str) -> MatchData:
        if match_id in self._live:
            return self._live[match_id].data()
        if match_id not in self._done:
            dirs = self.match_dirs()
            if match_id not in dirs:
                raise ValueError(f"Unknown match {match_id}")
            self._done[match_id] = MatchData.load(dirs[match_id])
        return self._done[match_id]

    def live_clock(self, match_id: str) -> tuple[int, int] | None:
        view = self._live.get(match_id)
        return view.clock if view else None

    def candidates(self, match_id: str) -> list[Candidate]:
        if match_id in self._live:
            return self._live[match_id].candidates()
        if match_id not in self._done_candidates:
            self._done_candidates[match_id] = self._cached_candidates(match_id)
        return self._done_candidates[match_id]

    def _cached_candidates(self, match_id: str) -> list[Candidate]:
        """A finished match's candidates, from the disk cache when the match files and the detectors are unchanged.
        Detecting a whole match takes minutes, which a fan's first question shouldn't wait for."""
        match_dir = self.match_dirs().get(match_id)
        manifest = match_dir / "manifest.json" if match_dir else None
        if manifest is None or not manifest.exists():
            return detect(self.data(match_id))
        digest = hashlib.sha256(manifest.read_bytes())
        for src in DETECTORS:
            digest.update(src.read_bytes())
        key = digest.hexdigest()
        path = CANDIDATE_CACHE / f"{match_id}.json"
        if path.exists():
            cached = json.loads(path.read_text(encoding="utf-8"))
            if cached.get("key") == key:
                return [Candidate.model_validate(c) for c in cached["candidates"]]
        found = detect(self.data(match_id))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"key": key, "candidates": [c.model_dump(mode="json") for c in found]},
                                   separators=(",", ":")), encoding="utf-8", newline="\n")
        return found


REGISTRY = Registry()
# Where the viewer is in a replay, while answering their question: tools then refuse to look past it too.
VIEWER_CLOCK: ContextVar[tuple[int, int] | None] = ContextVar("viewer_clock", default=None)


# ------------------------------------------------------------------------------------------------ helpers


def _now(match_id: str) -> tuple[int, int] | None:
    clocks = [c for c in (REGISTRY.live_clock(match_id), VIEWER_CLOCK.get()) if c is not None]
    return min(clocks) if clocks else None


def _guard(match_id: str, period: int, t_ms: int) -> None:
    clock = _now(match_id)
    if clock is not None and (period, t_ms) > clock:
        raise ValueError(f"Period {period} at {clock_label(period, t_ms)} hasn't happened yet for this viewer; "
                         f"the match clock is at {clock_label(*clock)}")


def _lineups(md: MatchData) -> dict[str, dict[str, Any]]:
    out = {}
    for sheet in (md.info.home, md.info.away):
        for entry in sheet.lineup:
            out[entry.player_id] = {"player_id": entry.player_id, "name": entry.name, "number": entry.number,
                                    "role": entry.role, "club_id": sheet.club_id, "club": sheet.name}
    return out


def _player(md: MatchData, pid: str | None) -> dict[str, Any] | None:
    return _lineups(md).get(pid) if pid else None


def _score_at(md: MatchData, period: int, t_ms: int) -> dict[str, int]:
    score = {md.home: 0, md.away: 0}
    for e in md.events:
        if (e.period, e.t_ms) > (period, t_ms):
            break
        if e.type == "shot" and e.outcome == "goal" and e.team_id in score:
            score[e.team_id] += 1
    return score


def _event_dict(e: Event) -> dict[str, Any]:
    return e.model_dump(mode="json", exclude_none=True, exclude={"schema_version"})


def _frame_t(ref: str) -> tuple[int, int] | None:
    parsed = parse_frame_ref(ref)
    return (parsed[1], parsed[2] * FRAME_MS) if parsed else None


def _round_xy(xy: Any) -> list[float]:
    return [round(float(xy[0]), 1), round(float(xy[1]), 1)]


def _position(md: MatchData, period: int, t_ms: int, pid: str) -> list[float] | None:
    pf = md.periods[period]
    xy = pf.xy[pf.index_of(t_ms), md.players.index(pid)]
    return None if np.isnan(xy).any() else _round_xy(xy)


# ------------------------------------------------------------------------------------------------ tools


def list_matches() -> list[dict[str, Any]]:
    """Every match OffBall can talk about, with its clubs and whether it is being played live now."""
    out = []
    for match_id, path in REGISTRY.match_dirs().items():
        info = json.loads((path / "match.json").read_text(encoding="utf-8"))
        out.append({"match_id": match_id, "home": info["home"]["name"], "away": info["away"]["name"],
                    "round": info.get("round"), "live": REGISTRY.is_live(match_id), "set": path.parent.name})
    return out


def match_facts(match_id: str) -> dict[str, Any]:
    """Clubs, line-ups (name, shirt number, role), attacking direction per period, and the score so far."""
    md = REGISTRY.data(match_id)
    clock = _now(match_id)
    period, t_ms = clock if clock else (max(md.periods), int(md.periods[max(md.periods)].t_ms[-1]))
    return {
        "match_id": match_id,
        "home": {"club_id": md.home, "name": md.info.home.name, "formation": md.info.home.formation},
        "away": {"club_id": md.away, "name": md.info.away.name, "formation": md.info.away.formation},
        "players": list(_lineups(md).values()),
        "attacks_left_to_right": {p.period: p.attacks_left_to_right for p in md.info.periods},
        "clock": {"period": period, "t_ms": t_ms, "label": clock_label(period, t_ms)},
        "score": _score_at(md, period, t_ms),
        "live": clock is not None,
    }


def list_metrics() -> list[dict[str, Any]]:
    """The named metrics compute_metric can calculate, with their units and parameters."""
    return metrics.catalogue()


def compute_metric(match_id: str, name: str, params: dict[str, Any]) -> dict[str, Any]:
    """Calculate one named metric exactly, from the match data. Quote numbers only from results of this tool."""
    period = params.get("period")
    t = params.get("t_end_ms", params.get("t_ms"))
    if period is not None and t is not None:
        _guard(match_id, int(period), int(t))
    md = REGISTRY.data(match_id)
    return metrics.compute(md, name, **params).as_dict()


def list_candidates(match_id: str, period: int | None = None, since_ms: int | None = None) -> list[dict[str, Any]]:
    """Moments the interpret service has found: type, players, signal strengths and status."""
    out = []
    now = _now(match_id)
    for c in REGISTRY.candidates(match_id):
        if period is not None and c.period != period:
            continue
        if now is not None and (c.period, c.t_end_ms) > now:
            continue  # not over yet for this viewer
        if since_ms is not None and c.t_start_ms < since_ms:
            continue
        out.append({"candidate_id": c.candidate_id, "type": c.type, "period": c.period, "t_start_ms": c.t_start_ms,
                    "t_end_ms": c.t_end_ms, "clock": clock_label(c.period, c.t_start_ms), "team_id": c.team_id,
                    "creator_id": c.creator_id, "dragged_ids": c.dragged_ids, "receiver_id": c.receiver_id,
                    "strength": c.strength, "status": c.status, "space_created_m2": c.space_created_m2})
    return out


def candidate(match_id: str, candidate_id: str) -> Candidate:
    for c in REGISTRY.candidates(match_id):
        if c.candidate_id == candidate_id:
            return c
    raise ValueError(f"Unknown candidate {candidate_id} in {match_id}")


def moment_card(match_id: str, candidate_id: str) -> dict[str, Any]:
    """Everything known about one moment: who, when, the signals with their evidence, the beats of the play and
    the pitch positions graphics can be anchored to."""
    md = REGISTRY.data(match_id)
    c = candidate(match_id, candidate_id)
    period = c.period
    _guard(match_id, period, c.t_start_ms)
    sig = {s.name: s for s in c.signals}
    beats = [{"key": "run_start", "t_ms": c.t_start_ms, "evidence_ids": [md.frame_id(period, c.t_start_ms)]}]
    disp = sig.get("defender_displacement_m")
    if disp and len(disp.evidence_ids) > 1 and (ft := _frame_t(disp.evidence_ids[1])):
        beats.append({"key": "defender_follows", "t_ms": ft[1], "evidence_ids": [disp.evidence_ids[1]]})
    gain = sig.get("zone_control_gain_pts")
    if gain and gain.evidence_ids and (ft := _frame_t(gain.evidence_ids[0])):
        beats.append({"key": "gap_opens", "t_ms": ft[1], "evidence_ids": gain.evidence_ids})
    pass_sig = sig.get("pass_into_gap")
    pass_ev = None
    if pass_sig and pass_sig.evidence_ids:
        pass_ev = next((e for e in md.events if e.event_id == pass_sig.evidence_ids[0]), None)
    finish = None
    if pass_ev:
        beats.append({"key": "pass_into_gap", "t_ms": pass_ev.t_ms, "evidence_ids": [pass_ev.event_id]})
        finish = next((e for e in md.events if e.period == period and e.type == "shot" and e.team_id == c.team_id
                       and pass_ev.t_ms <= e.t_ms <= pass_ev.t_ms + 8000), None)
        if finish:
            beats.append({"key": "goal" if finish.outcome == "goal" else "shot", "t_ms": finish.t_ms,
                          "evidence_ids": [finish.event_id]})
    beats.sort(key=lambda b: b["t_ms"])
    zone = c.gap_zone
    xs, ys = [p[0] for p in zone], [p[1] for p in zone]
    anchors: dict[str, Any] = {}
    # Only a moment with a run has a run to draw: a pin, a screen or a press has no run arrow (the Producer plans
    # from the anchors it is given, and publish rejects one without coordinates).
    if c.run_from and c.run_to:
        anchors["run"] = {"player_id": c.creator_id, "from_xy": list(c.run_from), "to_xy": list(c.run_to)}
    anchors["gap"] = {"centre_xy": [round((min(xs) + max(xs)) / 2, 1), round((min(ys) + max(ys)) / 2, 1)],
                      "rx_m": round((max(xs) - min(xs)) / 2, 1), "ry_m": round((max(ys) - min(ys)) / 2, 1),
                      "polygon": [list(p) for p in zone]}
    if c.dragged_ids:
        follow_t = next((b["t_ms"] for b in beats if b["key"] == "defender_follows"), c.t_end_ms)
        anchors["defender"] = {"player_id": c.dragged_ids[0], "from_xy": _position(md, period, c.t_start_ms, c.dragged_ids[0]),
                               "to_xy": _position(md, period, follow_t, c.dragged_ids[0])}
    if pass_ev and pass_ev.start_xy and pass_ev.end_xy:
        anchors["pass"] = {"from_xy": list(pass_ev.start_xy), "to_xy": list(pass_ev.end_xy),
                           "player_ids": [pass_ev.player_id, pass_ev.recipient_id], "event_id": pass_ev.event_id}
    attacking = c.team_id
    outcome = "chance" if pass_ev else "none"
    if finish:
        outcome = "goal" if finish.outcome == "goal" else "shot"
    return {
        "candidate_id": c.candidate_id,
        "match_id": match_id,
        "type": c.type,
        "status": c.status,
        "strength": c.strength,
        "period": period,
        "clock": clock_label(period, c.t_start_ms),
        "t_start_ms": c.t_start_ms,
        "t_end_ms": c.t_end_ms,
        "score_before": _score_at(md, period, c.t_start_ms - 1),
        "attacking": {"club_id": attacking, "club": md.club_name(attacking),
                      "direction": "left to right" if md.direction(period, attacking) > 0 else "right to left"},
        "defending": {"club_id": md.other(attacking), "club": md.club_name(md.other(attacking))},
        "creator": _player(md, c.creator_id),
        "dragged": [_player(md, pid) for pid in c.dragged_ids],
        "passer": _player(md, pass_ev.player_id) if pass_ev else None,
        "receiver": _player(md, c.receiver_id),
        "outcome": outcome,
        "signals": [s.model_dump(mode="json") for s in c.signals],
        "space_created_m2": c.space_created_m2,
        "beats": beats,
        "anchors": anchors,
        "evidence_ids": c.evidence_ids,
    }


def events_between(match_id: str, period: int, t_from_ms: int, t_to_ms: int) -> list[dict[str, Any]]:
    """Ball events in a time range of one period: passes, carries, shots, duels, restarts."""
    _guard(match_id, period, t_to_ms)
    md = REGISTRY.data(match_id)
    return [_event_dict(e) for e in md.events_between(period, t_from_ms, t_to_ms)]


def positions_at(match_id: str, period: int, t_ms: int) -> dict[str, Any]:
    """Where every player on the pitch and the ball are at an instant, with each player's speed in km/h."""
    _guard(match_id, period, t_ms)
    md = REGISTRY.data(match_id)
    pf = md.periods[period]
    i = pf.index_of(t_ms)
    people = _lineups(md)
    players = []
    for col, pid in enumerate(md.players):
        xy = pf.xy[i, col]
        if np.isnan(xy).any():
            continue
        speed = pf.speed[i, col]
        players.append({**people.get(pid, {"player_id": pid}), "xy": _round_xy(xy),
                        "speed_kmh": None if np.isnan(speed) else round(float(speed) * 3.6, 1)})
    return {"period": period, "t_ms": int(pf.t_ms[i]), "clock": clock_label(period, int(pf.t_ms[i])),
            "frame_id": md.frame_id(period, int(pf.t_ms[i])), "ball": [round(float(v), 2) for v in pf.ball[i]],
            "players": players}


def get_evidence(match_id: str, ids: list[str]) -> dict[str, Any]:
    """Resolve event and frame IDs into the data they point at."""
    md = REGISTRY.data(match_id)
    out: dict[str, Any] = {}
    for ref in ids:
        if parse_event_ref(ref):
            ev = next((e for e in md.events if e.event_id == ref), None)
            if ev is not None:
                _guard(match_id, ev.period, ev.t_ms)
            out[ref] = _event_dict(ev) if ev else {"error": "unknown event"}
        elif (ft := _frame_t(ref)) and ft[0] in md.periods:
            out[ref] = positions_at(match_id, ft[0], ft[1])
        else:
            out[ref] = {"error": "not an event or frame ID of this match"}
    return out


def player_summary(match_id: str, player_id: str, period: int | None = None, t_ms: int | None = None) -> dict[str, Any]:
    """A player's off-ball and physical work so far: moments created, defenders dragged, distance and sprints."""
    md = REGISTRY.data(match_id)
    clock = _now(match_id)
    if clock and period is None:
        period, t_ms = clock
    params = {"player_id": player_id, "period": period, "t_end_ms": t_ms}
    created = [c for c in REGISTRY.candidates(match_id)
               if c.creator_id == player_id and (period is None or (c.period, c.t_start_ms) <= (period, t_ms or 0))]
    return {
        "player": _player(md, player_id),
        "distance_km": metrics.compute(md, "distance_covered_km", **params).as_dict(),
        "sprints": metrics.compute(md, "sprints", **params).as_dict(),
        "moments_created": [{"candidate_id": c.candidate_id, "type": c.type, "clock": clock_label(c.period, c.t_start_ms),
                             "space_created_m2": c.space_created_m2, "dragged_ids": c.dragged_ids} for c in created],
    }


def glossary(lang: str = "en") -> dict[str, str]:
    """The football terms OffBall uses in one language (en, es, pt, fr, ar, hi, id, zh, ja or sw), keyed the same in
    every language, so every agent names ideas the same way."""
    path = LOCALES / f"{lang}.json"
    if lang not in LOCALE_CODES or not path.exists():
        raise ValueError(f"No glossary for {lang!r}; languages: {', '.join(LOCALE_CODES)}")
    return json.loads(path.read_text(encoding="utf-8"))["glossary"]


READ_TOOLS = [list_matches, match_facts, list_metrics, compute_metric, list_candidates, moment_card, events_between,
              positions_at, get_evidence, player_summary, glossary]
