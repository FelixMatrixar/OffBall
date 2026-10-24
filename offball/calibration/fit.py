"""Fitting realism targets from open data (PRD 12.2).

Reads the downloaded calibration sources in `calibration/raw/` (git-ignored, never committed) and writes only
fitted numbers: per-match bands and distribution quantiles in `calibration/targets.json`, and a report in
`calibration/reports/fit-report.md`. No real row, name or ID leaves this module.

- Wyscout (Pappalardo et al., 2019; CC BY 4.0): the English first division 2017/18, 380 matches. Event rates,
  pass lengths, shots, possessions, fouls and restarts.
- SkillCorner open data (MIT): A-League 2024/25 season aggregates. Distance, high-intensity running, sprints
  and peak speed per player, and off-ball runs by type.

    uv run offball fit
"""

from __future__ import annotations

import collections
import csv
import json
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "calibration" / "raw"
TARGETS = ROOT / "calibration" / "targets.json"
REPORT = ROOT / "calibration" / "reports" / "fit-report.md"

PITCH_L, PITCH_W = 105.0, 68.0
ACCURATE, GOAL_TAG, OWN_GOAL_TAG = 1801, 101, 102
PASS_FREE_KICKS = {"Throw in", "Goal kick", "Corner", "Free Kick", "Free kick cross"}
SHOT_FREE_KICKS = {"Free kick shot", "Penalty"}
# Possessions are team switches among these: passes, free kicks, shots and clearances. Wyscout's other
# "on the ball" events (touches, deflections) have no counterpart in a generated match, so they are left out
# to compare like with like.
ON_BALL = {"Pass", "Free Kick", "Shot"}
QUANTILES = np.linspace(0, 1, 101)
MATCH_SECONDS = 95 * 60


def _metres(p: dict) -> tuple[float, float]:
    return p["x"] * PITCH_L / 100.0, p["y"] * PITCH_W / 100.0


def _length(e: dict) -> float | None:
    pos = e.get("positions") or []
    if len(pos) < 2:
        return None
    (x0, y0), (x1, y1) = _metres(pos[0]), _metres(pos[1])
    return float(np.hypot(x1 - x0, y1 - y0))


def wyscout_matches(path: Path) -> tuple[list[dict[str, float]], dict[str, list[float]]]:
    """Per-match totals (both teams together) and pooled samples for the distributions."""
    events = json.loads(path.read_text(encoding="utf-8"))
    by_match: dict[int, list[dict]] = collections.defaultdict(list)
    for e in events:
        by_match[e["matchId"]].append(e)
    rows: list[dict[str, float]] = []
    pass_lengths: list[float] = []
    shot_distances: list[float] = []
    for evs in by_match.values():
        evs.sort(key=lambda e: (e["matchPeriod"], e["eventSec"]))
        periods: dict[str, float] = collections.defaultdict(float)
        passes = completed = long_ = shots = goals = in_box = 0
        lengths: list[float] = []
        fouls = offsides = corners = throw_ins = 0
        possessions, last_team = 0, None
        for e in evs:
            name, sub = e["eventName"], e["subEventName"]
            tags = {t["id"] for t in e.get("tags", [])}
            periods[e["matchPeriod"]] = max(periods[e["matchPeriod"]], e["eventSec"])
            if (name in ON_BALL or sub == "Clearance") and e["teamId"] != last_team:
                possessions += 1
                last_team = e["teamId"]
            if name == "Pass" or (name == "Free Kick" and sub in PASS_FREE_KICKS):
                passes += 1
                completed += ACCURATE in tags
                d = _length(e)
                if d is not None:
                    lengths.append(d)
                    long_ += d > 30.0
                corners += sub == "Corner"
                throw_ins += sub == "Throw in"
            elif name == "Shot" or (name == "Free Kick" and sub in SHOT_FREE_KICKS):
                shots += 1
                goals += GOAL_TAG in tags and OWN_GOAL_TAG not in tags
                x, y = _metres(e["positions"][0])
                shot_distances.append(float(np.hypot(PITCH_L - x, PITCH_W / 2 - y)))
                in_box += x >= PITCH_L - 16.5 and abs(y - PITCH_W / 2) <= 20.16
            elif name == "Foul":
                fouls += 1
            elif name == "Offside":
                offsides += 1
        played = sum(v for k, v in periods.items() if k in ("1H", "2H")) or MATCH_SECONDS
        scale = MATCH_SECONDS / played
        pass_lengths += lengths
        rows.append({
            "passes": passes * scale,
            "completion": completed / max(passes, 1),
            "median_pass_m": float(np.median(lengths)) if lengths else 0.0,
            "long_pass_share": long_ / max(len(lengths), 1),
            "shots": shots * scale,
            "goals": goals * scale,
            "shots_in_box_share": in_box / max(shots, 1),
            "possessions": possessions * scale,
            "fouls": fouls * scale,
            "offsides": offsides * scale,
            "corners": corners * scale,
            "throw_ins": throw_ins * scale,
            "goals_per_shot": goals / max(shots, 1),
        })
    return rows, {"pass_length_m": pass_lengths, "shot_distance_m": shot_distances}


def _num(v: str) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def skillcorner_physical(path: Path, min_minutes: float = 60.0, min_matches: int = 5) -> dict[str, list[float]]:
    """Per-player values for outfield players who average at least an hour over five or more matches (the
    aggregates are per-match averages): distance and sprints per 95 minutes, the shares of distance at
    15-20 km/h, above 20 km/h and above 25 km/h, the share of time the ball is in play, and peak speed
    (99th percentile, km/h)."""
    out: dict[str, list[float]] = collections.defaultdict(list)
    with path.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if (row.get("position_group") or "").lower().startswith("goal"):
                continue
            minutes = _num(row.get("minutes_full_all"))
            total = _num(row.get("total_distance_full_all"))
            matches = _num(row.get("count_match")) or 0
            if not minutes or minutes < min_minutes or matches < min_matches or not total:
                continue
            hi = _num(row.get("hi_distance_full_all"))
            running = _num(row.get("running_distance_full_all"))
            sprint_m = _num(row.get("sprint_distance_full_all"))
            sprints = _num(row.get("sprint_count_full_all"))
            peak = _num(row.get("psv99"))
            # Minutes with the ball in play: the player's team in possession, or the opponents.
            in_play = (_num(row.get("minutes_full_tip")) or 0) + (_num(row.get("minutes_full_otip")) or 0)
            out["km_per95"].append(total / minutes * 95 / 1000)
            if hi is not None:
                out["hi_share"].append(hi / total)
            if running is not None:
                out["running_share"].append(running / total)
            if sprint_m is not None:
                out["sprint_share"].append(sprint_m / total)
            if 0 < in_play <= minutes:
                out["in_play_share"].append(in_play / minutes)
            if sprints is not None:
                out["sprints_per95"].append(sprints / minutes * 95)
            if peak:
                out["peak_speed_kmh"].append(peak)
    return out


def skillcorner_runs(path: Path, min_minutes: float = 60.0) -> dict[str, list[float]]:
    """Off-ball runs per 30 minutes of team possession, by run type, per outfield player who averages at
    least an hour a match."""
    out: dict[str, list[float]] = collections.defaultdict(list)
    with path.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            minutes = _num(row.get("minutes"))
            if (row.get("position_group") or "").lower().startswith("goal") or not minutes or minutes < min_minutes:
                continue
            for key, value in row.items():
                if key.endswith("_count_p30tip") and (v := _num(value)) is not None:
                    out[key.removesuffix("_count_p30tip")].append(v)
    return out


def band(values: list[float], source: str) -> dict[str, float]:
    a = np.asarray(values, dtype=float)
    q = np.quantile(a, [0.05, 0.25, 0.5, 0.75, 0.95])
    return {"mean": round(float(a.mean()), 4), "p5": round(float(q[0]), 4), "p25": round(float(q[1]), 4),
            "p50": round(float(q[2]), 4), "p75": round(float(q[3]), 4), "p95": round(float(q[4]), 4),
            "n": int(a.size), "source": source}


def quantiles(values: list[float], source: str) -> dict:
    a = np.asarray(values, dtype=float)
    return {"quantiles": [round(float(v), 3) for v in np.quantile(a, QUANTILES)], "n": int(a.size), "source": source}


def fit(raw: Path = RAW) -> dict:
    wy = raw / "wyscout" / "events_England.json"
    sc = raw / "skillcorner" / "aggregates"
    if not wy.exists() or not sc.exists():
        raise FileNotFoundError(f"Download the calibration sources into {raw} first (PRD 12.2)")
    t0 = time.time()
    rows, samples = wyscout_matches(wy)
    phys = skillcorner_physical(sc / "aus1league_physicalaggregates_20242025.csv")
    runs = skillcorner_runs(sc / "aus1league_obraggregates_20242025.csv")
    wy_src = "Wyscout, English first division 2017/18 (CC BY 4.0)"
    sc_src = "SkillCorner open data, A-League 2024/25 aggregates (MIT)"
    match = {k: band([r[k] for r in rows], wy_src) for k in rows[0]}
    match["km_per_outfield"] = band(phys["km_per95"], sc_src)
    match["hsr_share"] = band(phys["hi_share"], sc_src)
    for name in ("running_share", "sprint_share", "in_play_share"):
        match[name] = band(phys[name], sc_src)
    return {
        "version": 1,
        "fitted": time.strftime("%Y-%m-%d"),
        "seconds": round(time.time() - t0, 1),
        "matches": len(rows),
        "match": match,
        "distributions": {
            "pass_length_m": quantiles(samples["pass_length_m"], wy_src),
            "shot_distance_m": quantiles(samples["shot_distance_m"], wy_src),
            "player_km_per95": quantiles(phys["km_per95"], sc_src),
            "player_peak_speed_kmh": quantiles(phys["peak_speed_kmh"], sc_src),
            "player_sprints_per95": quantiles(phys["sprints_per95"], sc_src),
        },
        "runs_per30_tip": {k: band(v, sc_src) for k, v in sorted(runs.items()) if v},
    }


def write_report(targets: dict, path: Path = REPORT) -> None:
    lines = ["# Calibration fit", "",
             f"Fitted {targets['fitted']} from {targets['matches']} real matches and season aggregates. "
             "Only these fitted numbers are kept; the raw sources stay out of the repository (PRD 12.2).", "",
             "## Per-match targets (both teams, per 95 minutes)", "",
             "| Metric | Mean | 5th | 25th | Median | 75th | 95th | Source |", "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for k, b in targets["match"].items():
        lines.append(f"| {k} | {b['mean']:g} | {b['p5']:g} | {b['p25']:g} | {b['p50']:g} | {b['p75']:g} | {b['p95']:g} | "
                     f"{b['source']} |")
    lines += ["", "## Distributions (quantiles kept for the KS checks in gate 1)", "",
              "| Distribution | Median | 5th | 95th | n |", "| --- | --- | --- | --- | --- |"]
    for k, d in targets["distributions"].items():
        q = d["quantiles"]
        lines.append(f"| {k} | {q[50]:g} | {q[5]:g} | {q[95]:g} | {d['n']} |")
    lines += ["", "## Off-ball runs per 30 minutes of team possession, per outfield player", "",
              "| Run type | Mean | Median | 95th |", "| --- | --- | --- | --- |"]
    for k, b in targets["runs_per30_tip"].items():
        lines.append(f"| {k} | {b['mean']:g} | {b['p50']:g} | {b['p95']:g} |")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    targets = fit()
    TARGETS.write_text(json.dumps(targets, indent=1) + "\n", encoding="utf-8")
    write_report(targets)
    print(f"Fitted {len(targets['match'])} match targets from {targets['matches']} matches in {targets['seconds']} s "
          f"-> {TARGETS}")


if __name__ == "__main__":
    main()
