"""The generator's true models: possession value, pass success, shot conversion and duels.

These are the hidden laws of the synthetic world. Every pass and shot draws its outcome from them, and
their probabilities are written to the truth store as ground truth for pass difficulty and xG (PRD 12.5).
The interpretation models never import this module; they learn their own estimates from data.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from offball.generator.engine.geometry import L, W, goal_angle, goal_distance
from offball.generator.engine.params import DEFAULT, EngineParams

GRAVITY = 9.81
GROUND_DECEL = 1.7  # m/s^2, rolling resistance on grass
AIR_DRAG = 0.12  # 1/s, horizontal speed decay in flight
CONTROL_RADIUS = 1.0
REACTION_S = 0.6
LOW_BALL_M = 2.3  # balls below this height can be cut out or headed


def sigmoid(x: float | np.ndarray) -> float | np.ndarray:
    return 1.0 / (1.0 + np.exp(-x))


def xg_location(x_t: float, y_t: float) -> float:
    """Unpressured shot conversion from a team-frame location."""
    if x_t < L / 2:
        return 0.0005
    return float(sigmoid(-1.05 + 1.45 * goal_angle(x_t, y_t) - 0.105 * goal_distance(x_t, y_t)))


def location_value(x_t: float, y_t: float, p: EngineParams = DEFAULT) -> float:
    """The generator's possession value of having the ball at a team-frame location.

    Shaped like published expected-threat surfaces: about 0.01 in our own third, 0.02 at halfway, 0.085 at
    22 m central (roughly twice the xG of shooting from there, because better chances usually follow),
    0.17 at the penalty spot and 0.3 in the six-yard box.
    """
    progress = float(sigmoid((x_t - p.value_progress_mid) / p.value_progress_scale))
    centrality = math.exp(-(((y_t - W / 2) / 20.0) ** 2))
    return p.value_base + p.value_progress * progress * (0.45 + 0.55 * centrality) + p.value_xg_weight * xg_location(
        x_t, y_t)


def value_grid(nx: int = 53, ny: int = 34, p: EngineParams = DEFAULT) -> np.ndarray:
    """location_value on a grid of cell centres, shape (ny, nx), row 0 at y = 0."""
    xs = (np.arange(nx) + 0.5) * L / nx
    ys = (np.arange(ny) + 0.5) * W / ny
    return np.array([[location_value(x, y, p) for x in xs] for y in ys])


@dataclass(frozen=True)
class ShotContext:
    x_t: float
    y_t: float
    pressure: float
    header: bool
    finishing: float
    composure: float
    keeper_cover: float  # 1 when the keeper is set on the shot line, 0 when beaten or out of position
    penalty: bool = False


def xg_true(s: ShotContext, p: EngineParams = DEFAULT) -> float:
    if s.penalty:
        return 0.76
    logit = (
        -1.05
        + 1.45 * goal_angle(s.x_t, s.y_t)
        - 0.105 * goal_distance(s.x_t, s.y_t)
        - 0.9 * s.pressure
        - 0.85 * float(s.header)
        + 1.2 * (s.finishing - 0.6)
        + 0.5 * (s.composure - 0.6) * s.pressure
        + 0.9 * (1.0 - s.keeper_cover)
        + p.xg_bias
    )
    return float(np.clip(sigmoid(logit), 0.002, 0.95))


def pressure_on(pos: np.ndarray, opponents: np.ndarray) -> float:
    """0..1: how hard a player is pressed, from opponents within 4.5 m."""
    if len(opponents) == 0:
        return 0.0
    d = np.linalg.norm(opponents - pos, axis=1)
    contrib = np.clip(1.0 - d / 4.5, 0.0, 1.0)
    return float(1.0 - np.prod(1.0 - contrib))


def time_to_reach(pos: np.ndarray, vel: np.ndarray, vmax: np.ndarray, targets: np.ndarray,
                  reaction: float | np.ndarray = REACTION_S) -> np.ndarray:
    """Spearman (2018) time to intercept: keep moving for the reaction time, then run straight at top speed.

    pos, vel: (n, 2); vmax: (n,); targets: (m, 2). Returns (n, m) seconds.
    """
    reaction = np.asarray(reaction, dtype=float)
    r = reaction if reaction.ndim == 0 else reaction[:, None]
    start = pos + vel * (reaction if reaction.ndim == 0 else reaction[:, None])
    d = np.linalg.norm(start[:, None, :] - targets[None, :, :], axis=2)
    return r + np.maximum(0.0, d - CONTROL_RADIUS) / vmax[:, None]


@dataclass
class BallFlight:
    """A planned ball path from start to end. Ground balls roll; aerial balls fly with drag, then drop."""

    start: np.ndarray
    end: np.ndarray
    aerial: bool
    v0: float  # initial horizontal speed, m/s
    vz0: float  # initial vertical speed, m/s
    duration: float  # seconds to reach end

    @property
    def distance(self) -> float:
        return float(np.linalg.norm(self.end - self.start))

    def horizontal_at(self, t: float) -> float:
        if self.aerial:
            return self.v0 * (1 - math.exp(-AIR_DRAG * t)) / AIR_DRAG
        return max(0.0, self.v0 * t - 0.5 * GROUND_DECEL * t * t)

    def speed_at(self, t: float) -> float:
        if self.aerial:
            return self.v0 * math.exp(-AIR_DRAG * t)
        return max(0.0, self.v0 - GROUND_DECEL * t)

    def height_at(self, t: float) -> float:
        if not self.aerial:
            return 0.0
        return max(0.0, self.vz0 * t - 0.5 * GRAVITY * t * t)

    def position_at(self, t: float) -> np.ndarray:
        d = self.distance
        if d < 1e-6:
            return np.array([self.start[0], self.start[1], 0.0])
        s = min(self.horizontal_at(t), d) / d
        xy = self.start + s * (self.end - self.start)
        return np.array([xy[0], xy[1], self.height_at(t)])

    def time_at_fraction(self, frac: np.ndarray) -> np.ndarray:
        s = frac * self.distance
        if self.aerial:
            inner = np.clip(1 - s * AIR_DRAG / self.v0, 1e-6, 1.0)
            return -np.log(inner) / AIR_DRAG
        disc = np.maximum(self.v0**2 - 2 * GROUND_DECEL * s, 0.0)
        return (self.v0 - np.sqrt(disc)) / GROUND_DECEL


def plan_ground(start: np.ndarray, end: np.ndarray, arrival_speed: float) -> BallFlight:
    d = float(np.linalg.norm(end - start))
    v0 = math.sqrt(arrival_speed**2 + 2 * GROUND_DECEL * d)
    v0 = min(v0, 34.0)
    disc = max(v0**2 - 2 * GROUND_DECEL * d, 0.0)
    duration = (v0 - math.sqrt(disc)) / GROUND_DECEL if d > 0 else 0.0
    return BallFlight(start, end, False, v0, 0.0, duration)


def plan_aerial(start: np.ndarray, end: np.ndarray, apex: float | None = None) -> BallFlight:
    d = float(np.linalg.norm(end - start))
    apex = apex if apex is not None else min(4.0 + d * 0.18, 16.0)
    vz0 = math.sqrt(2 * GRAVITY * apex)
    duration = 2 * vz0 / GRAVITY
    v0 = d * AIR_DRAG / (1 - math.exp(-AIR_DRAG * duration)) if d > 0 else 0.0
    return BallFlight(start, end, True, min(v0, 34.0), vz0, duration)


def plan_shot(start: np.ndarray, end: np.ndarray, speed: float, lift: float = 0.6) -> BallFlight:
    d = float(np.linalg.norm(end - start))
    duration = d / speed
    return BallFlight(start, end, True, speed, lift + 0.5 * GRAVITY * duration * 0.15, duration)


@dataclass
class PassAssessment:
    p_success: float
    p_no_intercept: float
    p_reach: float
    p_exec: float
    p_control: float
    interceptor: int  # index into the defender arrays, -1 if none is a threat
    intercept_point: np.ndarray | None
    intercept_time: float
    receiver_time: float


SAMPLE_FRACTIONS = np.linspace(0.12, 1.0, 9)


def assess_pass(
    flight: BallFlight,
    receiver_pos: np.ndarray,
    receiver_vel: np.ndarray,
    receiver_vmax: float,
    def_pos: np.ndarray,
    def_vel: np.ndarray,
    def_vmax: np.ndarray,
    passing: float,
    first_touch: float,
    passer_pressure: float,
    receiver_pressure: float,
    anticipated: bool = True,
    p: EngineParams = DEFAULT,
) -> PassAssessment:
    """True success probability of a pass, and how it would fail."""
    pts = flight.start + SAMPLE_FRACTIONS[:, None] * (flight.end - flight.start)
    t_ball = flight.time_at_fraction(SAMPLE_FRACTIONS)
    if flight.aerial:
        heights = np.array([flight.height_at(t) for t in t_ball])
        low = heights < LOW_BALL_M
    else:
        low = np.ones(len(pts), dtype=bool)

    t_recv = float(
        time_to_reach(receiver_pos[None], receiver_vel[None], np.array([receiver_vmax]), flight.end[None],
                      reaction=0.15 if anticipated else REACTION_S)[0, 0]
    )
    p_reach = float(sigmoid((flight.duration + 0.35 - t_recv) / 0.25))

    interceptor, point, t_int = -1, None, math.inf
    if len(def_pos):
        t_def = time_to_reach(def_pos, def_vel, def_vmax, pts)  # (n_def, n_pts)
        margin = t_ball[None, :] - t_def
        # A defender has to be there a little before the ball to cut it out cleanly.
        p_path = sigmoid((margin[:, :-1] - p.intercept_lead) / p.intercept_tau) * low[None, :-1]
        # At the arrival point it is a race against the receiver, not the ball.
        p_end = sigmoid((t_recv - t_def[:, -1] - p.intercept_lead) / p.intercept_tau) * low[-1]
        p_def = np.maximum(p_path.max(axis=1) if p_path.shape[1] else 0.0, p_end)
        p_def = np.clip(p_def * 0.92, 0.0, 0.97)
        p_no_int = float(np.prod(1.0 - p_def))
        best = int(np.argmax(p_def))
        if p_def[best] > 0.02:
            interceptor = best
            j_path = int(np.argmax(p_path[best])) if p_path.shape[1] else 0
            if p_path.shape[1] and p_path[best, j_path] >= p_end[best]:
                point, t_int = pts[j_path], float(t_ball[j_path])
            else:
                point, t_int = flight.end, max(float(t_def[best, -1]), 0.2)
    else:
        p_no_int = 1.0

    d = flight.distance
    # Long balls are hard to land: execution error grows steeply with distance and pressure.
    error = p.exec_base + p.exec_long * (d / 35.0) ** 1.8 * (1.25 - passing) * (1 + 0.9 * passer_pressure)
    error += p.exec_aerial if flight.aerial else 0.0
    p_exec = float(np.clip(1 - error, 0.35, 0.995))
    arrival_speed = flight.speed_at(flight.duration)
    touch = p.control_base * (1 + 1.6 * receiver_pressure) * (0.6 + arrival_speed / 14) * (1.35 - first_touch)
    if flight.aerial:
        touch *= p.control_aerial  # a dropping ball is harder to kill than one along the ground
    p_control = float(np.clip(1 - touch, 0.5, 0.995))
    p_success = p_no_int * p_reach * p_exec * p_control
    return PassAssessment(
        p_success=float(np.clip(p_success, 0.001, 0.999)),
        p_no_intercept=p_no_int,
        p_reach=p_reach,
        p_exec=p_exec,
        p_control=p_control,
        interceptor=interceptor,
        intercept_point=point,
        intercept_time=t_int,
        receiver_time=t_recv,
    )


@dataclass
class CrossAssessment:
    p_success: float
    p_delivery: float
    p_claim: float
    p_duel: float
    winner_defender: int  # index into the defender arrays, -1 if none contests


def assess_cross(
    end: np.ndarray,
    receiver_aerial: float,
    def_pos: np.ndarray,
    def_aerial: np.ndarray,
    keeper_idx: int,
    goal_x: float,
    passing: float,
    passer_pressure: float,
) -> CrossAssessment:
    """True probability that a cross or corner finds its target: delivery, keeper claim, then the header."""
    p_delivery = float(np.clip(0.78 + 0.25 * (passing - 0.6) - 0.15 * passer_pressure, 0.4, 0.95))
    near_goal = abs(goal_x - float(end[0])) < 7.0 and abs(float(end[1]) - W / 2) < 10.0
    p_claim = 0.0
    if keeper_idx >= 0:
        k_dist = float(np.linalg.norm(def_pos[keeper_idx] - end))
        p_claim = float(np.clip((0.38 if near_goal else 0.08) * (1.2 - k_dist / 12.0), 0.0, 0.45))
    outfield = [k for k in range(len(def_pos)) if k != keeper_idx]
    dists = np.array([float(np.linalg.norm(def_pos[k] - end)) for k in outfield]) if outfield else np.array([])
    contest = [outfield[k] for k in np.argsort(dists)[:2] if dists[k] < 3.5] if len(dists) else []
    if contest:
        best = max(contest, key=lambda k: def_aerial[k])
        sep = float(min(dists[outfield.index(k)] for k in contest))
        p_duel = float(sigmoid(2.5 * (receiver_aerial - def_aerial[best]) + 0.9 * (sep - 1.8) - 0.35))
        winner = best
    else:
        p_duel, winner = 0.8, -1
    p = p_delivery * (1 - p_claim) * p_duel
    return CrossAssessment(float(np.clip(p, 0.01, 0.95)), p_delivery, p_claim, p_duel, winner)


def tackle_win_prob(tackling: float, dribbling: float, from_behind: bool) -> float:
    return float(sigmoid(3.0 * (tackling - dribbling) + 0.1 - (0.9 if from_behind else 0.0)))


def foul_prob(tackling: float, from_behind: bool, in_box: bool, p: EngineParams = DEFAULT) -> float:
    prob = p.foul_base + 0.1 * (1 - tackling) + (0.15 if from_behind else 0.0)
    return float(prob * (0.55 if in_box else 1.0))
