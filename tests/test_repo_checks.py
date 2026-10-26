"""Repository checks that CI runs on every change (PRD 18.13): the published schemas match the code (BE-1), and no
live-pipeline module can reach the held-out truth (BE-6, AI-4)."""

from __future__ import annotations

import ast
from pathlib import Path

from offball.contracts import export_schemas

ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "contracts"
# Everything that runs live or reaches an agent. The generator writes truth and the evaluator reads it, by design.
LIVE = ["offball/services", "offball/agents", "offball/mcp", "offball/models"]
# Models train on synthetic truth and are validated on it (PRD 13); only their training script reads it.
ALLOWED = {"offball/models/train.py"}
TRUTH_MODELS = {"AnswerKeyMoment", "CounterfactualTruth", "Intent", "TrueProbability"}


def test_the_published_schemas_match_the_code(tmp_path) -> None:
    export_schemas(tmp_path)
    exported = {p.relative_to(tmp_path).as_posix(): p.read_bytes() for p in tmp_path.rglob("*.json")}
    published = {p.relative_to(CONTRACTS).as_posix(): p.read_bytes() for p in CONTRACTS.rglob("*.json")}
    assert sorted(exported) == sorted(published), "run `uv run offball schemas` and commit contracts/"
    stale = [name for name in exported if exported[name] != published[name]]
    assert not stale, f"out of date, run `uv run offball schemas`: {stale}"


def _truth_uses(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module == "offball.contracts.truth":
                found.append(f"line {node.lineno}: imports offball.contracts.truth")
            elif node.module == "offball.contracts":
                found += [f"line {node.lineno}: imports {a.name}" for a in node.names if a.name in TRUTH_MODELS]
        elif isinstance(node, ast.Import):
            found += [f"line {node.lineno}: imports {a.name}" for a in node.names if a.name == "offball.contracts.truth"]
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            v = node.value.replace("\\", "/")
            if v == "truth" or v.startswith("truth/") or "/truth/" in v:
                found.append(f"line {node.lineno}: names the truth folder ({node.value!r})")
    return found


def test_nothing_live_reaches_the_truth() -> None:
    problems = []
    for folder in LIVE:
        for path in sorted((ROOT / folder).rglob("*.py")):
            rel = path.relative_to(ROOT).as_posix()
            if rel not in ALLOWED:
                problems += [f"{rel} {p}" for p in _truth_uses(path)]
    assert not problems, "\n".join(problems)


def test_the_truth_check_catches_a_leak(tmp_path) -> None:
    leak = tmp_path / "leak.py"
    leak.write_text('from offball.contracts import Intent\nKEY = ROOT / "truth" / "showcase"\n', encoding="utf-8")
    assert len(_truth_uses(leak)) == 2
