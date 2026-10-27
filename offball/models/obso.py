"""Off-ball scoring opportunity (PRD 13; Spearman, 2018): how likely each attacker is to score from the next
on-ball action, whether or not they have the ball.

For every cell, the chance the ball goes there next (transition), times the attacker's own chance of controlling it
there (pitch control, per player), times the chance of scoring from there (the xG model): summed over the pitch, that
is the attacker's scoring opportunity. The transition is a normal kernel around the ball whose width is fitted to
the training matches' passes, as Spearman fitted his to observed ball movement.

Validated against realized chances (PRD 13): the attacking side's total opportunity should rank the moments a shot
follows above the ones none does, and a shooter should be the attacker the model rated highest just before.
"""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path

import numpy as np

from offball.core import HALF_WIDTH, PITCH_LENGTH
from offball.models import xg as XG
from offball.models.match_data import MatchData
from offball.models.metrics import MetricResult, _frames, metric
from offball.models.pitch_control import GRID_2M, ppcf

ARTIFACT = Path(__file__).parent / "artifacts" / "obso.json"
CELLS = GRID_2M.centres()
DEFAULT_SIGMA_M = 14.0  # before fitting: roughly the spread of a short pass
KEEP = 1e-5  # cells weighing less than this share of the heaviest are left out


@cache
def transition_sigma() -> float:
    """The transition kernel's width in metres, fitted by `offball.models.train`."""
    if ARTIFACT.exists():
        return float(json.loads(ARTIFACT.read_text(encoding="utf-8"))["sigma_m"])
    return DEFAULT_SIGMA_M


def fit_sigma(mds: list[MatchData]) -> float:
    """The root-mean-square of completed passes' displacement per axis: a normal kernel with the same spread."""
    d = [np.subtract(e.end_xy, e.start_xy) for md in mds for e in md.events
         if e.type == "pass" and e.outcome == "complete" and e.start_xy and e.end_xy]
    return float(np.sqrt(np.mean(np.square(d)))) if d else DEFAULT_SIGMA_M


@cache
def _scoring_team_frame() -> np.ndarray:
    """xG of an open-play shot from each cell, attacking towards x = 105; zero beyond 40 m, where no one shoots."""
    feats = []
    for x, y in CELLS:
        distance, angle = XG.geometry(float(x), float(y))
        feats.append([distance, angle, 0.0, 0.0, 0.0, 0.0])
    p = XG.model().predict_proba(np.asarray(feats))[:, 1]
    dist = np.hypot(PITCH_LENGTH - CELLS[:, 0], HALF_WIDTH - CELLS[:, 1])
    return np.where(dist <= 40.0, p, 0.0)


def scoring(md: MatchData, period: int, club: str) -> np.ndarray:
    """Per absolute cell, the chance `club` scores from a shot there."""
    if md.direction(period, club) > 0:
        return _scoring_team_frame()
    # The grid is symmetric under the half-turn, so the team-frame values just reverse.
    return _scoring_team_frame()[::-1]


def transition(ball_xy: np.ndarray, sigma: float | None = None) -> np.ndarray:
    """Chance the ball goes to each cell next: a normal kernel around the ball, normalised over the pitch."""
    s = sigma or transition_sigma()
    w = np.exp(-np.sum((CELLS - ball_xy[None, :]) ** 2, axis=1) / (2 * s * s))
    return w / w.sum()


def by_player(md: MatchData, period: int, idx: int, club: str) -> dict[str, float]:
    """Each of `club`'s players' scoring opportunity at frame idx."""
    pf = md.periods[period]
    xy = pf.xy[idx].astype(float)
    vel = np.nan_to_num(pf.vel[idx].astype(float))
    ball = pf.ball[idx, :2].astype(float)
    if np.isnan(ball).any():
        raise ValueError("no ball position at that instant")
    att = [c for c in md.columns_of(club) if not np.isnan(xy[c, 0])]
    dfn = [c for c in md.columns_of(md.other(club)) if not np.isnan(xy[c, 0])]
    weight = transition(ball) * scoring(md, period, club)
    # Control matters only where the ball might go and a shot could score. Leaving the rest out is 15 times faster
    # and moves the total by 2% at most (checked against every cell over a half of s27-02).
    keep = weight > weight.max() * KEEP if weight.max() > 0 else np.zeros_like(weight, dtype=bool)
    if not keep.any():
        return {md.players[c]: 0.0 for c in att}
    p_att, _ = ppcf(xy[att], vel[att], xy[dfn], vel[dfn], ball, CELLS[keep])
    return {md.players[c]: float(p_att[k] @ weight[keep]) for k, c in enumerate(att)}


@metric("scoring_opportunity", "%", "Off-ball scoring opportunity: the chance a player, or a whole club when no "
        "player is given, scores from the next on-ball action, from where everyone is and how they are moving",
        {"club_id": "str", "period": "int", "t_ms": "int", "player_id": "optional str"}, decimals=1)
def scoring_opportunity(md: MatchData, club_id: str, period: int, t_ms: int,
                        player_id: str | None = None) -> MetricResult:
    i = md.periods[period].index_of(t_ms)
    values = by_player(md, period, i, club_id)
    if player_id is not None and player_id not in values:
        raise ValueError(f"{player_id} isn't one of {club_id}'s players on the pitch")
    value = values[player_id] if player_id else sum(values.values())
    ranked = sorted(values.items(), key=lambda kv: -kv[1])[:3]
    params = {"club_id": club_id, "period": period, "t_ms": t_ms, **({"player_id": player_id} if player_id else {})}
    return MetricResult("scoring_opportunity", value * 100, "%", _frames(md, period, i), params,
                        {"top": [{"player_id": p, "pct": round(v * 100, 1)} for p, v in ranked]})
