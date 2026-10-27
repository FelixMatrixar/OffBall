"""Physics-based pitch control (Spearman, 2018): who controls each part of the pitch (PRD 13).

`control_spearman` integrates each player's chance of controlling a ball that arrives at a cell, following
Spearman's model (reaction 0.7 s, top speed 5 m/s, sigma 0.45 s, lambda 4.3 /s). `control_fast` is the
closed-form first-arrival approximation the live views use; both return the attacking team's share.

Inputs are observed positions and velocities only, never generator internals.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from offball.core import PITCH_LENGTH, PITCH_WIDTH

REACTION_S = 0.7
MAX_SPEED = 5.0
TTI_SIGMA = 0.45
LAMBDA = 4.3
BALL_SPEED = 15.0


@dataclass(frozen=True)
class Grid:
    """Cell centres covering the pitch. Row 0 is y near 0."""

    nx: int
    ny: int

    @property
    def cell_w(self) -> float:
        return PITCH_LENGTH / self.nx

    @property
    def cell_h(self) -> float:
        return PITCH_WIDTH / self.ny

    @property
    def cell_area(self) -> float:
        return self.cell_w * self.cell_h

    def centres(self) -> np.ndarray:
        xs = (np.arange(self.nx) + 0.5) * self.cell_w
        ys = (np.arange(self.ny) + 0.5) * self.cell_h
        gx, gy = np.meshgrid(xs, ys)
        return np.stack([gx.ravel(), gy.ravel()], axis=1)


GRID_1M = Grid(105, 68)
GRID_2M = Grid(53, 34)


def _time_to_intercept(pos: np.ndarray, vel: np.ndarray, cells: np.ndarray,
                       reaction: float = REACTION_S, vmax: float = MAX_SPEED) -> np.ndarray:
    """(players, cells) seconds: carry on for the reaction time, then run straight at top speed."""
    start = pos + vel * reaction
    d = np.linalg.norm(start[:, None, :] - cells[None, :, :], axis=2)
    return reaction + d / vmax


def control_fast(att_pos: np.ndarray, att_vel: np.ndarray, def_pos: np.ndarray, def_vel: np.ndarray,
                 cells: np.ndarray) -> np.ndarray:
    """Attacking control per cell from the first arrival of each team (the live approximation)."""
    t_att = _time_to_intercept(att_pos, att_vel, cells).min(axis=0)
    t_def = _time_to_intercept(def_pos, def_vel, cells).min(axis=0)
    scale = np.pi / np.sqrt(3.0) / TTI_SIGMA
    return 1.0 / (1.0 + np.exp(-scale * (t_def - t_att)))


def ppcf(att_pos: np.ndarray, att_vel: np.ndarray, def_pos: np.ndarray, def_vel: np.ndarray, ball_xy: np.ndarray,
         cells: np.ndarray, dt: float = 0.04, horizon: float = 10.0) -> tuple[np.ndarray, np.ndarray]:
    """Each player's chance of controlling a ball sent to each cell, (attackers, cells) and (defenders, cells), by
    integrating Spearman's model from the ball's arrival time. A cell one side reaches far earlier skips the
    integration and goes to that side's first arrival, as in Spearman's implementation."""
    t_ball = np.linalg.norm(cells - ball_xy[None, :], axis=1) / BALL_SPEED
    tti_att = _time_to_intercept(att_pos, att_vel, cells)
    tti_def = _time_to_intercept(def_pos, def_vel, cells)
    scale = np.pi / np.sqrt(3.0) / TTI_SIGMA
    n_cells = cells.shape[0]
    ppcf_att = np.zeros((att_pos.shape[0], n_cells))
    ppcf_def = np.zeros((def_pos.shape[0], n_cells))
    tau_att = tti_att.min(axis=0)
    tau_def = tti_def.min(axis=0)
    time_to_control = 3.0 * np.log(10.0) * (np.sqrt(3.0) * TTI_SIGMA / np.pi + 1.0 / LAMBDA)
    att_wins = tau_def - np.maximum(t_ball, tau_att) >= time_to_control
    def_wins = tau_att - np.maximum(t_ball, tau_def) >= time_to_control
    total = np.zeros(n_cells)
    t = t_ball.copy() - dt
    steps = int(horizon / dt)
    for _ in range(steps):
        t = t + dt
        remaining = np.clip(1.0 - total, 0.0, 1.0)
        f_att = 1.0 / (1.0 + np.exp(-scale * (t[None, :] - tti_att)))
        f_def = 1.0 / (1.0 + np.exp(-scale * (t[None, :] - tti_def)))
        ppcf_att += remaining[None, :] * f_att * LAMBDA * dt
        ppcf_def += remaining[None, :] * f_def * LAMBDA * dt
        total = ppcf_att.sum(axis=0) + ppcf_def.sum(axis=0)
        if np.all(total > 0.99):
            break
    # Normalise so the two sides' shares sum to one, then hand the uncontested cells to their first arrival.
    norm = np.maximum(total, 1e-9)
    ppcf_att, ppcf_def = ppcf_att / norm, ppcf_def / norm
    for wins, mine, theirs, tti in ((att_wins, ppcf_att, ppcf_def, tti_att), (def_wins, ppcf_def, ppcf_att, tti_def)):
        if wins.any() and mine.shape[0]:
            mine[:, wins] = 0.0
            mine[tti[:, wins].argmin(axis=0), np.nonzero(wins)[0]] = 1.0
            theirs[:, wins] = 0.0
    return ppcf_att, ppcf_def


def control_spearman(att_pos: np.ndarray, att_vel: np.ndarray, def_pos: np.ndarray, def_vel: np.ndarray,
                     ball_xy: np.ndarray, cells: np.ndarray, dt: float = 0.04, horizon: float = 10.0) -> np.ndarray:
    """Attacking control per cell by integrating Spearman's model from the ball's arrival time."""
    return ppcf(att_pos, att_vel, def_pos, def_vel, ball_xy, cells, dt, horizon)[0].sum(axis=0)


def zone_mask(cells: np.ndarray, polygon: list[tuple[float, float]]) -> np.ndarray:
    """Cells whose centres lie inside an axis-aligned rectangle given as a 4-point polygon."""
    xs = [p[0] for p in polygon]
    ys = [p[1] for p in polygon]
    return (cells[:, 0] >= min(xs)) & (cells[:, 0] <= max(xs)) & (cells[:, 1] >= min(ys)) & (cells[:, 1] <= max(ys))


def zone_control(control: np.ndarray, cells: np.ndarray, polygon: list[tuple[float, float]]) -> float:
    """Mean attacking control over a zone, 0..1."""
    mask = zone_mask(cells, polygon)
    return float(control[mask].mean()) if mask.any() else 0.0


def controlled_area(control: np.ndarray, cells: np.ndarray, polygon: list[tuple[float, float]], cell_area: float) -> float:
    """Square metres of the zone the attacking team controls (control-weighted)."""
    mask = zone_mask(cells, polygon)
    return float(control[mask].sum() * cell_area)
