"""Run classification (PRD 13): what kind of run each detected off-ball run is.

`offball.models.runs.detect_runs` finds the runs; this names them. Each run is described by player-relative features
taken along it, in the team frame (attacking towards x = 105): where it starts and ends against the ball, the
defensive line and the ball carrier; how fast, how far and which way it goes; how close the nearest defender is and
whether that defender goes with it; and whether the runner was found by a pass. A gradient-boosted classifier,
trained by `offball.models.train` on the calibration matches' oracle intents (training split only, PRD 12.9),
turns the features into one of the types the generator labels:

- in_behind: a run beyond the defensive line, for the ball
- overlap: round the outside of the ball carrier
- decoy: a run that pulls a defender away from space a teammate then uses
- positioning: moving to a place in the team's shape, whether back into it or to offer the ball carrier a pass.
  The generator labels these two apart (support and anchor), but both carry the player to a point near the shape
  and look the same in tracking: kept apart, support scored F1 0.09 in cross-validation on 57 examples

The PRD's other attacking run types (underlap, third-man, blind-side, timed in behind, false-nine drop and the like)
appear only where the director plants them, once or twice a match, too rarely to learn or score; the moment
detectors name those (`offball.models.candidates`).
"""

from __future__ import annotations

from functools import cache
from pathlib import Path

import numpy as np

from offball.core import HALF_WIDTH
from offball.models.match_data import MatchData
from offball.models.runs import Run

ARTIFACT = Path(__file__).parent / "artifacts" / "runclass.joblib"
TYPES = ("in_behind", "overlap", "decoy", "positioning")
# The generator's intents that are run types, and the type each one is.
INTENT_TYPE = {"run": "in_behind", "run_into_gap": "in_behind", "counter_run": "in_behind", "overlap": "overlap",
               "decoy_run": "decoy", "support": "positioning", "anchor": "positioning"}
FEATURES = ["x0", "y0_width", "x1", "y1_width", "dx", "dy", "length_m", "duration_s", "max_speed", "mean_speed",
            "ball_dx0", "ball_dy0", "ball_dx1", "line_dx0", "line_dx1", "carrier_dx0", "carrier_dx1",
            "outside_carrier", "defender_d0", "defender_d1", "defender_follow", "defender_moved",
            "received", "team_moved_x", "carrier_d0", "carrier_d1", "ball_d0", "ball_d1", "toward_ball"]


def _width(p: np.ndarray) -> float:
    """How far from the middle of the pitch a point is, either side."""
    return abs(float(p[1]) - HALF_WIDTH)


def _line_x(xy_team: np.ndarray, defenders: list[int]) -> float:
    """The defensive line's depth: the second-deepest defender in the attacking team's frame (the deepest is the
    keeper)."""
    xs = np.sort(xy_team[defenders, 0][~np.isnan(xy_team[defenders, 0])])
    return float(xs[-2]) if len(xs) >= 2 else float(xs[-1]) if len(xs) else 0.0


def features(md: MatchData, run: Run) -> list[float]:
    """The run's features, in FEATURES order."""
    pf = md.periods[run.period]
    club, col = run.club, md.players.index(run.player_id)
    xy = md.to_team(run.period, club, pf.xy.astype(float))
    ball = md.to_team(run.period, club, pf.ball[:, :2].astype(float))
    mates = [c for c in md.columns_of(club) if c != col]
    opp = list(md.columns_of(md.other(club)))
    a, b = run.i0, run.i1
    p0, p1 = xy[a, col], xy[b, col]
    path = xy[a: b + 1, col]
    length = float(np.nansum(np.linalg.norm(np.diff(path, axis=0), axis=1)))
    duration = (b - a) * (pf.t_ms[1] - pf.t_ms[0]) / 1000 if pf.n > 1 else 0.0
    speed = np.nan_to_num(pf.speed[a: b + 1, col])
    # The ball carrier: the teammate nearest the ball when the run starts.
    near = [c for c in mates if not np.isnan(xy[a, c, 0])]
    carrier = min(near, key=lambda c: float(np.linalg.norm(xy[a, c] - ball[a]))) if near else col
    # The nearest defender at the start, and whether he went the same way.
    live = [c for c in opp if not np.isnan(xy[a, c, 0]) and not np.isnan(xy[b, c, 0])]
    d0 = {c: float(np.linalg.norm(xy[a, c] - p0)) for c in live}
    marker = min(d0, key=d0.get) if d0 else None
    run_vec, follow, moved, dist1 = p1 - p0, 0.0, 0.0, 30.0
    if marker is not None:
        m_vec = xy[b, marker] - xy[a, marker]
        moved = float(np.linalg.norm(m_vec))
        denom = float(np.linalg.norm(run_vec)) * moved
        follow = float(run_vec @ m_vec / denom) if denom > 1e-6 else 0.0
        dist1 = min(float(np.linalg.norm(xy[b, c] - p1)) for c in live)
    received = any(e.type == "pass" and e.recipient_id == run.player_id and run.t0_ms <= e.t_ms <= run.t1_ms + 3000
                   for e in md.events_between(run.period, run.t0_ms, run.t1_ms + 3000))
    shift = [c for c in mates if not np.isnan(xy[a, c, 0]) and not np.isnan(xy[b, c, 0])]
    team_moved = float(np.mean(xy[b, shift, 0] - xy[a, shift, 0])) if shift else 0.0
    # Support comes towards the ball carrier to offer a pass; a move back into shape needn't.
    to_ball = ball[a] - p0
    reach = float(np.linalg.norm(run_vec)) * float(np.linalg.norm(to_ball))
    toward = float(run_vec @ to_ball / reach) if reach > 1e-6 else 0.0
    return [float(p0[0]), _width(p0), float(p1[0]), _width(p1), float(run_vec[0]), float(run_vec[1]), length, duration,
            run.max_speed, float(speed.mean()), float(ball[a, 0] - p0[0]), float(ball[a, 1] - p0[1]),
            float(ball[b, 0] - p1[0]), float(p0[0] - _line_x(xy[a], opp)), float(p1[0] - _line_x(xy[b], opp)),
            float(p0[0] - xy[a, carrier, 0]), float(p1[0] - xy[b, carrier, 0]),
            _width(xy[(a + b) // 2, col]) - _width(xy[(a + b) // 2, carrier]),
            d0[marker] if marker is not None else 30.0, dist1, follow, moved, float(received), team_moved,
            float(np.linalg.norm(p0 - xy[a, carrier])), float(np.linalg.norm(p1 - xy[b, carrier])),
            float(np.linalg.norm(p0 - ball[a])), float(np.linalg.norm(p1 - ball[b])), toward]


@cache
def model():
    import joblib

    if not ARTIFACT.exists():
        raise FileNotFoundError(f"No run classifier at {ARTIFACT}; run `uv run python -m offball.models.train`")
    return joblib.load(ARTIFACT)


def classify(md: MatchData, runs: list[Run]) -> list[tuple[str, float]]:
    """Each run's type and the classifier's probability for it."""
    if not runs:
        return []
    proba = model().predict_proba(np.asarray([features(md, r) for r in runs]))
    classes = list(model().classes_)
    best = proba.argmax(axis=1)
    return [(str(classes[k]), float(proba[n, k])) for n, k in enumerate(best)]
