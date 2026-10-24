"""OffBall command line.

    offball schemas                      Export JSON Schemas to contracts/
    offball league                       Build the league (public data + held-out truth)
    offball showcase                     Generate the showcase match, Kestrel Bay v Ashmoor
    offball match --home kes --away ash  Generate one emergent match from a seed
    offball smoke                        Generate the CI smoke set
    offball serve api|mcp|all            Run the API (port 8000), the MCP server (port 8001), or both
    offball replay m07 --period 2 --from-ms 1225000 --to-ms 1252000
                                         Build a replay stream through the live pipeline and the crew
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
    (truth_root / script.match_id / "director_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8",
                                                                       newline="\n")
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
        MatchScript(match_id="smk1", home="dun", away="lar", seed=113, half_minutes=5,
                    moments=[StoryMoment(key="k01", type="decoy_run", team="dun", minute=2.0, outcome="chance")]),
        MatchScript(match_id="smk2", home="bra", away="sal", seed=102, half_minutes=5,
                    moments=[StoryMoment(key="k01", type="null_run", team="bra", minute=6.0)]),
        MatchScript(match_id="smk3", home="nor", away="oak", seed=103, half_minutes=5,
                    moments=[StoryMoment(key="k01", type="decoy_run", team="nor", minute=2.0, outcome="chance")]),
        MatchScript(match_id="smk4", home="kes", away="ash", seed=104, half_minutes=5,
                    moments=[StoryMoment(key="k01", type="overlap", team="kes", minute=1.5, outcome="chance")]),
        MatchScript(match_id="smk5", home="kes", away="ash", seed=125, half_minutes=5,
                    moments=[StoryMoment(key="k01", type="null_overlap", team="kes", minute=1.5)]),
        MatchScript(match_id="smk6", home="har", away="ive", seed=106, half_minutes=5,
                    moments=[StoryMoment(key="k01", type="timed_run_in_behind", team="har", minute=1.5,
                                         outcome="chance")]),
    ]
    # Each match is seeded on its own, so they can play in parallel and still come out the same.
    from concurrent.futures import ProcessPoolExecutor

    with ProcessPoolExecutor(max_workers=max(1, min(args.workers, len(scripts)))) as pool:
        jobs = [pool.submit(_write_directed, script, DATASETS / "smoke", TRUTH / "smoke", args.attempts, args.cf_runs)
                for script in scripts]
        for job in jobs:
            job.result()


def cmd_serve(args: argparse.Namespace) -> None:
    import asyncio
    import logging

    import uvicorn

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

    async def run() -> None:
        servers = []
        if args.what in ("api", "all"):
            from offball.services.api import app

            servers.append(uvicorn.Server(uvicorn.Config(app, host=args.host, port=args.port, log_level="info")))
        if args.what in ("mcp", "all"):
            from offball.mcp.server import build_server

            mcp_app = build_server(args.host, args.mcp_port).streamable_http_app()
            servers.append(uvicorn.Server(uvicorn.Config(mcp_app, host=args.host, port=args.mcp_port,
                                                         log_level="info")))
        await asyncio.gather(*(s.serve() for s in servers))

    asyncio.run(run())


def cmd_replay(args: argparse.Namespace) -> None:
    import asyncio
    import logging

    from offball.agents.crew import Crew
    from offball.agents.llm import model_configured
    from offball.mcp.tools import REGISTRY
    from offball.services.emitter import EmitterConfig
    from offball.services.replay import build_replay

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    dirs = REGISTRY.match_dirs()
    if args.match_id not in dirs:
        sys.exit(f"Unknown match {args.match_id}; known: {', '.join(dirs)}")
    if not model_configured():
        print("No model is configured, so the crew is off and the replay has no graphics. See .env.example.")
    crew = Crew.from_env() if model_configured() else None
    out = Path(args.out) if args.out else ROOT / "replays" / f"{args.match_id}.jsonl"
    config = EmitterConfig(period=args.period, from_ms=args.from_ms, to_ms=args.to_ms)
    result = asyncio.run(build_replay(dirs[args.match_id], config, crew, out))
    print(f"{result.messages} messages, {result.overlays} graphics -> {result.path}")
    for o in result.outcomes:
        print(f"  {o.candidate_id}: {o.status} {o.note}")
    if result.invalid:
        print(f"{len(result.invalid)} messages don't match the contracts:")
        print("\n".join(result.invalid[:20]))
        sys.exit(1)


def cmd_fit(args: argparse.Namespace) -> None:
    from offball.calibration import fit

    fit.main()


def cmd_blocklist(args: argparse.Namespace) -> None:
    from offball.calibration.blocklist import build
    from offball.generator.names import BLOCKLIST_PATH

    print(f"{build()} hashes -> {BLOCKLIST_PATH}")


def cmd_gates(args: argparse.Namespace) -> None:
    from offball.calibration import gates

    results = gates.run(args.set)
    n = len(gates.load_set(args.set))
    text = gates.report(args.set, results, n)
    gates.REPORTS.mkdir(parents=True, exist_ok=True)
    name = Path(args.set).name
    (gates.REPORTS / f"gates-{name}.md").write_text(text, encoding="utf-8")
    if args.json:
        rows = [{"gate": g.number, "name": g.name, "status": g.status, "summary": g.summary, "numbers": g.numbers}
                for g in results]
        (gates.REPORTS / f"gates-{name}.json").write_text(json.dumps(rows, indent=1, default=str), encoding="utf-8",
                                                          newline="\n")
    print(text)
    if any(g.status == "fail" for g in results):
        sys.exit(1)


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
    p.add_argument("--workers", type=int, default=6)
    p.add_argument("--cf-runs", type=int, default=8)
    p.set_defaults(fn=cmd_smoke)
    sub.add_parser("fit").set_defaults(fn=cmd_fit)
    sub.add_parser("blocklist").set_defaults(fn=cmd_blocklist)
    p = sub.add_parser("gates")
    p.add_argument("set", help="A dataset folder under datasets/ (showcase, smoke) or a match folder")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_gates)
    p = sub.add_parser("serve")
    p.add_argument("what", choices=["api", "mcp", "all"], nargs="?", default="all")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--mcp-port", type=int, default=8001)
    p.set_defaults(fn=cmd_serve)
    p = sub.add_parser("replay")
    p.add_argument("match_id")
    p.add_argument("--period", type=int)
    p.add_argument("--from-ms", type=int, default=0)
    p.add_argument("--to-ms", type=int)
    p.add_argument("--out")
    p.set_defaults(fn=cmd_replay)
    args = ap.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
