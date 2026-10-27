"""Off-ball credit (PRD 10.3, 13): Space Created (m²) and Threat Created for a player's off-ball work in a moment.

Space generation in the manner of Fernández and Bornn (2018). The space a player's movement handed their side is the
control the side has of the moment's gap zone when the gap is used, against a counterfactual in which the player
hadn't made the movement and the defenders it pulled hadn't followed. In the counterfactual, the creator and the
dragged defenders keep their place in the shape: each moves only as far as the rest of their own side moved over
the window, so a whole team shifting with the ball isn't credited to one run. Threat Created weights the same change
in control by the space value of each cell (`offball.models.epv`).

It reads observed tracking only, so it estimates credit the same way it would on real data. The generator measures
true credit by re-running the moment without the creator's decision (PRD 12.9); the counterfactual workers' engine
re-runs (ADR 0005) will refine this estimate with ghost players, and `offball.models.train` scores it against
the true credit (PRD 19.2: within 25% on 80% of moments, rank correlation 0.8).
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache
from pathlib import Path

import numpy as np

from offball.models import epv
from offball.models.match_data import MatchData
from offball.models.metrics import MetricResult, _frames, _zone_cells, metric, zone_control_at, zone_from

DEFAULT_MEASURE_MS = 3000  # when no pass uses the gap: about when the generator measures its own moments


@dataclass(frozen=True)
class Credit:
    space_created_m2: float
    threat_created: float
    t_measure_ms: int
    ghosts: dict[str, list[float]]  # where the creator and the dragged defenders would have been


def measure_instant(md: MatchData, club_id: str, period: int, t_start_ms: int, t_end_ms: int,
                    receiver_id: str | None = None) -> int:
    """When the gap is measured: the first completed pass by the club in the window (to the receiver, if one is
    named), when the gap is used; otherwise a few seconds in."""
    passes = [e for e in md.events_between(period, t_start_ms, t_end_ms)
              if e.type == "pass" and e.team_id == club_id and e.outcome == "complete"
              and (receiver_id is None or e.recipient_id == receiver_id)]
    return passes[0].t_ms if passes else min(t_start_ms + DEFAULT_MEASURE_MS, t_end_ms)


def credit(md: MatchData, club_id: str, creator_id: str, dragged_ids: list[str], period: int, t_start_ms: int,
           t_measure_ms: int, zone: list) -> Credit:
    """Space and threat the creator's movement made in the zone by t_measure_ms."""
    pf = md.periods[period]
    a, b = pf.index_of(t_start_ms), pf.index_of(t_measure_ms)
    moved = [creator_id, *dragged_ids]
    override, ghosts = {}, {}
    for pid in moved:
        col = md.players.index(pid)
        mates = [c for c in md.columns_of(md.team_of[pid]) if md.players[c] not in moved
                 and not np.isnan(pf.xy[a, c, 0]) and not np.isnan(pf.xy[b, c, 0])]
        shift = np.mean(pf.xy[b, mates] - pf.xy[a, mates], axis=0) if mates else np.zeros(2)
        override[col] = pf.xy[a, col].astype(float) + shift
        ghosts[pid] = [round(float(v), 1) for v in override[col]]
    cells = _zone_cells(zone_from({"zone": zone}))
    gain = zone_control_at(md, club_id, period, b, cells) - zone_control_at(md, club_id, period, b, cells, override)
    values = epv.value_at(md, period, club_id, cells)
    # 1 m cells: summed control is square metres; the threat is the zone's mean, as the generator measures it.
    return Credit(float(gain.sum()), float((gain * values).mean()), int(pf.t_ms[b]), ghosts)


# ------------------------------------------------------------------------------------------------ learned credit

# Moment types by what the creator's decision changes, which decides how its counterfactual differs.
FAMILIES = {"decoy_run": "run", "timed_run_in_behind": "run", "blind_side_run": "run", "third_man_run": "run",
            "overlap": "wide", "underlap": "wide", "switch_of_play": "wide",
            "false_9_drop": "drop", "pinning": "drop", "press_broken": "drop",
            "rotation": "shape", "set_piece_screen": "shape", "cover_shadow": "shape", "rest_defence_exposed": "shape",
            "fatigue_gap": "state", "space_lost": "state"}
FAMILY_NAMES = ("run", "wide", "drop", "shape", "state")
FEATURES = ["space_est", "threat_est", "zone_m2", "area_start", "area_measure", "control_gain", "defender_moved",
            "creator_moved", "follow", "measure_s", *(f"family_{f}" for f in FAMILY_NAMES)]
ARTIFACT = Path(__file__).parent / "artifacts" / "credit.joblib"


def features(md: MatchData, moment_type: str, club_id: str, creator_id: str, dragged_ids: list[str], period: int,
             t_start_ms: int, t_measure_ms: int, zone: list) -> list[float]:
    """What tracking shows about a moment, in FEATURES order: the observed estimate itself, the zone's size and
    control before and when the gap is used, how far the creator and the dragged defender moved and whether
    together, how long the gap took, and the moment's family."""
    c = credit(md, club_id, creator_id, dragged_ids, period, t_start_ms, t_measure_ms, zone)
    pf = md.periods[period]
    a, b = pf.index_of(t_start_ms), pf.index_of(t_measure_ms)
    cells = _zone_cells(zone_from({"zone": zone}))
    start, end = zone_control_at(md, club_id, period, a, cells), zone_control_at(md, club_id, period, b, cells)
    creator = pf.xy[b, md.players.index(creator_id)] - pf.xy[a, md.players.index(creator_id)]
    moved, follow = 0.0, 0.0
    if dragged_ids:
        col = md.players.index(dragged_ids[0])
        path = pf.xy[a: b + 1, col].astype(float) - pf.xy[a, col].astype(float)
        moved = float(np.nanmax(np.linalg.norm(path, axis=1))) if len(path) else 0.0
        d = pf.xy[b, col] - pf.xy[a, col]
        denom = float(np.linalg.norm(creator) * np.linalg.norm(d))
        follow = float(creator @ d / denom) if denom > 1e-6 else 0.0
    family = FAMILIES.get(moment_type, "shape")
    return [c.space_created_m2, c.threat_created, float(len(cells)), float(start.sum()), float(end.sum()),
            float(end.mean() - start.mean()), moved, float(np.linalg.norm(creator)), follow,
            (b - a) * (pf.t_ms[1] - pf.t_ms[0]) / 1000 if pf.n > 1 else 0.0,
            *(float(family == f) for f in FAMILY_NAMES)]


@cache
def learned():
    """The credit model `offball.models.train` fits to true credit, or None before it has been trained."""
    import joblib

    return joblib.load(ARTIFACT) if ARTIFACT.exists() else None


def learned_space(feats: list[float]) -> float:
    """Space Created from the learned model: it predicts the true credit on a log scale."""
    model = learned()
    if model is None:
        raise FileNotFoundError(f"No credit model at {ARTIFACT}; run `uv run python -m offball.models.train`")
    return float(np.expm1(model.predict(np.asarray([feats]))[0]))


_PARAMS = {"club_id": "str", "creator_id": "str", "dragged_ids": "list[str]", "period": "int", "t_start_ms": "int",
           "t_end_ms": "int", "zone": "polygon", "receiver_id": "optional str"}


def _credit(md: MatchData, club_id: str, creator_id: str, dragged_ids: list[str], period: int, t_start_ms: int,
            t_end_ms: int, zone: list, receiver_id: str | None) -> tuple[Credit, dict, list[str]]:
    t_measure = measure_instant(md, club_id, period, t_start_ms, t_end_ms, receiver_id)
    c = credit(md, club_id, creator_id, list(dragged_ids), period, t_start_ms, t_measure, zone)
    pf = md.periods[period]
    params = {"club_id": club_id, "creator_id": creator_id, "dragged_ids": list(dragged_ids), "period": period,
              "t_start_ms": t_start_ms, "t_end_ms": t_end_ms, "zone": zone,
              **({"receiver_id": receiver_id} if receiver_id else {})}
    return c, params, _frames(md, period, pf.index_of(t_start_ms), pf.index_of(c.t_measure_ms))


@metric("space_created_by_m2", "m²", "Space Created: how much of the gap zone a player's off-ball movement won for "
        "their club, against a counterfactual where the player and the defenders they pulled kept their shape",
        _PARAMS, decimals=0)
def space_created_by(md: MatchData, club_id: str, creator_id: str, dragged_ids: list[str], period: int,
                     t_start_ms: int, t_end_ms: int, zone: list, receiver_id: str | None = None) -> MetricResult:
    c, params, frames = _credit(md, club_id, creator_id, dragged_ids, period, t_start_ms, t_end_ms, zone, receiver_id)
    return MetricResult("space_created_by_m2", c.space_created_m2, "m²", frames, params,
                        {"t_measure_ms": c.t_measure_ms, "ghosts": c.ghosts})


@metric("threat_created", "EPV", "Threat Created: the gain in space value a player's off-ball movement made in the "
        "gap zone, against the same counterfactual as Space Created", _PARAMS, decimals=4)
def threat_created(md: MatchData, club_id: str, creator_id: str, dragged_ids: list[str], period: int,
                   t_start_ms: int, t_end_ms: int, zone: list, receiver_id: str | None = None) -> MetricResult:
    c, params, frames = _credit(md, club_id, creator_id, dragged_ids, period, t_start_ms, t_end_ms, zone, receiver_id)
    return MetricResult("threat_created", c.threat_created, "EPV", frames, params,
                        {"t_measure_ms": c.t_measure_ms, "ghosts": c.ghosts})
