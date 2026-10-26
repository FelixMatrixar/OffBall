"""Pass difficulty (PRD 13): a probability that a pass is completed, and a 0-10 rating, from what can be observed.

The features are what is known as the ball leaves the passer's foot: how hard it is struck, which way it goes, its
kind, where the passer is and how close the nearest opponent stands, and how many opponents are in the lane ahead.
Nothing about where the ball ended up is used: a failed pass ends where it was cut out, so its end point gives the
answer away and makes the probabilities overconfident. A logistic model, trained on completed and failed passes
(`offball.models.train`), turns the features into a probability; the rating is ten times the chance it fails. It
never reads the held-out truth.
"""

from __future__ import annotations

from functools import cache
from pathlib import Path

import numpy as np

from offball.contracts import Event
from offball.models.match_data import MatchData
from offball.models.metrics import MetricResult, _event, metric

ARTIFACT = Path(__file__).parent / "artifacts" / "pass_difficulty.joblib"
SET_PIECES = {"throw_in", "free_kick", "corner", "goal_kick", "kick_off"}
FEATURES = ["ball_speed", "forward", "across", "start_x", "passer_space", "in_lane", "lofted", "through", "cross",
            "switch", "set_piece", "under_pressure"]
LANE_M = 2.5
LANE_LENGTH_M = 30.0  # how far ahead along the pass's direction opponents count as in the lane


def _nearest(points: np.ndarray, at: np.ndarray) -> float:
    return float(np.min(np.linalg.norm(points - at, axis=1))) if len(points) else 30.0


def _in_lane(points: np.ndarray, a: np.ndarray, b: np.ndarray) -> int:
    """Opponents within LANE_M of the segment a-b, between its ends."""
    ab = b - a
    length2 = float(ab @ ab)
    if not len(points) or length2 < 1e-6:
        return 0
    t = np.clip(((points - a) @ ab) / length2, 0, 1)
    d = np.linalg.norm(points - (a + t[:, None] * ab), axis=1)
    return int(((d < LANE_M) & (t > 0.05) & (t < 0.95)).sum())


def features(md: MatchData, e: Event) -> list[float]:
    """The pass's features at release, in FEATURES order, in the passing club's frame (attacking to x = 105). Only the
    pass's direction is taken from where it ended, never its length."""
    start = np.asarray(e.start_xy, dtype=float)
    end = np.asarray(e.end_xy if e.end_xy else e.start_xy, dtype=float)
    s, t = md.to_team(e.period, e.team_id, start), md.to_team(e.period, e.team_id, end)
    d = t - s
    n = float(np.linalg.norm(d))
    u = d / n if n > 1e-6 else np.array([1.0, 0.0])
    opp = np.empty((0, 2))
    if e.period in md.periods:
        pf = md.periods[e.period]
        xy = pf.xy[pf.index_of(e.t_ms), md.columns_of(md.other(e.team_id))].astype(float)
        opp = md.to_team(e.period, e.team_id, xy[~np.isnan(xy[:, 0])])
    sub = e.subtype or ""
    return [float(e.ball_speed_mps or 0.0), float(u[0]), float(abs(u[1])), float(s[0]), _nearest(opp, s),
            float(_in_lane(opp, s, s + u * LANE_LENGTH_M)), float(sub == "lofted"), float(sub == "through"),
            float(sub == "cross"), float(sub == "switch"), float(sub in SET_PIECES), float(bool(e.under_pressure))]


def completed(e: Event) -> bool:
    return e.outcome == "complete"


@cache
def model():
    import joblib

    if not ARTIFACT.exists():
        raise FileNotFoundError(f"No pass difficulty model at {ARTIFACT}; run `uv run python -m offball.models.train`")
    return joblib.load(ARTIFACT)


def probability(md: MatchData, e: Event) -> float:
    """The chance the pass is completed."""
    return float(model().predict_proba(np.asarray([features(md, e)]))[0, 1])


def rating(p_complete: float) -> float:
    """0 (routine) to 10 (nearly impossible): ten times the chance the pass fails."""
    return round(10 * (1 - p_complete), 1)


@metric("pass_difficulty", "/10", "How hard a pass was, 0 (routine) to 10 (nearly impossible), from the pass difficulty "
        "model; details give the chance it was completed", {"event_id": "str"})
def pass_difficulty_metric(md: MatchData, event_id: str) -> MetricResult:
    e = _event(md, event_id)
    if e.type != "pass" or not e.start_xy:
        raise ValueError(f"{event_id} is not a pass")
    p = probability(md, e)
    return MetricResult("pass_difficulty", rating(p), "/10", [event_id], {"event_id": event_id},
                        {"p_complete": round(p, 3)})
