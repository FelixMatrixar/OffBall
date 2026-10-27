"""OffBall command line.

    offball schemas                      Export JSON Schemas to contracts/
    offball league                       Build the league (public data + held-out truth)
    offball showcase                     Generate the showcase match, Kestrel Bay v Ashmoor
    offball match --home kes --away ash  Generate one emergent match from a seed
    offball smoke                        Generate the CI smoke set (every moment type, 13 short matches)
    offball bench [--only b001 b002]     Generate OffBall-Bench (100 full matches, answer keys, dev/test split)
    offball matchday --round 27          Play the showcase round: one planted moment a fixture, oracle labels
    offball season                       Play the 380-match season backdrop with the fast engine
    offball fit                          Fit realism targets and the fast engine from calibration/raw/
    offball blocklist                    Build the salted-hash name blocklist from calibration/raw/
    offball gates smoke|calib|<dir>      Run the nine quality gates and write their report
    offball serve api|mcp|all            Run the API (port 8000), the MCP server (port 8001), or both
    offball replay m07 --period 2 --from-ms 1225000 --to-ms 1252000
                                         Build a replay stream through the live pipeline and the crew
    offball graphics m07 [--limit 10]    Take every moment of a whole match through the crew, for the match player
    offball golden list|build|run        Golden render tests: list or build the cases, or run the pipeline on them
    offball golden check <case> --stream out.jsonl
                                         Check a pipeline's output stream against a case's expectations
    offball eval agents [--only factchecker scout persona]
                                         Evaluate each agent on its own task set (needs a model)
"""

from __future__ import annotations

import argparse
import json
import os
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


def _write_directed(script, data_root: Path, truth_root: Path, attempts: int, cf_runs: int,
                    oracle: bool = False, prepare=None) -> None:
    from offball.generator.director import play_script
    from offball.generator.league import build_league
    from offball.generator.writer import refresh_manifest, write_match

    league = build_league(2026)
    t0 = time.time()
    dm = play_script(league, script, counterfactual_runs=cf_runs, max_attempts=attempts)
    if prepare is not None:
        prepare(dm)
    key = [row.model_dump() for row in dm.answer_key]
    data_dir, truth_dir = data_root / script.match_id, truth_root / script.match_id
    manifest = write_match(dm.result, data_dir, truth_dir, round_=script.round, answer_key=key)
    if oracle:
        # Label the moments the players made on their own, from the decision log and the detectors' signals.
        from offball.generator.oracle import oracle_labels
        from offball.models.match_data import MatchData

        intents = [json.loads(line) for line in (truth_dir / "intents.jsonl").read_text(encoding="utf-8").splitlines()]
        key += [row.model_dump() for row in oracle_labels(MatchData.load(data_dir), intents, first_n=len(key) + 1)]
        (truth_dir / "answer_key.json").write_text(json.dumps(key, indent=1), encoding="utf-8", newline="\n")
        manifest = refresh_manifest(data_dir, truth_dir)
    report = {
        "match_id": script.match_id,
        "seconds": round(time.time() - t0, 1),
        "segment_retries": dm.segment_retries,
        "score": {t.club.club_id: t.score for t in dm.result.teams},
        "moments": [
            {"key": r.key, "type": r.type, "ok": r.ok, "attempts": r.attempts, "reasons": r.reasons[-10:]}
            for r in dm.reports
        ],
        "oracle_labels": sum(row.get("source") == "oracle" for row in key),
    }
    (truth_root / script.match_id / "director_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8",
                                                                       newline="\n")
    print(json.dumps(report, indent=2))
    print(f"{len(manifest)} files written")


def cmd_showcase(args: argparse.Namespace) -> None:
    from offball.generator.director import place_showcase_goal, showcase_script

    script = showcase_script()
    _write_directed(script, DATASETS / "showcase", TRUTH / "showcase", args.attempts, args.cf_runs,
                    prepare=place_showcase_goal)


def cmd_match(args: argparse.Namespace) -> None:
    from offball.generator.script import MatchScript

    script = MatchScript(match_id=args.match_id, home=args.home, away=args.away, seed=args.seed,
                         half_minutes=args.half)
    _write_directed(script, DATASETS / args.set, TRUTH / args.set, args.attempts, args.cf_runs)


def cmd_smoke(args: argparse.Namespace) -> None:
    from offball.generator.smoke import smoke_scripts

    scripts = smoke_scripts()
    # Each match is seeded on its own, so they can play in parallel and still come out the same.
    from concurrent.futures import ProcessPoolExecutor

    with ProcessPoolExecutor(max_workers=max(1, min(args.workers, len(scripts)))) as pool:
        jobs = [pool.submit(_write_directed, script, DATASETS / "smoke", TRUTH / "smoke", args.attempts, args.cf_runs)
                for script in scripts]
        for job in jobs:
            job.result()


def _play_set(scripts, name: str, workers: int, attempts: int, cf_runs: int, oracle_for) -> None:
    from concurrent.futures import ProcessPoolExecutor

    with ProcessPoolExecutor(max_workers=max(1, min(workers, len(scripts)))) as pool:
        jobs = [pool.submit(_write_directed, s, DATASETS / name, TRUTH / name, attempts, cf_runs, oracle_for(s))
                for s in scripts]
        for job in jobs:
            job.result()


def cmd_credit_set(args: argparse.Namespace) -> None:
    from offball.generator.trainset import credit_scripts

    scripts = credit_scripts(args.per_type, args.first)
    if args.only:
        scripts = [s for s in scripts if s.match_id in set(args.only)]
    _play_set(scripts, "credit", args.workers, args.attempts, args.cf_runs, lambda s: False)


def cmd_bench(args: argparse.Namespace) -> None:
    from offball.generator.bench import bench_scripts
    from offball.generator.league import build_league

    scripts, split = bench_scripts(build_league(2026), matches=args.matches)
    if args.only:
        scripts = [s for s in scripts if s.match_id in set(args.only)]
    (DATASETS / "bench").mkdir(parents=True, exist_ok=True)
    (DATASETS / "bench" / "split.json").write_text(json.dumps(split, indent=1), encoding="utf-8", newline="\n")
    # Unscripted matches carry oracle labels only; every match also gets any the players made on their own.
    _play_set(scripts, "bench", args.workers, args.attempts, args.cf_runs, lambda s: True)


def cmd_matchday(args: argparse.Namespace) -> None:
    from offball.generator.bench import matchday_scripts
    from offball.generator.league import build_league

    scripts = matchday_scripts(build_league(2026), round_=args.round)
    if args.only:
        scripts = [s for s in scripts if s.match_id in set(args.only)]
    _play_set(scripts, "matchday", args.workers, args.attempts, args.cf_runs, lambda s: True)
    # Kestrel Bay v Ashmoor is the showcase match.
    if args.round == 27 and (DATASETS / "showcase" / "m07").exists():
        import shutil

        for root in (DATASETS, TRUTH):
            shutil.copytree(root / "showcase" / "m07", root / "matchday" / "m07", dirs_exist_ok=True)


def cmd_season(args: argparse.Namespace) -> None:
    from offball.generator.fast import play_season
    from offball.generator.league import build_league

    t0 = time.time()
    table = play_season(build_league(2026), DATASETS / "season", seed=args.seed)
    leader = next(iter(sorted(table.items(), key=lambda kv: (-kv[1][6], kv[1][5] - kv[1][4]))))
    print(f"{sum(r[0] for r in table.values()) // 2} matches in {time.time() - t0:.0f} s -> {DATASETS / 'season'}; "
          f"top of the table: {leader[0]} on {leader[1][6]} points")


def _tracing() -> None:
    """Traces of every agent hop, where the environment says (offball.services.telemetry)."""
    from offball.services.telemetry import setup_tracing

    where = setup_tracing()
    if where != "off":
        print(f"Traces go to {where}")


def cmd_serve(args: argparse.Namespace) -> None:
    import asyncio
    import logging

    import uvicorn

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    os.environ.setdefault("OFFBALL_WARM", "m07")  # the showcase's moments are ready before the first question
    _tracing()

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


def cmd_graphics(args: argparse.Namespace) -> None:
    import asyncio
    import logging

    from offball.agents.crew import Crew
    from offball.agents.llm import model_configured
    from offball.mcp.tools import REGISTRY
    from offball.services.fullmatch import build_graphics

    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    _tracing()
    if args.match_id not in REGISTRY.match_dirs():
        sys.exit(f"Unknown match {args.match_id}")
    if not model_configured():
        sys.exit("Graphics come only from the crew, and no model is configured. See .env.example.")
    started = time.monotonic()
    done = [0]

    def progress(cid: str, kept: dict) -> None:
        done[0] += 1
        print(f"{done[0]:4d}  {cid}  {kept['status']:9}  {len(kept['overlay_ids']):3d} graphics  "
              f"{kept['tokens'] / 1e6:6.2f}M tokens  {time.monotonic() - started:6.0f} s  {kept['note'][:70]}",
              flush=True)

    state = asyncio.run(build_graphics(Crew.from_env(), args.match_id, args.concurrency, args.limit, args.redo,
                                       args.tokens, args.min_gap, progress))
    print(f"{done[0]} moments, {state.tokens.used / 1e6:.2f}M tokens, {time.monotonic() - started:.0f} s")


def cmd_replay(args: argparse.Namespace) -> None:
    import asyncio
    import logging

    from offball.agents.crew import Crew
    from offball.agents.llm import model_configured
    from offball.mcp.tools import REGISTRY
    from offball.services.emitter import EmitterConfig
    from offball.services.replay import build_replay

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    _tracing()
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


def cmd_golden(args: argparse.Namespace) -> None:
    from offball.eval import golden

    names = args.cases or list(golden.CASES)
    unknown = [n for n in names if n not in golden.CASES]
    if unknown:
        sys.exit(f"Unknown case {', '.join(unknown)}; known: {', '.join(golden.CASES)}")
    if args.action == "list":
        for name, (set_name, match_id, kind, outcome) in golden.CASES.items():
            print(f"{name:20} {set_name}/{match_id}  {kind}{' (' + outcome + ')' if outcome else ''}")
        return
    if args.action == "build":
        for name in golden.build(names):
            print(f"{name} -> {DATASETS / 'golden' / name}, {TRUTH / 'golden' / name / 'expected.json'}")
        return
    reports = []
    if args.action == "check":
        if len(names) != 1 or not args.stream:
            sys.exit("offball golden check <case> --stream <output.jsonl>")
        reports.append(golden.check(golden.load_case(names[0]), golden.load_stream(Path(args.stream))))
    else:
        import logging

        from offball.agents.crew import Crew
        from offball.agents.llm import model_configured

        logging.basicConfig(level=logging.WARNING)
        _tracing()
        if not model_configured():
            print("No model is configured, so the crew is off and the pipeline airs nothing. See .env.example.")
        crew = Crew.from_env() if model_configured() else None
        for name in names:
            reports.append(golden.run(name, crew, ROOT / "replays" / "golden" / f"{name}.jsonl"))
    for r in reports:
        print(r.text())
    if args.json:
        Path(args.json).write_text(json.dumps([r.to_dict() for r in reports], indent=1) + "\n", encoding="utf-8",
                                   newline="\n")
    print(f"{sum(r.passed for r in reports)} of {len(reports)} case(s) pass")
    if not all(r.passed for r in reports):
        sys.exit(1)


def cmd_eval(args: argparse.Namespace) -> None:
    import asyncio
    import logging

    from offball.agents.crew import Crew
    from offball.agents.llm import ModelSettings, model_configured
    from offball.eval import agents

    logging.basicConfig(level=logging.WARNING)
    if not model_configured():
        sys.exit("Evaluating the agents needs a model. See .env.example.")
    _tracing()
    settings = ModelSettings.from_env()
    crew = Crew.from_env()
    results = asyncio.run(agents.run_all(crew, args.only or None, args.smoke or None))
    timing = crew.telemetry.summary(window_s=24 * 3600)
    for r in results:
        print(r.text())
    for agent, t in sorted(timing.items()):
        print(f"{agent}: {t['calls']} calls, p95 {t['p95_ms']:,} ms (budget {t['budget_ms']:,} ms)")
    out = ROOT / "calibration" / "reports" / "agents.md"
    models = ", ".join(f"{settings.deployment(t)}" + (f" at {e} effort" if (e := settings.effort(t)) else "")
                       + (f", up to {n:,} tokens" if (n := settings.max_tokens(t)) else "") + f" ({t})"
                       for t in ("fast", "reasoning"))
    out.write_text(agents.report(results, models, timing), encoding="utf-8", newline="\n")
    print(f"Report -> {out}")
    if not all(r.passed for r in results):
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
    p.add_argument("--attempts", type=int, default=150, help="Attempts per moment (goal moments get twice as many)")
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
    p.add_argument("--workers", type=int, default=13)
    p.add_argument("--cf-runs", type=int, default=8)
    p.set_defaults(fn=cmd_smoke)
    p = sub.add_parser("credit-set", help="Play the credit training split: short directed matches, each type "
                                          "planted several times with true counterfactual credit")
    p.add_argument("--per-type", type=int, default=5)
    p.add_argument("--first", type=int, default=1, help="Number (and seed) the batch from here, after earlier ones")
    p.add_argument("--only", nargs="*", help="Play only these match ids (e.g. crd001)")
    p.add_argument("--workers", type=int, default=14)
    p.add_argument("--attempts", type=int, default=40)
    p.add_argument("--cf-runs", type=int, default=8)
    p.set_defaults(fn=cmd_credit_set)
    p = sub.add_parser("bench", help="Generate OffBall-Bench: 100 full matches with answer keys, dev/test split")
    p.add_argument("--matches", type=int, default=100)
    p.add_argument("--only", nargs="*", help="Generate only these match ids (e.g. b001 b002)")
    p.add_argument("--workers", type=int, default=15)
    p.add_argument("--attempts", type=int, default=30)
    p.add_argument("--cf-runs", type=int, default=8)
    p.set_defaults(fn=cmd_bench)
    p = sub.add_parser("matchday", help="Play the showcase round: one planted moment a fixture, with oracle labels")
    p.add_argument("--round", type=int, default=27)
    p.add_argument("--only", nargs="*", help="Play only these match ids (e.g. s27-06)")
    p.add_argument("--workers", type=int, default=10)
    p.add_argument("--attempts", type=int, default=60)
    p.add_argument("--cf-runs", type=int, default=8)
    p.set_defaults(fn=cmd_matchday)
    p = sub.add_parser("season", help="Play the 380-match season backdrop with the fast engine (events only)")
    p.add_argument("--seed", type=int, default=2026)
    p.set_defaults(fn=cmd_season)
    p = sub.add_parser("eval", help="Evaluate each agent on its own task set against a real model (PRD 14.15)")
    p.add_argument("what", choices=["agents"])
    p.add_argument("--only", nargs="*", choices=["factchecker", "scout", "persona"])
    p.add_argument("--smoke", nargs="*", help="Smoke matches for the Scout and Fact-checker sets (default: all)")
    p.set_defaults(fn=cmd_eval)
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
    p = sub.add_parser("graphics", help="Take every moment of a whole match through the crew")
    p.add_argument("match_id")
    p.add_argument("--concurrency", type=int, default=4, help="Moments in the crew at once")
    p.add_argument("--limit", type=int, help="Stop after this many moments")
    p.add_argument("--redo", action="store_true", help="Explain moments again even if a build already did")
    p.add_argument("--tokens", type=int, default=20_000_000, help="The build's token budget")
    p.add_argument("--min-gap", type=int, help="The Scout's minimum spacing between graphics, in seconds (60)")
    p.set_defaults(fn=cmd_graphics)
    p = sub.add_parser("golden", help="Golden render tests: build the cases, run the pipeline on them, check a stream")
    p.add_argument("action", choices=["list", "build", "run", "check"])
    p.add_argument("cases", nargs="*", help="Case names; all of them when left out")
    p.add_argument("--stream", help="For check: the pipeline's output stream, one message a line")
    p.add_argument("--json", help="Also write the report as JSON to this file")
    p.set_defaults(fn=cmd_golden)
    args = ap.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
