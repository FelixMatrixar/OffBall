"""Match-level realism metrics, shared by the tuner and the realism gate (PRD 12.6, 12.10 gate 1)."""

from __future__ import annotations

import collections
from dataclasses import dataclass

import numpy as np

from offball.core import HZ

MATCH_SECONDS = 95 * 60


@dataclass(frozen=True)
class Target:
    lo: float
    hi: float
    weight: float
    source: str


# Per-match targets for both teams together, normalised to 95 minutes. Until `calibration/fit.py` has fitted
# them from SkillCorner and Wyscout data, they are approximate published norms for top-flight football.
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
    "hsr_share": Target(0.04, 0.09, 0.5, "norm"),
}


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
    possessions = len({e.get("possession_n") for e in ev if e.get("possession_n") is not None})
    km, hsr, total = [], 0, 0
    for period, rec in result.recorders.items():
        n = result.period_lengths[period]
        xy = rec.xy[:n].astype(float)
        step = np.linalg.norm(np.diff(xy, axis=0), axis=2)
        roles_gk = [0, 11]
        outfield = np.delete(step, roles_gk, axis=1)
        km.append(np.nansum(outfield) / 20 / 1000)
        speed = outfield * HZ
        valid = ~np.isnan(speed)
        hsr += int(((speed > 5.5) & valid).sum())
        total += int(valid.sum())
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
        "hsr_share": hsr / max(1, total),
    }


def deviation(value: float, target: Target) -> float:
    """0 inside the band, otherwise the distance outside it in band widths."""
    width = max(target.hi - target.lo, 1e-9)
    if value < target.lo:
        return (target.lo - value) / width
    if value > target.hi:
        return (value - target.hi) / width
    return 0.0


def loss(metrics: dict[str, float], targets: dict[str, Target] = DEFAULT_TARGETS) -> float:
    return float(sum(t.weight * deviation(metrics[k], t) ** 2 for k, t in targets.items() if k in metrics))


def summarise(rows: list[dict[str, float]]) -> dict[str, float]:
    keys = rows[0].keys()
    return {k: float(np.mean([r[k] for r in rows])) for k in keys}
