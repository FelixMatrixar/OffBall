"""Global engine parameters: the 80 numbers calibration by simulation tunes (PRD 12.6).

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
    long_shot_appeal: float = tunable(0.006, 0.0, 0.02, "Extra appeal of a shot from outside the box for a good finisher")
    # Crosses and headers.
    cross_delivery: float = tunable(0.66, 0.5, 0.85, "Chance an average crosser beats the first man and finds the box")
    cross_free: float = tunable(0.6, 0.35, 0.85, "Chance an uncontested target wins the ball in the air")
    cross_contest: float = tunable(4.5, 3.0, 6.0, "Distance within which defenders contest a cross, m")
    header_shot: float = tunable(0.5, 0.3, 0.7, "Chance a won header in the box goes at goal")
    header_behind: float = tunable(0.3, 0.15, 0.5, "Chance a defender's header from a cross goes behind")
    # Balls out of play.
    wide_tackle_out: float = tunable(0.45, 0.1, 0.8, "Chance a tackle won near the touchline puts the ball out")
    clear_to_touch: float = tunable(0.55, 0.2, 0.85, "Chance a clearance from a wide area goes out of touch")
    deflect_out: float = tunable(0.4, 0.1, 0.7, "Chance a pass cut out near the touchline is deflected out")
    touch_out: float = tunable(0.5, 0.2, 0.8, "Chance a misplaced ball near the touchline runs out of play")
    loose_control: float = tunable(4.0, 2.5, 6.0, "Ball speed a player stops cleanly in one touch, m/s")
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
    offside_misread: float = tunable(0.08, 0.02, 0.8, "Chance a passer with no vision misreads a teammate's offside position")
    offside_read_lag: float = tunable(0.0, 0.0, 0.5, "How out of date a passer's read of a runner against the line is, s")
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
    def_ball_shift: float = tunable(0.5, 0.3, 0.85, "How far the block slides across towards the ball")
    # Shape in possession.
    att_width: float = tunable(44.0, 34.0, 52.0, "Width of the shape in possession before the club's style, m")
    att_ball_shift: float = tunable(0.18, 0.05, 0.5, "How far the shape in possession slides towards the ball")
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
    # Movement pace: how fast players choose to move, as a share of their top speed (fitted against real
    # distance, high-intensity running and peak speeds).
    pace_walk_cap: float = tunable(0.18, 0.1, 0.35, "Fastest walk while in position")
    pace_shape_horizon: float = tunable(3.5, 2.0, 5.0, "Seconds a player takes to jog back into shape")
    pace_shape_cap: float = tunable(0.5, 0.35, 0.65, "Fastest jog back into shape")
    pace_transition_cap: float = tunable(0.75, 0.6, 0.92, "Fastest recovery run after losing the ball")
    pace_mark_gain: float = tunable(0.5, 0.2, 1.0, "How hard a marker closes a gap, m/s per m")
    pace_mark_cap: float = tunable(0.65, 0.5, 0.8, "Fastest pace while marking")
    pace_press_base: float = tunable(0.68, 0.55, 0.85, "Pace of a pressing run before the club's intensity")
    pace_support_cap: float = tunable(0.6, 0.4, 0.75, "Fastest pace offering support")
    pace_sprint_cap: float = tunable(0.92, 0.75, 1.0, "Share of top speed even an all-out sprint reaches")
    pace_chase_cap: float = tunable(0.9, 0.65, 1.0, "Fastest pace chasing a loose ball")
    accel_scale: float = tunable(1.0, 0.2, 1.0, "Share of a player's acceleration used for ordinary changes of pace")
    accel_effort_exp: float = tunable(2.0, 1.0, 6.0, "How steeply the share rises to full acceleration with effort")
    move_tau: float = tunable(0.0, 0.0, 0.8, "How smoothly a player eases into a new direction and pace, s")
    drift_sd: float = tunable(2.0, 1.0, 6.0, "How far players drift around their spot in the shape, m")
    drift_period: float = tunable(6.0, 2.0, 10.0, "How often a player picks a new spot to drift to, s")
    # Stoppages: the ball is out of play for about 44% of a real match.
    restart_delay_scale: float = tunable(1.0, 0.8, 2.0, "How long restarts take, against the base delays")
    setpiece_pace: float = tunable(0.17, 0.1, 0.3, "Pace players walk into position at a restart")
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
