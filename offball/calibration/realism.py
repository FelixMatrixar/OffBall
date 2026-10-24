"""How realistic the engine is right now: fresh matches across different club pairings, scored against the
fitted targets (PRD 12.6). The Tuner and the realism gate read the same numbers.

    uv run offball realism --matches 16 --half 45
"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from offball.calibration.metrics import deviation, loss, targets
from offball.calibration.tune import evaluate
from offball.generator.engine.params import EngineParams


def table(metrics: dict[str, float]) -> str:
    lines = [f"{'metric':20} {'engine':>10}   {'real middle half':>22}   status", "-" * 70]
    for name, t in targets().items():
        if name not in metrics:
            continue
        d = deviation(metrics[name], t)
        status = "ok" if d == 0 else f"out by {d:.2f} bands"
        lines.append(f"{name:20} {metrics[name]:10.3f}   {t.lo:10.3f} – {t.hi:9.3f}   {status}")
    lines.append(f"loss {loss(metrics):.3f}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="offball realism")
    ap.add_argument("--matches", type=int, default=16)
    ap.add_argument("--half", type=float, default=45.0)
    ap.add_argument("--workers", type=int, default=15)
    ap.add_argument("--seed", type=int, default=500)
    ap.add_argument("--defaults", action="store_true", help="score the engine defaults, not the calibrated params")
    ap.add_argument("--params", type=Path, help="score a candidate parameter file instead of calibration/params.json")
    args = ap.parse_args(argv)
    base = EngineParams() if args.defaults else EngineParams.load(args.params) if args.params else EngineParams.load()
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        metrics = evaluate({}, args.matches, args.half, pool, seed0=args.seed, base=base)
    print(table(metrics))


if __name__ == "__main__":
    main()
