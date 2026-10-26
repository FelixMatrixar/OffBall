"""Expected goals (PRD 13): the chance a shot is scored, from what can be observed about it.

The features are the shot's distance and the angle the goal mouth makes from where it was struck, its kind (header,
penalty, free kick) and whether the shooter was under pressure. A logistic model, trained on the season backdrop's
shots and their outcomes (`offball.models.train`), turns them into a probability. It never reads the held-out truth.

The season backdrop has events but no tracking, and its shots never record pressure or set pieces, so for now the
model learns from distance, angle and headers only. Pressure and the keeper's position, which drive the generator's
own chances, need training shots with tracking (OffBall-Bench).
"""

from __future__ import annotations

import math
from functools import cache
from pathlib import Path

import numpy as np

from offball.contracts import Event
from offball.core import GOAL_WIDTH, HALF_WIDTH, PITCH_LENGTH
from offball.models.match_data import MatchData
from offball.models.metrics import MetricResult, _event, metric

ARTIFACT = Path(__file__).parent / "artifacts" / "xg.joblib"
FEATURES = ["distance", "angle", "header", "penalty", "free_kick", "under_pressure"]


def geometry(x: float, y: float) -> tuple[float, float]:
    """Distance to the goal's centre and the angle (radians) between the posts, for a shot from (x, y) attacking
    towards x = 105."""
    dx = PITCH_LENGTH - x
    left, right = HALF_WIDTH - GOAL_WIDTH / 2, HALF_WIDTH + GOAL_WIDTH / 2
    angle = abs(math.atan2(right - y, max(dx, 1e-6)) - math.atan2(left - y, max(dx, 1e-6)))
    return math.hypot(dx, HALF_WIDTH - y), angle


def features(e: Event, attacking_right: bool) -> list[float]:
    """The shot's features, in FEATURES order. `attacking_right`: the shooter's club attacks towards x = 105."""
    x, y = e.start_xy
    if not attacking_right:
        x, y = PITCH_LENGTH - x, 2 * HALF_WIDTH - y
    distance, angle = geometry(x, y)
    sub = e.subtype or ""
    return [distance, angle, float(sub == "header" or e.body_part == "head"), float(sub == "penalty"),
            float(sub == "free_kick"), float(bool(e.under_pressure))]


def match_features(md: MatchData, e: Event) -> list[float]:
    return features(e, md.direction(e.period, e.team_id) > 0)


@cache
def model():
    import joblib

    if not ARTIFACT.exists():
        raise FileNotFoundError(f"No xG model at {ARTIFACT}; run `uv run python -m offball.models.train`")
    return joblib.load(ARTIFACT)


def probability(md: MatchData, e: Event) -> float:
    return float(model().predict_proba(np.asarray([match_features(md, e)]))[0, 1])


@metric("xg", "xG", "Expected goals: the chance a shot is scored, from the xG model", {"event_id": "str"}, decimals=2)
def xg_metric(md: MatchData, event_id: str) -> MetricResult:
    e = _event(md, event_id)
    if e.type != "shot" or not e.start_xy:
        raise ValueError(f"{event_id} is not a shot")
    return MetricResult("xg", probability(md, e), "xG", [event_id], {"event_id": event_id})
