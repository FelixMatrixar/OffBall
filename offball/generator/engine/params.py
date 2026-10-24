"""Global engine parameters: the ~45 numbers calibration by simulation tunes (PRD 12.6).

Each field has a default and a search range. `calibration/params.json` overrides the defaults; the Tuner
agent picks which fields to search and within what bounds, and Optuna does the numeric search. Nothing
changes unless every quality gate passes.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

PARAMS_PATH = Path(__file__).resolve().parents[3] / "calibration" / "params.json"


def tunable(default: float, lo: float, hi: float, doc: str) -> float:
    return field(default=default, metadata={"lo": lo, "hi": hi, "doc": doc})


@dataclass
class EngineParams:
    # Possession value surface (the generator's hidden EPV).
    value_base: float = tunable(0.008, 0.004, 0.016, "Value of the ball anywhere")
    value_progress: float = tunable(0.06, 0.015, 0.1, "Weight of territorial progress")
    value_progress_mid: float = tunable(66.0, 58.0, 74.0, "x' where progress is half way, m")
    value_progress_scale: float = tunable(10.0, 6.0, 16.0, "Steepness of progress, m")
    value_xg_weight: float = tunable(0.5, 0.3, 0.8, "Weight of shot conversion from the spot")
    # Shots.
    xg_bias: float = tunable(-0.25, -0.8, 0.5, "Logit offset of the true xG model")
    shot_scale: float = tunable(1.0, 0.6, 1.3, "How much players value a shot against its xG")
    # Passing physics.
    intercept_tau: float = tunable(0.16, 0.1, 0.3, "Spread of the interception race, s")
    intercept_lead: float = tunable(0.2, 0.05, 0.35, "How early a defender must arrive to cut a pass out, s")
    pass_arrival: float = tunable(10.5, 8.0, 13.0, "Arrival speed of a ground pass, m/s")
    exec_base: float = tunable(0.008, 0.002, 0.03, "Base error rate of a pass")
    exec_long: float = tunable(0.2, 0.1, 0.35, "Growth of error with distance")
    exec_aerial: float = tunable(0.07, 0.02, 0.15, "Extra error for lofted passes")
    control_base: float = tunable(0.032, 0.015, 0.06, "Base miscontrol rate")
    control_aerial: float = tunable(2.2, 1.3, 3.0, "Miscontrol multiplier for dropping balls")
    # On-ball decisions.
    temperature: float = tunable(0.0015, 0.0005, 0.006, "Decision noise of the best decision-makers")
    temperature_vision: float = tunable(0.004, 0.001, 0.01, "Extra noise for poor vision")
    loss_base: float = tunable(0.012, 0.004, 0.03, "Cost of losing the ball, beyond the opponents' gain")
    held_pressure: float = tunable(0.35, 0.15, 0.6, "Value lost to pressure at the receiving spot")
    hold_risk: float = tunable(0.45, 0.25, 0.7, "Chance per unit pressure of being dispossessed when holding")
    clear_keep: float = tunable(0.42, 0.3, 0.55, "Chance a clearance stays with the team")
    long_pass_cost: float = tunable(0.0004, 0.0, 0.0015, "Dislike of long balls per metre beyond 25 m, scaled by (1.2 - directness)")
    # Dribbling and duels.
    carry_lead: float = tunable(0.25, 0.0, 0.5, "Slack a defender has to reach the dribbling line, s")
    carry_tau: float = tunable(0.3, 0.15, 0.5, "Spread of the dribbling race, s")
    carry_beat: float = tunable(0.35, 0.15, 0.55, "Base chance a dribbler beats a challenge")
    tackle_hazard: float = tunable(0.02, 0.008, 0.04, "Tackle attempts per tick when engaged")
    goal_side_boost: float = tunable(2.2, 1.0, 3.5, "Extra tackle attempts for a defender in the way")
    foul_base: float = tunable(0.2, 0.08, 0.35, "Share of challenges that are fouls")
    # Defensive shape.
    def_width: float = tunable(39.0, 32.0, 46.0, "Width of the block out of possession, m")
    def_depth: float = tunable(25.0, 20.0, 32.0, "Length of the block out of possession, m")
    box_squeeze_depth: float = tunable(9.0, 4.0, 14.0, "How much the block shortens defending the box, m")
    box_squeeze_width: float = tunable(10.0, 5.0, 16.0, "How much the block narrows defending the box, m")
    zone_radius: float = tunable(9.5, 7.0, 13.0, "Zonal marking radius, m")
    zone_radius_deep: float = tunable(12.5, 9.0, 16.0, "Marking radius near our own goal, m")
    box_engage: float = tunable(32.0, 24.0, 48.0, "Distance from goal where two defenders engage the ball, m")
    track_base: float = tunable(0.12, 0.0, 0.3, "Chance of tracking a harmless run regardless of discipline")
    track_discipline: float = tunable(0.72, 0.4, 0.9, "Effect of low discipline on tracking runners")
    track_danger: float = tunable(0.4, 0.2, 0.6, "Extra tracking for runs in behind")
    press_zone: float = tunable(40.0, 30.0, 50.0, "Pressing line of a low block, m from own goal")
    press_trigger: float = tunable(8.0, 5.0, 12.0, "Distance at which pressing starts, m")
    # Off-ball attacking movement.
    run_rate: float = tunable(0.12, 0.02, 0.25, "Chance a run in behind is found by a pass")
    support_base: float = tunable(0.006, 0.002, 0.012, "Structural value of offering support")
    decoy_scale: float = tunable(0.18, 0.08, 0.35, "Value players see in decoy runs")
    anchor_value: float = tunable(0.010, 0.006, 0.016, "Structural value of holding position")
    # Movement and fatigue.
    anchor_lag: float = tunable(0.9, 0.4, 1.6, "Reaction lag of the team shape, s")
    walk_gap: float = tunable(2.5, 1.0, 4.0, "Distance from position within which players walk, m")
    fatigue_drain: float = tunable(2.9e-4, 1.5e-4, 5e-4, "Energy drain from high-speed running")

    @classmethod
    def bounds(cls) -> dict[str, tuple[float, float, str]]:
        return {f.name: (f.metadata["lo"], f.metadata["hi"], f.metadata["doc"]) for f in fields(cls)}

    def with_overrides(self, **overrides: float) -> EngineParams:
        data = asdict(self)
        unknown = set(overrides) - set(data)
        if unknown:
            raise KeyError(f"Unknown engine parameters: {sorted(unknown)}")
        data.update(overrides)
        return EngineParams(**data)

    def to_json(self) -> dict[str, float]:
        return asdict(self)

    @classmethod
    def load(cls, path: Path = PARAMS_PATH) -> EngineParams:
        """Calibrated parameters if present, otherwise the defaults."""
        if not path.exists():
            return cls()
        raw = json.loads(path.read_text(encoding="utf-8"))
        values = raw.get("params", raw)
        known = {f.name for f in fields(cls)}
        return cls(**{k: float(v) for k, v in values.items() if k in known})


DEFAULT = EngineParams()
