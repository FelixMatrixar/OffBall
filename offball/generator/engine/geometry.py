"""Geometry helpers. Team frame: each team attacks towards x' = 105, with its left side at high y'."""

from __future__ import annotations

import math

import numpy as np

from offball.core import GOAL_WIDTH, PITCH_LENGTH, PITCH_WIDTH

L = PITCH_LENGTH
W = PITCH_WIDTH
HALF_GOAL = GOAL_WIDTH / 2


def to_team(xy: np.ndarray, direction: int) -> np.ndarray:
    """Absolute -> team frame. direction is +1 when the team attacks towards x = 105."""
    if direction > 0:
        return xy
    out = np.empty_like(xy)
    out[..., 0] = L - xy[..., 0]
    out[..., 1] = W - xy[..., 1]
    return out


def from_team(xy: np.ndarray, direction: int) -> np.ndarray:
    return to_team(xy, direction)  # the 180 degree rotation is its own inverse


def pt_to_team(x: float, y: float, direction: int) -> tuple[float, float]:
    return (x, y) if direction > 0 else (L - x, W - y)


def goal_centre(direction: int) -> np.ndarray:
    """Centre of the goal a team attacks."""
    return np.array([L if direction > 0 else 0.0, W / 2])


def own_goal(direction: int) -> np.ndarray:
    return np.array([0.0 if direction > 0 else L, W / 2])


def goal_angle(x_t: float, y_t: float) -> float:
    """Angle in radians subtended by the goal mouth from a team-frame position."""
    dx = L - x_t
    a = math.atan2(W / 2 + HALF_GOAL - y_t, dx)
    b = math.atan2(W / 2 - HALF_GOAL - y_t, dx)
    return abs(a - b)


def goal_distance(x_t: float, y_t: float) -> float:
    return math.hypot(L - x_t, W / 2 - y_t)


def in_pitch(xy: np.ndarray, margin: float = 0.0) -> bool:
    return bool(margin <= xy[0] <= L - margin and margin <= xy[1] <= W - margin)


def clamp_pitch(xy: np.ndarray, margin: float = 0.5) -> np.ndarray:
    return np.array([min(L - margin, max(margin, xy[0])), min(W - margin, max(margin, xy[1]))])


def seg_closest(p: np.ndarray, a: np.ndarray, b: np.ndarray) -> tuple[float, float]:
    """Closest point on segment ab to p: (fraction along ab, distance)."""
    ab = b - a
    denom = float(ab @ ab)
    if denom < 1e-9:
        return 0.0, float(np.linalg.norm(p - a))
    s = float(np.clip(((p - a) @ ab) / denom, 0.0, 1.0))
    return s, float(np.linalg.norm(a + s * ab - p))


def angle_of(v: np.ndarray) -> float:
    return math.atan2(float(v[1]), float(v[0]))


def wrap(a: float) -> float:
    return (a + math.pi) % (2 * math.pi) - math.pi


def polygon_area(poly: list[tuple[float, float]]) -> float:
    s = 0.0
    for (x1, y1), (x2, y2) in zip(poly, poly[1:] + poly[:1], strict=True):
        s += x1 * y2 - x2 * y1
    return abs(s) / 2


def point_in_polygon(x: float, y: float, poly: list[tuple[float, float]]) -> bool:
    inside = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1 + 1e-12) + x1:
            inside = not inside
    return inside


def rect(cx: float, cy: float, half_w: float, half_h: float) -> list[tuple[float, float]]:
    x0, x1 = max(0.0, cx - half_w), min(L, cx + half_w)
    y0, y1 = max(0.0, cy - half_h), min(W, cy + half_h)
    return [(round(x0, 1), round(y0, 1)), (round(x1, 1), round(y0, 1)), (round(x1, 1), round(y1, 1)),
            (round(x0, 1), round(y1, 1))]
