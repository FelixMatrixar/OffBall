"""Golden render tests for the AI pipeline (PRD 19.5).

Each case is a stretch of a generated match around one planted moment. Its input is the feed the pipeline reads,
`datasets/golden/<case>/feed.jsonl`: every frame, event and status message of the stretch, in send order. Its
expectations, `truth/golden/<case>/expected.json`, are built from the answer key and the data, and say what the
stream the pipeline sends the frontend (INTEGRATION.md section 4) must hold. `check` scores an output stream
against them:

- every message valid against the contracts the frontend reads, for this match;
- frames that carry the tracking as it is, kept alive by `clock.sync`, with the score right;
- each planted moment aired: a caption in English in every mode, its graphics on the right players and places,
  every graphic citing evidence from the moment, held long enough to read and sent in time to be seen;
- no null moment aired as its parent;
- no more pitch graphics at a time than each mode allows, and every graphic labelled as AI-generated on synthetic
  data.

The wording is the AI's own and isn't judged here; the Fact-checker and the evaluations in 14.15 do that. Moments
the pipeline airs that the answer key doesn't label are counted, not failed: the players make moments of their own.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np

from offball.core import FRAME_MS, parse_event_ref, parse_frame_ref
from offball.models.match_data import MatchData

ROOT = Path(__file__).resolve().parents[2]
DATASETS, TRUTH = ROOT / "datasets", ROOT / "truth"
MODES = ("casual", "learn", "analyst", "player", "audio", "broadcaster")
PAD_MS = 12_000  # the stretch of play kept either side of the case's moment
PATH_STEP_MS = 500  # how finely a run's path is kept
EPOCH_S = 1_792_857_600.0  # the feed's send times start at 2026-10-24T15:00:00Z
LIVE_BUFFER_MS = 1500  # how far behind the newest data live viewers watch
NULL_PARENT = {"null_run": "decoy_run", "null_overlap": "overlap"}
RUN_TYPES = {"decoy_run", "overlap", "underlap", "third_man_run", "blind_side_run", "timed_run_in_behind",
             "false_9_drop"}
GAP_TYPES = RUN_TYPES | {"switch_of_play", "press_broken"}  # moments that open space a ring can show
PITCH_KINDS = {"gap_ring", "run_arrow", "pass_line", "ghost"}  # the graphics a mode's density limit counts
DENSITY = {"casual": 1, "learn": 1, "analyst": 4}  # pitch graphics at a time (PRD 15.2)
TOLERANCE = {"timing_ms": 3000, "hold_ms": 2500, "anchor_m": 3.0, "gap_m": 5.0, "run_min_m": 4.0,
             "number_m": 1.0, "frame_m": 0.1, "frame_coverage": 0.95, "clock_gap_ms": 1500,
             "score_before_ms": 500, "score_after_ms": 3000, "evidence_before_ms": 5000, "evidence_after_ms": 8000}

# name -> (set, match id, moment type, outcome or None): the planted moment the case is built around.
CASES: dict[str, tuple[str, str, str, str | None]] = {
    "showcase-goal": ("showcase", "m07", "decoy_run", "goal"),
    "showcase-null-run": ("showcase", "m07", "null_run", None),
    "overlap": ("smoke", "smk4", "overlap", None),
    "null-overlap": ("smoke", "smk5", "null_overlap", None),
    "third-man-run": ("smoke", "smk8", "third_man_run", None),
    "switch-of-play": ("smoke", "smk9", "switch_of_play", None),
    "press-broken": ("smoke", "smk10", "press_broken", None),
    "cover-shadow": ("smoke", "smk15", "cover_shadow", None),
}


# ------------------------------------------------------------------------------------------------ building


def build(names: list[str] | None = None, data_root: Path = DATASETS, truth_root: Path = TRUTH) -> list[str]:
    """Write each case's input feed and expectations. Returns the cases written."""
    written = []
    for name in names or list(CASES):
        set_name, match_id, kind, outcome = CASES[name]
        match_dir = DATASETS / set_name / match_id
        md = MatchData.load(match_dir)
        key = json.loads((TRUTH / set_name / match_id / "answer_key.json").read_text(encoding="utf-8"))
        anchor = next(r for r in key if r["type"] == kind and (outcome is None or r.get("outcome") == outcome))
        period = anchor["period"]
        window = {"from_ms": max(anchor["t_start_ms"] - PAD_MS, 0),
                  "to_ms": min(anchor["t_end_ms"] + PAD_MS, int(md.periods[period].t_ms[-1]))}
        moments = [_expect(md, r) for r in key if r["period"] == period
                   and r["t_end_ms"] >= window["from_ms"] and r["t_start_ms"] <= window["to_ms"]]
        case = {"case": name, "set": set_name, "match_id": match_id, "home": md.home, "away": md.away,
                "period": period, **window}
        expected = {**case, "modes": list(MODES), "tolerance": TOLERANCE, "moments": moments,
                    "score": _score(md, period, window)}
        out = data_root / "golden" / name
        out.mkdir(parents=True, exist_ok=True)
        _write(out / "case.json", case)
        _feed(match_dir, case, out / "feed.jsonl")
        _write(truth_root / "golden" / name / "expected.json", expected)
        written.append(name)
    return written


def _write(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=1) + "\n", encoding="utf-8", newline="\n")


def _feed(match_dir: Path, case: dict, path: Path) -> int:
    """The stretch as the feed sends it, with no faults, stamped with send times from a fixed start."""
    from offball.services.emitter import EmitterConfig, FeedEmitter, _iso

    em = FeedEmitter(match_dir, EmitterConfig(period=case["period"], from_ms=case["from_ms"], to_ms=case["to_ms"],
                                              faults=False))
    n = 0
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        for item in em.messages():
            fh.write(json.dumps(dict(item.msg, sent_at=_iso(EPOCH_S + item.due_ms / 1000)),
                                separators=(",", ":")) + "\n")
            n += 1
    return n


def _expect(md: MatchData, row: dict) -> dict:
    """What the stream must show for one labelled moment, read from the data."""
    period, kind = row["period"], row["type"]
    pf = md.periods[period]
    out: dict[str, Any] = {"moment_id": row["moment_id"], "type": kind, "source": row["source"],
                           "t_start_ms": row["t_start_ms"], "t_end_ms": row["t_end_ms"], "team_id": row["team_id"],
                           "creator_id": row["creator_id"], "dragged_ids": row.get("dragged_ids") or [],
                           "receiver_id": row.get("receiver_id")}
    zone = row.get("gap_zone") or []
    if zone:
        pts = np.array(zone, dtype=float)
        centre = pts.mean(axis=0)
        out["gap"] = {"centre_xy": _xy(centre),
                      "radius_m": round(float(np.linalg.norm(pts - centre, axis=1).max()), 1)}
    if kind in RUN_TYPES or kind in NULL_PARENT:
        col = md.players.index(row["creator_id"])
        ts = range(row["t_start_ms"] - 1000, row["t_end_ms"] + 1, PATH_STEP_MS)
        out["run"] = {"path": [[t, *_xy(pf.xy[pf.index_of(t), col])] for t in ts
                               if not np.isnan(pf.xy[pf.index_of(t), col, 0])]}
    if row.get("is_null"):
        out["must_air"] = False
        out["parent"] = NULL_PARENT.get(kind, kind)
        return out
    out["must_air"] = row["source"] == "planted"  # moments the oracle labelled may air
    out["required_kinds"] = ["caption"] + (["run_arrow"] if kind in RUN_TYPES else []) + \
        (["gap_ring"] if kind in GAP_TYPES and zone else [])
    receiver = row.get("receiver_id")
    passes = [e for e in md.events_between(period, row["t_start_ms"], row["t_end_ms"] + 3000)
              if e.type == "pass" and receiver and e.recipient_id == receiver and e.player_id != receiver]
    if passes:
        p = passes[0]
        out["pass"] = {"event_id": p.event_id, "t_ms": p.t_ms, "player_ids": [p.player_id, receiver],
                       "distance_m": round(float(np.hypot(*np.subtract(p.end_xy, p.start_xy))), 1)}
    return out


def _xy(p) -> list[float]:
    return [round(float(p[0]), 2), round(float(p[1]), 2)]


def _score(md: MatchData, period: int, window: dict) -> dict:
    """The score as the stretch opens, and every change within it: from the scoring shot until the ball is in."""
    score = {md.home: 0, md.away: 0}
    changes = []
    for e in sorted(md.events, key=lambda e: (e.period, e.t_ms)):
        if e.type != "shot" or e.outcome != "goal":
            continue
        if (e.period, e.t_ms) < (period, window["from_ms"]):
            score[e.team_id] += 1
        elif e.period == period and e.t_ms <= window["to_ms"]:
            after = dict(changes[-1]["score"]) if changes else dict(score)
            after[e.team_id] += 1
            changes.append({"shot_ms": e.t_ms, "in_ms": _ball_in(md, period, e.team_id, e.t_ms), "score": after})
    return {"at_start": score, "changes": changes}


def _ball_in(md: MatchData, period: int, club: str, from_ms: int) -> int:
    """When the ball crosses the goal line the club attacks, after `from_ms`."""
    pf = md.periods[period]
    goal_x = 105.0 if md.direction(period, club) > 0 else 0.0
    for i in range(pf.index_of(from_ms), pf.n):
        if (pf.ball[i, 0] - goal_x) * (1 if goal_x > 0 else -1) >= 0:
            return int(pf.t_ms[i])
    return from_ms


# ------------------------------------------------------------------------------------------------ checking


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""


@dataclass
class Report:
    case: str
    checks: list[Check] = field(default_factory=list)
    unlabelled_moments: int = 0

    @property
    def passed(self) -> bool:
        return all(c.ok for c in self.checks)

    def add(self, name: str, ok: bool, detail: str = "") -> None:
        self.checks.append(Check(name, bool(ok), detail))

    def to_dict(self) -> dict:
        return {"case": self.case, "passed": self.passed, "unlabelled_moments": self.unlabelled_moments,
                "checks": [c.__dict__ for c in self.checks]}

    def text(self) -> str:
        lines = [f"{self.case}: {'pass' if self.passed else 'FAIL'} "
                 f"({sum(c.ok for c in self.checks)}/{len(self.checks)} checks)"]
        lines += [f"  {'ok  ' if c.ok else 'FAIL'} {c.name}{': ' + c.detail if c.detail and not c.ok else ''}"
                  for c in self.checks]
        if self.unlabelled_moments:
            lines.append(f"  note: {self.unlabelled_moments} moment(s) aired that the answer key doesn't label")
        return "\n".join(lines)


def load_case(name: str, truth_root: Path = TRUTH) -> dict:
    return json.loads((truth_root / "golden" / name / "expected.json").read_text(encoding="utf-8"))


def load_stream(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def run(name: str, crew, out: Path) -> Report:
    """Put the case's stretch through the pipeline (`offball replay`, with no feed faults) and check what comes out."""
    import asyncio

    from offball.services.emitter import EmitterConfig
    from offball.services.replay import build_replay

    exp = load_case(name)
    config = EmitterConfig(period=exp["period"], from_ms=exp["from_ms"], to_ms=exp["to_ms"], faults=False)
    asyncio.run(build_replay(DATASETS / exp["set"] / exp["match_id"], config, crew, out))
    return check(exp, load_stream(out))


@lru_cache(maxsize=4)
def _match_data(set_name: str, match_id: str) -> MatchData:
    return MatchData.load(DATASETS / set_name / match_id)


def check(exp: dict, messages: list[dict]) -> Report:
    """Score a pipeline's output stream for one case against its expectations."""
    tol = exp["tolerance"]
    md = _match_data(exp["set"], exp["match_id"])
    report = Report(exp["case"])
    _check_contracts(report, exp, messages)
    _check_frames(report, exp, md, messages, tol)
    _check_clock(report, exp, messages, tol)
    _check_score(report, exp, messages, tol)

    latest: dict[str, dict] = {}
    for m in messages:
        o = m.get("overlay") if m.get("type") == "overlay.upsert" else None
        if not isinstance(o, dict) or "overlay_id" not in o:
            continue
        if o["overlay_id"] not in latest or o.get("rev", 0) > latest[o["overlay_id"]].get("rev", 0):
            latest[o["overlay_id"]] = o
    retracted = {m.get("overlay_id") for m in messages if m.get("type") == "overlay.retract"}
    overlays = [o for oid, o in latest.items() if oid not in retracted]
    shown = [o for o in overlays if o.get("approval", "auto") in ("auto", "approved")]
    groups: dict[str, list[dict]] = {}
    for o in shown:
        groups.setdefault(o.get("detected_moment_id") or o["overlay_id"], []).append(o)
    whatifs = {o["counterfactual_id"] for o in overlays if o.get("counterfactual_id")}

    claimed: set[str] = set()
    for mom in exp["moments"]:
        tag = f"{mom['moment_id']} ({mom['type']})"
        if "parent" in mom:
            hit = _aired_as_parent(mom, groups, tol)
            name = mom["parent"].replace("_", " ")
            report.add(f"{tag} is not aired as {'an' if name[0] in 'aeiou' else 'a'} {name}", hit is None,
                       f"group {hit} draws it")
            continue
        hit = _match(mom, groups, tol)
        if hit is None:
            if mom["must_air"]:
                report.add(f"{tag} aired", False, "no graphics on its players or its space around its time")
            continue
        claimed.add(hit)
        _check_moment(report, tag, mom, groups[hit], exp, md, whatifs, tol)
    report.unlabelled_moments = len(set(groups) - claimed)
    _check_density(report, shown)
    _check_timeliness(report, exp, messages, shown, tol)
    bad = [o["overlay_id"] for o in overlays if o.get("ai_generated") is not True
           or not {"synthetic-data", "ai-generated"} <= set(o.get("labels") or [])]
    report.add("every graphic is labelled AI-generated on synthetic data", not bad, f"unlabelled: {bad[:4]}")
    return report


def _check_contracts(report: Report, exp: dict, messages: list[dict]) -> None:
    from offball.services.replay import check_messages

    bad = check_messages(messages)
    for n, m in enumerate(messages, start=1):
        ids = {m.get("match_id"), (m.get("overlay") or {}).get("match_id", exp["match_id"])}
        if ids != {exp["match_id"]}:
            bad.append(f"line {n} ({m.get('type')}): match_id {ids - {exp['match_id']}}")
    report.add("every message matches the contracts", not bad, "; ".join(bad[:3]) + (" ..." if len(bad) > 3 else ""))


def _check_frames(report: Report, exp: dict, md: MatchData, messages: list[dict], tol: dict) -> None:
    pf = md.periods[exp["period"]]
    frames = {}
    for m in messages:
        f = m.get("frame") if m.get("type") == "frame" else None
        if isinstance(f, dict) and f.get("period") == exp["period"]:
            frames[f.get("t_ms")] = f
    want = pf.t_ms[(pf.t_ms >= exp["from_ms"]) & (pf.t_ms <= exp["to_ms"])]
    got = sum(1 for t in want if int(t) in frames)
    report.add("frames cover the stretch at 25 Hz", got >= tol["frame_coverage"] * len(want),
               f"{got} of {len(want)} frames")
    worst, wrong_players = 0.0, 0
    for t, f in frames.items():
        i = pf.index_of(int(t))
        on = {p: pf.xy[i, k] for k, p in enumerate(md.players) if not np.isnan(pf.xy[i, k, 0])}
        if set(f.get("players") or {}) != set(on):
            wrong_players += 1
            continue
        for p, xy in on.items():
            worst = max(worst, _dist(f["players"][p][:2], xy))
        worst = max(worst, _dist(f["ball"][:2], pf.ball[i, :2]))
    report.add("frames carry the tracking as it is", worst <= tol["frame_m"] and not wrong_players,
               f"largest error {worst:.2f} m; {wrong_players} frame(s) with the wrong players")


def _check_clock(report: Report, exp: dict, messages: list[dict], tol: dict) -> None:
    """`clock.sync` at least once a second of play, from the start of the stretch to its end (INTEGRATION 4.3)."""
    times = sorted(m["t_ms"] for m in messages if m.get("type") == "clock.sync" and m.get("period") == exp["period"])
    gap = float(np.diff([exp["from_ms"], *times, exp["to_ms"]]).max())
    report.add("the clock keeps the feed alive", bool(times) and gap <= tol["clock_gap_ms"],
               f"longest stretch of play without a clock.sync {gap:.0f} ms" if times else "no clock.sync")


def _check_score(report: Report, exp: dict, messages: list[dict], tol: dict) -> None:
    status = sorted((m for m in messages if m.get("type") == "match.status" and m.get("period") == exp["period"]),
                    key=lambda m: m["t_ms"])
    start = [m for m in status if m["t_ms"] <= exp["from_ms"] + tol["clock_gap_ms"]]
    want = exp["score"]["at_start"]
    report.add("the score is right as the stretch opens", bool(start) and start[-1]["score"] == want,
               f"expected {want}, got {start[-1]['score'] if start else 'no match.status'}")
    for ch in exp["score"]["changes"]:
        first = next((m for m in status if m["score"] == ch["score"]), None)
        ok = first is not None and ch["shot_ms"] - tol["score_before_ms"] <= first["t_ms"] <= \
            ch["in_ms"] + tol["score_after_ms"]
        report.add(f"the score goes to {ch['score']} as the goal goes in", ok,
                   f"first shown at {first['t_ms'] if first else 'never'} ms; shot {ch['shot_ms']}, in {ch['in_ms']}")


def _dist(a, b) -> float:
    if a is None or b is None:
        return float("inf")
    return float(np.hypot(a[0] - b[0], a[1] - b[1]))


def _in_time(o: dict, mom: dict, tol: dict) -> bool:
    return o["t_end_ms"] >= mom["t_start_ms"] - tol["timing_ms"] and o["t_start_ms"] <= mom["t_end_ms"] + tol["timing_ms"]


def _live(o: dict) -> bool:
    """Shows what happened: not a what-if, not a planned pass, not a gap that stays shut."""
    d = o.get("data") or {}
    return not o.get("counterfactual_id") and not d.get("planned") and not d.get("shut")


def _match(mom: dict, groups: dict[str, list[dict]], tol: dict) -> str | None:
    """The group of graphics that airs this moment: on its players or its space, around its time."""
    players = {mom["creator_id"], *mom["dragged_ids"], mom.get("receiver_id")} - {None}
    for gid, os in groups.items():
        for o in os:
            if not _in_time(o, mom, tol):
                continue
            a = o.get("anchors") or {}
            if a.get("player_id") in players or players & set(a.get("player_ids") or []):
                return gid
            gap = mom.get("gap")
            if gap and o.get("kind") == "gap_ring" and _dist(a.get("centre_xy"), gap["centre_xy"]) <= tol["gap_m"]:
                return gid
    return None


def _aired_as_parent(mom: dict, groups: dict[str, list[dict]], tol: dict) -> str | None:
    """A null moment is aired as its parent when its run is drawn, or a ring marks space opening where it would."""
    for gid, os in groups.items():
        for o in os:
            if not _in_time(o, mom, tol) or not _live(o):
                continue
            a = o.get("anchors") or {}
            if o.get("kind") == "run_arrow" and a.get("player_id") == mom["creator_id"] and \
                    (o.get("data") or {}).get("style") != "displacement":
                return gid
            gap = mom.get("gap")
            if gap and o.get("kind") == "gap_ring" and _dist(a.get("centre_xy"), gap["centre_xy"]) <= tol["gap_m"]:
                return gid
    return None


def _check_moment(report: Report, tag: str, mom: dict, os: list[dict], exp: dict, md: MatchData,
                  whatifs: set[str], tol: dict) -> None:
    report.add(f"{tag} aired", True)
    captions = [o for o in os if o.get("kind") == "caption"]
    missing = [m for m in exp["modes"] if m not in {o["mode"] for o in captions}]
    report.add(f"{tag} has a caption in every mode", not missing, f"missing {missing}")
    blank = [o["overlay_id"] for o in captions if not str((o.get("text") or {}).get("en", "")).strip()]
    report.add(f"{tag} captions are written in English", not blank, f"no English text: {blank[:4]}")
    lacking = [k for k in mom["required_kinds"] if k not in {o.get("kind") for o in os if _live(o)}]
    report.add(f"{tag} draws {', '.join(mom['required_kinds'])}", not lacking, f"missing {lacking}")
    if "run" in mom and "run_arrow" in mom["required_kinds"]:
        arrows = [o for o in os if o.get("kind") == "run_arrow" and _live(o)
                  and (o.get("anchors") or {}).get("player_id") == mom["creator_id"]]
        report.add(f"{tag} run arrow follows {mom['creator_id']}'s run", any(_follows(o, mom, tol) for o in arrows),
                   f"{len(arrows)} arrow(s) on {mom['creator_id']}, none along the run")
    if "gap" in mom and "gap_ring" in mom["required_kinds"]:
        rings = [o for o in os if o.get("kind") == "gap_ring" and _live(o)]
        near = min((_dist((o.get("anchors") or {}).get("centre_xy"), mom["gap"]["centre_xy"]) for o in rings),
                   default=float("inf"))
        report.add(f"{tag} gap ring is on the space that opened", near <= tol["gap_m"], f"nearest ring {near:.1f} m off")
    lines = [o for o in os if o.get("kind") == "pass_line" and _live(o)]
    if "pass" in mom and lines:
        right = [o for o in lines if (o.get("anchors") or {}).get("player_ids") == mom["pass"]["player_ids"]]
        report.add(f"{tag} pass line joins {' to '.join(mom['pass']['player_ids'])}", bool(right))
        sized = [o for o in right if "distance_m" in (o.get("data") or {})]
        if sized:
            off = [o["overlay_id"] for o in sized
                   if abs(float(o["data"]["distance_m"]) - mom["pass"]["distance_m"]) > tol["number_m"]]
            report.add(f"{tag} pass length is {mom['pass']['distance_m']} m", not off, f"wrong on {off[:3]}")
    first = min(o["t_start_ms"] for o in os)
    report.add(f"{tag} airs on time", mom["t_start_ms"] - tol["timing_ms"] <= first <= mom["t_end_ms"],
               f"first graphic at {first} ms, moment {mom['t_start_ms']}-{mom['t_end_ms']} ms")
    # Captions queue in the caption bar, so only graphics have to hold on their own.
    short = [o["overlay_id"] for o in os
             if o.get("kind") != "caption" and o["t_end_ms"] - o["t_start_ms"] < tol["hold_ms"]]
    report.add(f"{tag} graphics hold long enough to read", not short, f"too short: {short[:4]}")
    problems = _evidence(os, mom, exp, md, whatifs, tol)
    report.add(f"{tag} every graphic cites evidence from the moment", not problems, "; ".join(problems[:3]))
    wrong = _numbers(os, md, exp, tol)
    report.add(f"{tag} stat cards match the frames they cite", not wrong, "; ".join(wrong[:3]))


def _follows(o: dict, mom: dict, tol: dict) -> bool:
    """The arrow starts where the run starts and ends further along the same run."""
    a = o.get("anchors") or {}
    path = mom["run"]["path"]
    if not path or a.get("from_xy") is None or a.get("to_xy") is None:
        return False
    early = [k for k, p in enumerate(path) if p[0] <= mom["t_start_ms"] + 2000] or [0]
    k0 = min(early, key=lambda k: _dist(a["from_xy"], path[k][1:]))
    if _dist(a["from_xy"], path[k0][1:]) > tol["anchor_m"] or _dist(a["from_xy"], a["to_xy"]) < tol["run_min_m"]:
        return False
    return min(_dist(a["to_xy"], p[1:]) for p in path[k0:]) <= tol["anchor_m"]


def _evidence(os: list[dict], mom: dict, exp: dict, md: MatchData, whatifs: set[str], tol: dict) -> list[str]:
    lo, hi = mom["t_start_ms"] - tol["evidence_before_ms"], mom["t_end_ms"] + tol["evidence_after_ms"]
    events = {e.event_id: e for e in md.events}
    pf = md.periods[exp["period"]]
    problems = []
    for o in os:
        ids = o.get("evidence_ids") or []
        if not ids:
            problems.append(f"{o['overlay_id']} cites nothing")
        for ref in ids:
            if ref in whatifs:
                continue
            fr, ev = parse_frame_ref(ref), parse_event_ref(ref)
            if fr is not None and fr[0] == md.match_id and fr[1] == exp["period"] and \
                    pf.t_ms[0] <= fr[2] * FRAME_MS <= pf.t_ms[-1]:
                t = fr[2] * FRAME_MS
            elif ev is not None and ref in events and events[ref].period == exp["period"]:
                t = events[ref].t_ms
            else:
                problems.append(f"{o['overlay_id']} cites {ref}, which doesn't exist")
                continue
            if not lo <= t <= hi:
                problems.append(f"{o['overlay_id']} cites {ref}, outside the moment")
    return problems


def _numbers(os: list[dict], md: MatchData, exp: dict, tol: dict) -> list[str]:
    """A card's distance in metres for a player is how far they moved between the first and last frames it cites."""
    pf = md.periods[exp["period"]]
    wrong = []
    for o in os:
        d, a = o.get("data") or {}, o.get("anchors") or {}
        if o.get("kind") != "stat_card" or d.get("unit") != "m" or a.get("player_id") not in md.players:
            continue
        frames = sorted(fr[2] for fr in map(parse_frame_ref, o.get("evidence_ids") or []) if fr)
        if len(frames) < 2:
            wrong.append(f"{o['overlay_id']} cites fewer than two frames")
            continue
        col = md.players.index(a["player_id"])
        moved = _dist(pf.xy[pf.index_of(frames[0] * FRAME_MS), col], pf.xy[pf.index_of(frames[-1] * FRAME_MS), col])
        value = float(d.get("value", np.nan))
        if not abs(value - moved) <= tol["number_m"]:
            wrong.append(f"{o['overlay_id']} shows {d.get('value')} m; the frames give {moved:.1f} m")
    return wrong


def _check_density(report: Report, shown: list[dict]) -> None:
    over = []
    for mode, limit in DENSITY.items():
        gs = [o for o in shown if o["mode"] == mode and o.get("kind") in PITCH_KINDS and not o.get("counterfactual_id")]
        for t in sorted({o["t_start_ms"] for o in gs}):
            n = sum(1 for o in gs if o["t_start_ms"] <= t < o["t_end_ms"])
            if n > limit:
                over.append(f"{mode}: {n} at {t} ms")
                break
    report.add("no mode shows more pitch graphics at a time than it allows", not over, "; ".join(over))


def _check_timeliness(report: Report, exp: dict, messages: list[dict], shown: list[dict], tol: dict) -> None:
    """A graphic that arrives after the viewer's clock has passed most of it is dropped or flashes past
    (INTEGRATION 4.3). Messages are read in the order they arrive; viewers watch LIVE_BUFFER_MS behind the newest."""
    newest, arrived = None, {}
    for m in messages:
        t = m.get("type")
        if t == "frame" and isinstance(m.get("frame"), dict) and m["frame"].get("period") == exp["period"]:
            newest = max(newest or 0, m["frame"]["t_ms"])
        elif t == "clock.sync" and m.get("period") == exp["period"]:
            newest = max(newest or 0, m["t_ms"])
        elif t == "overlay.upsert" and isinstance(m.get("overlay"), dict):
            arrived.setdefault(m["overlay"].get("overlay_id"), newest)
    late = []
    for o in shown:
        at = arrived.get(o["overlay_id"])
        if at is None:
            continue
        seen = o["t_end_ms"] - max(o["t_start_ms"], at - LIVE_BUFFER_MS)
        if seen < min(tol["hold_ms"], o["t_end_ms"] - o["t_start_ms"]):
            late.append(o["overlay_id"])
    report.add("every graphic arrives in time to be seen", not late, f"late: {late[:4]}")
