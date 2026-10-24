"""OffBall command line.

    offball schemas                      Export JSON Schemas to contracts/
    offball league                       Build the league (public data + held-out truth)
    offball showcase                     Generate the showcase match, Kestrel Bay v Ashmoor
    offball match --home kes --away ash  Generate one emergent match from a seed
    offball smoke                        Generate the CI smoke set
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATASETS = ROOT / "datasets"
TRUTH = ROOT / "truth"


def cmd_schemas(args: argparse.Namespace) -> None:
    from offball.contracts import export_schemas

    files = export_schemas(ROOT / "contracts")
    print(f"Wrote {len(files)} schemas to {ROOT / 'contracts'}")


def cmd_league(args: argparse.Namespace) -> None:
    from offball.generator.league import build_league

    league = build_league(args.seed)
    league.save(DATASETS / "league", TRUTH / "league")
    print(f"League built from seed {args.seed}: {len(league.clubs)} clubs, {len(league.fixtures)} fixtures")


def _write_directed(script, data_root: Path, truth_root: Path, attempts: int, cf_runs: int) -> None:
    from offball.generator.director import play_script
    from offball.generator.league import build_league
    from offball.generator.writer import write_match

    league = build_league(2026)
    t0 = time.time()
    dm = play_script(league, script, counterfactual_runs=cf_runs, max_attempts=attempts)
    key = [row.model_dump() for row in dm.answer_key]
    manifest = write_match(dm.result, data_root / script.match_id, truth_root / script.match_id,
                           round_=script.round, answer_key=key)
    report = {
        "match_id": script.match_id,
        "seconds": round(time.time() - t0, 1),
        "segment_retries": dm.segment_retries,
        "score": {t.club.club_id: t.score for t in dm.result.teams},
        "moments": [
            {"key": r.key, "type": r.type, "ok": r.ok, "attempts": r.attempts, "reasons": r.reasons[-10:]}
            for r in dm.reports
        ],
    }
    (truth_root / script.match_id / "director_report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    print(f"{len(manifest)} files written")


def cmd_showcase(args: argparse.Namespace) -> None:
    from offball.generator.director import showcase_script

    script = showcase_script()
    _write_directed(script, DATASETS / "showcase", TRUTH / "showcase", args.attempts, args.cf_runs)


def cmd_match(args: argparse.Namespace) -> None:
    from offball.generator.script import MatchScript

    script = MatchScript(match_id=args.match_id, home=args.home, away=args.away, seed=args.seed,
                         half_minutes=args.half)
    _write_directed(script, DATASETS / args.set, TRUTH / args.set, args.attempts, args.cf_runs)


def cmd_smoke(args: argparse.Namespace) -> None:
    from offball.generator.script import MatchScript, StoryMoment

    scripts = [
        MatchScript(match_id="smk1", home="kes", away="ash", seed=101, half_minutes=5,
                    moments=[StoryMoment(key="k01", type="decoy_run", team="kes", minute=2.0, outcome="chance")]),
        MatchScript(match_id="smk2", home="bra", away="sal", seed=102, half_minutes=5,
                    moments=[StoryMoment(key="k01", type="null_run", team="bra", minute=6.0)]),
        MatchScript(match_id="smk3", home="nor", away="oak", seed=103, half_minutes=5,
                    moments=[StoryMoment(key="k01", type="decoy_run", team="nor", minute=2.0, outcome="chance")]),
    ]
    for script in scripts:
        _write_directed(script, DATASETS / "smoke", TRUTH / "smoke", args.attempts, args.cf_runs)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="offball", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("schemas").set_defaults(fn=cmd_schemas)
    p = sub.add_parser("league")
    p.add_argument("--seed", type=int, default=2026)
    p.set_defaults(fn=cmd_league)
    p = sub.add_parser("showcase")
    p.add_argument("--attempts", type=int, default=75, help="Attempts per moment (goal moments get twice as many)")
    p.add_argument("--cf-runs", type=int, default=16)
    p.set_defaults(fn=cmd_showcase)
    p = sub.add_parser("match")
    p.add_argument("--match-id", required=True)
    p.add_argument("--home", required=True)
    p.add_argument("--away", required=True)
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--half", type=float, default=45.0)
    p.add_argument("--set", default="adhoc")
    p.add_argument("--attempts", type=int, default=30)
    p.add_argument("--cf-runs", type=int, default=8)
    p.set_defaults(fn=cmd_match)
    p = sub.add_parser("smoke")
    p.add_argument("--attempts", type=int, default=40)
    p.add_argument("--cf-runs", type=int, default=8)
    p.set_defaults(fn=cmd_smoke)
    args = ap.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
