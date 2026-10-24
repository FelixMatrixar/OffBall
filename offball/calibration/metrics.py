"""Match-level realism metrics, shared by the tuner and the realism gate (PRD 12.6, 12.10 gate 1)."""

from __future__ import annotations

import collections
import json
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import numpy as np

from offball.core import HZ

MATCH_SECONDS = 95 * 60
TARGETS_PATH = Path(__file__).resolve().parents[2] / "calibration" / "targets.json"
HI_SPEED_MPS = 20.0 / 3.6  # high-intensity running, as SkillCorner counts it
RUNNING_MPS = 15.0 / 3.6  # running: 15-20 km/h
SPRINT_MPS = 25.0 / 3.6  # sprinting: above 25 km/h
# What stops play, and what restarts it, in the event stream.
STOPS = {"ball_out", "foul", "offside"}
RESTARTS = {"throw_in", "corner", "goal_kick", "free_kick", "kick_off", "penalty"}


@dataclass(frozen=True)
class Target:
    lo: float
    hi: float
    weight: float
    source: str


# Per-match targets for both teams together, normalised to 95 minutes: approximate published norms, used only
# where `calibration/targets.json` (fitted from Wyscout and SkillCorner by `offball fit`) has no band.
DEFAULT_TARGETS: dict[str, Target] = {
    "passes": Target(850, 1050, 1.0, "norm"),
    "completion": Target(0.77, 0.85, 2.0, "norm"),
    "median_pass_m": Target(14, 18, 1.0, "norm"),
    "long_pass_share": Target(0.08, 0.15, 1.0, "norm"),
    "shots": Target(22, 30, 3.0, "norm"),
    "goals": Target(2.0, 3.4, 2.0, "norm"),
    "xg_per_shot": Target(0.09, 0.13, 1.0, "norm"),
    "shots_in_box_share": Target(0.55, 0.7, 1.0, "norm"),
    "possessions": Target(170, 230, 1.5, "norm"),
    "tackles": Target(28, 45, 1.0, "norm"),
    "fouls": Target(18, 26, 1.0, "norm"),
    "offsides": Target(2, 5, 0.5, "norm"),
    "corners": Target(8, 12, 1.0, "norm"),
    "throw_ins": Target(35, 50, 0.5, "norm"),
    "km_per_outfield": Target(9.5, 11.5, 1.0, "norm"),
    "hsr_share": Target(0.04, 0.09, 1.0, "norm"),
    "running_share": Target(0.12, 0.16, 0.5, "norm"),
    "sprint_share": Target(0.01, 0.02, 0.5, "norm"),
    "in_play_share": Target(0.54, 0.6, 1.0, "norm"),
    "behind_runs_p30": Target(1.2, 3.6, 0.5, "norm"),
    "overlap_runs_p30": Target(0.4, 1.2, 0.25, "norm"),
}
# Engine intents -> SkillCorner run types, for the run-rate metrics.
RUN_TYPES = {"behind_runs_p30": ("run", "behindrun"), "overlap_runs_p30": ("overlap", "overlaprun")}


@cache
def fitted() -> dict:
    """The fitted targets file, or an empty dict before the first fit."""
    return json.loads(TARGETS_PATH.read_text(encoding="utf-8")) if TARGETS_PATH.exists() else {}


def targets() -> dict[str, Target]:
    """Tuning targets: the interquartile range of real matches where a fit exists, the norms elsewhere. The
    simulated average must land inside the middle half of real matches."""
    bands = fitted().get("match", {})
    out = dict(DEFAULT_TARGETS)
    for name, t in DEFAULT_TARGETS.items():
        b = bands.get(name)
        if b is not None:
            out[name] = Target(b["p25"], b["p75"], t.weight, b["source"])
    conversion = bands.get("goals_per_shot")
    if conversion is not None:  # a shot's true xG should average out to the league's conversion rate
        out["xg_per_shot"] = Target(conversion["mean"] - 0.02, conversion["mean"] + 0.02, 1.0, conversion["source"])
    runs = fitted().get("runs_per30_tip", {})
    for name, (_intent, real) in RUN_TYPES.items():
        b = runs.get(real)
        if b is not None:  # the average player's rate within half to one and a half times the real average
            out[name] = Target(0.5 * b["mean"], 1.5 * b["mean"], DEFAULT_TARGETS[name].weight, b["source"])
    peaks = fitted().get("distributions", {}).get("player_peak_speed_kmh")
    if peaks is not None:  # the typical player's peak speed sits in the middle half of real players'
        out["peak_speed_kmh"] = Target(peaks["quantiles"][25], peaks["quantiles"][75], 1.0, peaks["source"])
    return out


def match_metrics(result) -> dict[str, float]:
    """Rates per 95 minutes from a MatchResult (from the emergent engine)."""
    ev = result.events
    played_s = sum(result.period_lengths.values()) / HZ
    scale = MATCH_SECONDS / max(played_s, 1.0)
    passes = [e for e in ev if e["type"] == "pass"]
    shots = [e for e in ev if e["type"] == "shot"]
    counts = collections.Counter(e["type"] for e in ev)
    subtypes = collections.Counter(e.get("subtype") for e in passes)
    lengths = [np.hypot(e["end_xy"][0] - e["start_xy"][0], e["end_xy"][1] - e["start_xy"][1])
               for e in passes if e.get("end_xy") and e.get("start_xy")]
    xg = [p["p_success"] for p in result.probabilities if p["kind"] == "shot"]
    in_box = 0
    for s in shots:
        x, y = s["start_xy"]
        if (x > 88.5 or x < 16.5) and abs(y - 34) < 20.16:
            in_box += 1
    possessions = possession_count(ev)
    km, hi_m, run_m, sprint_m, total_m = [], 0.0, 0.0, 0.0, 0.0
    speeds: list[np.ndarray] = []
    for period, rec in result.recorders.items():
        n = result.period_lengths[period]
        xy = rec.xy[:n].astype(float)
        step = np.linalg.norm(np.diff(xy, axis=0), axis=2)
        roles_gk = [0, 11]
        outfield = np.nan_to_num(np.delete(step, roles_gk, axis=1))
        speeds.append(outfield * HZ)
        km.append(outfield.sum() / 20 / 1000)
        # The share of distance covered above 20 km/h, as SkillCorner measures high-intensity running.
        hi_m += float(outfield[outfield * HZ > HI_SPEED_MPS].sum())
        run_m += float(outfield[(outfield * HZ > RUNNING_MPS) & (outfield * HZ <= HI_SPEED_MPS)].sum())
        sprint_m += float(outfield[outfield * HZ > SPRINT_MPS].sum())
        total_m += float(outfield.sum())
    return {
        "passes": len(passes) * scale,
        "completion": sum(e["outcome"] == "complete" for e in passes) / max(1, len(passes)),
        "median_pass_m": float(np.median(lengths)) if lengths else 0.0,
        "long_pass_share": float(np.mean([d > 30 for d in lengths])) if lengths else 0.0,
        "shots": len(shots) * scale,
        "goals": sum(e["outcome"] == "goal" for e in shots) * scale,
        "xg_per_shot": float(np.mean(xg)) if xg else 0.0,
        "shots_in_box_share": in_box / max(1, len(shots)),
        "possessions": possessions * scale,
        "tackles": counts["tackle"] * scale,
        "fouls": counts["foul"] * scale,
        "offsides": counts["offside"] * scale,
        "corners": subtypes["corner"] * scale,
        "throw_ins": subtypes["throw_in"] * scale,
        "km_per_outfield": sum(km) * scale,
        "hsr_share": hi_m / max(total_m, 1.0),
        "running_share": run_m / max(total_m, 1.0),
        "sprint_share": sprint_m / max(total_m, 1.0),
        "in_play_share": 1.0 - dead_seconds(ev) / max(played_s, 1.0),
        **run_rates(result, played_s - dead_seconds(ev)),
        "peak_speed_kmh": float(np.median([robust_peak(col) for col in np.vstack(speeds).T])) * 3.6,
    }


def possession_count(events: list[dict]) -> int:
    """Possessions as the calibration data counts them: team switches among passes, shots and clearances."""
    n, last = 0, None
    for e in events:
        if e["type"] in ("pass", "shot", "clearance") and e["team_id"] != last:
            n += 1
            last = e["team_id"]
    return n


def run_rates(result, in_play_s: float) -> dict[str, float]:
    """Mean off-ball runs per 30 minutes of team possession, over outfield players who played most of the
    match, by run type: the engine's counterpart of SkillCorner's off-ball run aggregates (gate 4). The mean,
    not the median: runs in behind are mostly forwards' work, so most players' counts are zero."""
    players = result.players
    frames: collections.Counter = collections.Counter()
    total = 0
    for period, rec in result.recorders.items():
        n = result.period_lengths[period]
        on = rec.slot_player[:n]
        total += n
        ids, counts = np.unique(on[on >= 0], return_counts=True)
        frames.update({players[int(k)].player_id: int(c) for k, c in zip(ids, counts, strict=True)})
    passes = collections.Counter(e["team_id"] for e in result.events if e["type"] == "pass")
    all_passes = max(sum(passes.values()), 1)
    counts = collections.Counter((it["player_id"], it["intent"]) for it in result.intents)
    rates: dict[str, list[float]] = collections.defaultdict(list)
    for p in players:
        share_on = frames[p.player_id] / max(total, 1)
        if p.role == "GK" or share_on < 0.6:
            continue
        club = p.player_id.split("-")[0]
        tip_min = in_play_s / 60.0 * passes[club] / all_passes * share_on
        for name, (intent, _real) in RUN_TYPES.items():
            rates[name].append(counts[(p.player_id, intent)] / max(tip_min, 1e-6) * 30.0)
    return {name: float(np.mean(v)) if v else 0.0 for name, v in rates.items()}


def dead_seconds(events: list[dict]) -> float:
    """Time the ball was out of play: from whatever stopped play (out, a foul, an offside, a goal) to the
    restart that resumed it."""
    dead, stopped = 0.0, None
    for e in sorted(events, key=lambda e: (e["period"], e["t_ms"])):
        key = (e["period"], e["t_ms"] / 1000.0)
        if e["type"] in ("pass", "shot") and e.get("subtype") in RESTARTS:
            if stopped is not None and stopped[0] == key[0]:
                dead += key[1] - stopped[1]
            stopped = None
        elif stopped is None and (e["type"] in STOPS or (e["type"] == "shot" and e.get("outcome") == "goal")):
            stopped = key
    return dead


def robust_peak(speeds: np.ndarray) -> float:
    """A player's peak speed, robust to tracking glitches: the speed held for at least a second in total
    (the 25th-fastest frame), close to how SkillCorner reports peak sprint velocity."""
    s = np.asarray(speeds, dtype=float)
    s = s[~np.isnan(s)]
    if s.size < HZ:
        return float(s.max()) if s.size else 0.0
    return float(np.partition(s, -HZ)[-HZ])


def deviation(value: float, target: Target) -> float:
    """0 inside the band, otherwise the distance outside it in band widths."""
    width = max(target.hi - target.lo, 1e-9)
    if value < target.lo:
        return (target.lo - value) / width
    if value > target.hi:
        return (value - target.hi) / width
    return 0.0


def loss(metrics: dict[str, float], bands: dict[str, Target] | None = None) -> float:
    bands = bands if bands is not None else targets()
    return float(sum(t.weight * deviation(metrics[k], t) ** 2 for k, t in bands.items() if k in metrics))


def summarise(rows: list[dict[str, float]]) -> dict[str, float]:
    keys = rows[0].keys()
    return {k: float(np.mean([r[k] for r in rows])) for k in keys}
