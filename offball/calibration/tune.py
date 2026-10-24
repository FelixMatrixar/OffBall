"""Calibration by simulation (PRD 12.6): an optimizer searches engine parameters against realism targets.

The Tuner agent proposes a hypothesis and chooses which parameters to search and within what bounds; this
module does the numeric search with Optuna. Each trial plays short matches across different club styles in
parallel and scores them against the target bands. The model never does the arithmetic.

    uv run python -m offball.calibration.tune --trials 60 --matches 8
"""

from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from pathlib import Path

import optuna

from offball.calibration.metrics import deviation, loss, match_metrics, summarise, targets
from offball.generator.engine.params import PARAMS_PATH, EngineParams

PAIRINGS = [("kes", "ash"), ("bra", "sal"), ("mor", "qua"), ("nor", "oak"), ("fen", "gle"), ("cor", "wre"),
            ("dun", "lar"), ("har", "ive"), ("jun", "low"), ("pel", "riv")]

# The Tuner's current hypothesis, against targets fitted to real matches: shots still come about twice as
# often as in real football, possessions last too long, and players cover too little ground at a jog while
# running too much of it at high speed. Search chance creation, turnovers, balls out of play and pace.
HYPOTHESIS = ("Shots about 2x real, possessions too long, too little jogging and too much high-speed running: "
              "search chance creation, turnovers, balls out of play and movement pace together.")
DEFAULT_SEARCH = [
    # Chances and shots.
    "shot_scale", "value_progress", "value_xg_weight", "xg_bias", "long_shot_appeal", "cross_delivery",
    "cross_free", "header_shot",
    # Defending the box and winning the ball.
    "box_engage", "def_width", "def_depth", "box_squeeze_depth", "zone_radius_deep", "carry_beat", "carry_lead",
    "tackle_hazard", "goal_side_boost", "foul_base",
    # Turnovers and balls out of play.
    "intercept_lead", "exec_long", "control_base", "temperature", "hold_risk", "run_rate", "wide_tackle_out",
    "clear_to_touch", "deflect_out", "touch_out", "header_behind",
    # Movement pace.
    "walk_gap", "anchor_lag", "pace_walk_cap", "pace_shape_horizon", "pace_shape_cap", "pace_transition_cap",
    "pace_mark_gain", "pace_mark_cap", "pace_press_base", "pace_support_cap", "drift_sd", "drift_period",
]


def play_one(args: tuple[dict, int, float]) -> dict[str, float]:
    values, seed, half = args
    from offball.generator.engine.sim import Simulator
    from offball.generator.league import build_league

    league = build_league(2026)
    home, away = PAIRINGS[seed % len(PAIRINGS)]
    sim = Simulator(league, home, away, f"cal{seed}", seed=seed, half_minutes=half, params=EngineParams(**values))
    return match_metrics(sim.play())


def evaluate(overrides: dict, matches: int, half: float, pool: ProcessPoolExecutor, seed0: int = 100,
             base: EngineParams | None = None) -> dict:
    """Average metrics of fresh matches, playing `overrides` on top of `base` (the calibrated parameters the
    generator uses, unless given)."""
    values = asdict((base or EngineParams.load()).with_overrides(**overrides))
    rows = list(pool.map(play_one, [(values, seed0 + k, half) for k in range(matches)]))
    return summarise(rows)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=60)
    ap.add_argument("--matches", type=int, default=8)
    ap.add_argument("--half", type=float, default=15.0)
    ap.add_argument("--workers", type=int, default=14)
    ap.add_argument("--search", nargs="*", default=DEFAULT_SEARCH)
    ap.add_argument("--out", type=Path, default=PARAMS_PATH)
    ap.add_argument("--log", type=Path, default=PARAMS_PATH.parent / "reports" / "tuning-log.jsonl")
    args = ap.parse_args()

    bounds = EngineParams.bounds()
    base = EngineParams.load(args.out)
    args.log.parent.mkdir(parents=True, exist_ok=True)
    pool = ProcessPoolExecutor(max_workers=args.workers)

    baseline = evaluate({}, args.matches, args.half, pool, base=base)
    print(f"baseline loss {loss(baseline):.3f}", flush=True)

    def objective(trial: optuna.Trial) -> float:
        overrides = {name: trial.suggest_float(name, bounds[name][0], bounds[name][1]) for name in args.search}
        t0 = time.time()
        metrics = evaluate(overrides, args.matches, args.half, pool, base=base)
        value = loss(metrics)
        record = {"trial": trial.number, "loss": value, "secs": round(time.time() - t0, 1),
                  "metrics": {k: round(v, 3) for k, v in metrics.items()}, "params": overrides}
        with args.log.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
        print(f"trial {trial.number:3d} loss {value:7.3f}  shots {metrics['shots']:5.1f} goals {metrics['goals']:4.1f}"
              f" passes {metrics['passes']:6.0f} completion {metrics['completion']:.2f}", flush=True)
        return value

    study = optuna.create_study(direction="minimize", sampler=optuna.samplers.TPESampler(seed=7, multivariate=True))
    study.enqueue_trial({name: getattr(base, name) for name in args.search})
    study.optimize(objective, n_trials=args.trials)

    best = base.with_overrides(**study.best_params)
    confirm = evaluate(study.best_params, args.matches * 2, args.half, pool, seed0=900, base=base)
    pool.shutdown()
    report = {
        "best_loss": study.best_value,
        "confirm_loss": loss(confirm),
        "baseline_loss": loss(baseline),
        "trials": len(study.trials),
        "hypothesis": HYPOTHESIS,
        "searched": args.search,
        "metrics": {k: round(v, 3) for k, v in confirm.items()},
        "outside_band": {k: round(deviation(confirm[k], t), 3) for k, t in targets().items()
                         if deviation(confirm[k], t) > 0},
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({"params": asdict(best), "report": report}, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)


if __name__ == "__main__":
    main()
