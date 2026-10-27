"""Evaluating each agent on its own (PRD 14.15), before the crew is scored as a whole (section 19).

- Fact-checker: drafts built from the metric tools, so every claim in them is right, and copies with one planted
  mistake each (a wrong number, a wrong player, a reversed relation). It must pass the right ones and catch every
  planted one. The promise that nothing unverified airs rests on this set.
- Scout: every planted moment in the smoke set that the detectors found, and every null moment they mistook for one.
  It should air the planted ones and leave the nulls off.
- Persona: a verified draft in every mode: a line in every language for each, numbers only from the claims, glossary
  keys that exist, and casual lines short enough to read.

Only the evaluator reads the answer keys (PRD 12.9); nothing here reaches an agent's context but the moment card,
which the live pipeline would build anyway. Pass bars are the PRD's starting values.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from offball.agents.crew import AgentFailed, Crew, as_json
from offball.agents.schemas import LANGS, MODES, ClaimOut, DraftOut, ModeScript, ScoutDecision, VerdictOut
from offball.contracts.truth import NULL_TYPES
from offball.mcp import tools as T
from offball.models import metrics

ROOT = Path(__file__).resolve().parents[2]
TRUTH = ROOT / "truth"
BARS = {"factchecker_catches": 0.99, "factchecker_passes": 0.98, "scout_recall": 0.90, "scout_invented_per_null": 0.3,
        "persona_ok": 1.0}
CASUAL_MAX_WORDS = 22


@dataclass
class EvalResult:
    agent: str
    numbers: dict[str, Any]
    passed: bool
    notes: list[str] = field(default_factory=list)

    def text(self) -> str:
        nums = ", ".join(f"{k} {v}" for k, v in self.numbers.items())
        notes = "".join(f"\n  - {n}" for n in self.notes[:8])
        return f"{self.agent}: {'pass' if self.passed else 'FAIL'} ({nums}){notes}"


def _who(player: dict) -> str:
    """A player as the card names them: club and shirt number, since both sides can have the same number."""
    return f"{player['club']}'s No. {player['number']}"


def right_draft(match_id: str, candidate_id: str) -> DraftOut | None:
    """A draft whose every claim comes straight from the tools: the defender's displacement, the creator's run
    length, and the card's own relation, that the creator dragged the defender. A card says "dragged", not that
    the defender followed a run: a moment can be a pin, a screen or a drop as well as a run."""
    card = T.moment_card(match_id, candidate_id)
    if not card.get("creator") or not card.get("dragged"):
        return None
    md = T.REGISTRY.data(match_id)
    creator, dragged = card["creator"], card["dragged"][0]
    window = {"period": card["period"], "t_start_ms": card["t_start_ms"], "t_end_ms": card["t_end_ms"]}
    claims = []
    for k, (metric, player, what) in enumerate((("displacement_m", dragged, "was pulled"),
                                                ("run_length_m", creator, "ran"))):
        pid = player["player_id"]
        r = metrics.compute(md, metric, player_id=pid, **window)
        claims.append(ClaimOut(claim_id=f"c{k + 1}", kind="number", text=f"{_who(player)} {what} {r.value} {r.unit}.",
                               metric=metric, params_json=json.dumps({"player_id": pid, **window}), value=r.value,
                               unit=r.unit, subject_ids=[pid], evidence_ids=r.evidence_ids))
    claims.append(ClaimOut(claim_id="c3", kind="statement", text=f"{_who(creator)} dragged {_who(dragged)}.",
                           metric=None, params_json=None, value=None, unit=None,
                           subject_ids=[creator["player_id"], dragged["player_id"]], evidence_ids=card["evidence_ids"]))
    return DraftOut(headline=f"{_who(creator)} dragged {_who(dragged)} away.", claims=claims, confidence=0.9)


def planted(draft: DraftOut, card: dict, md_players: list[str]) -> list[tuple[str, DraftOut]]:
    """Copies of a right draft with one mistake each: (what was planted, the draft)."""
    out = []
    c1, c2, c3 = draft.claims
    wrong = round((c1.value or 0) * 1.4 + 2, 1)
    out.append(("a wrong number", draft.model_copy(update={"claims": [
        c1.model_copy(update={"value": wrong, "text": c1.text.replace(str(c1.value), str(wrong))}), c2, c3]})))
    creator, dragged = card["creator"], card["dragged"][0]
    other_id = next(p for p in md_players if p.split("-")[0] == creator["club_id"] and p != creator["player_id"])
    other = {**creator, "player_id": other_id, "number": int(other_id.rsplit("-", 1)[1])}
    out.append(("a wrong player", draft.model_copy(update={"claims": [c1, c2, c3.model_copy(update={
        "text": f"{_who(other)} dragged {_who(dragged)}.", "subject_ids": [other_id, dragged["player_id"]]})]})))
    out.append(("a reversed relation", draft.model_copy(update={"claims": [c1, c2, c3.model_copy(update={
        "text": f"{_who(dragged)} dragged {_who(creator)}.",
        "subject_ids": [dragged["player_id"], creator["player_id"]]})]})))
    return out


async def _verdict(crew: Crew, match_id: str, card: dict, draft: DraftOut) -> VerdictOut:
    prompt = (f"Check this draft about a moment in match {match_id}.\n\nMoment card:\n{as_json(card)}\n\n"
              f"Draft:\n{as_json(draft)}")
    return await crew.ask("factchecker", prompt, VerdictOut)


def _passed(v: VerdictOut, n: int) -> bool:
    return v.passed and all(c.ok for c in v.checks) and len(v.checks) >= n


async def factchecker(crew: Crew, moments: list[tuple[str, str]]) -> EvalResult:
    right = caught = right_total = planted_total = 0
    notes = []
    for match_id, cid in moments:
        draft = right_draft(match_id, cid)
        if draft is None:
            continue
        card = T.moment_card(match_id, cid)
        try:
            right_total += 1
            verdict = await _verdict(crew, match_id, card, draft)
            if _passed(verdict, len(draft.claims)):
                right += 1
            else:
                failed = "; ".join(f"{c.claim_id}: {c.reason}" for c in verdict.checks if not c.ok)
                notes.append(f"{cid}: rejected a right draft ({failed or f'{len(verdict.checks)} checks, passed {verdict.passed}'})")
            for what, bad in planted(draft, card, T.REGISTRY.data(match_id).players):
                planted_total += 1
                if _passed(await _verdict(crew, match_id, card, bad), len(bad.claims)):
                    notes.append(f"{cid}: missed {what}")
                else:
                    caught += 1
        except AgentFailed as exc:
            notes.append(f"{cid}: no verdict ({exc})")
    catches = caught / planted_total if planted_total else 0.0
    passes = right / right_total if right_total else 0.0
    return EvalResult("factchecker", {"drafts": right_total, "catches": round(catches, 3), "passes": round(passes, 3)},
                      catches >= BARS["factchecker_catches"] and passes >= BARS["factchecker_passes"], notes)


def scout_tasks(set_name: str = "smoke", only: list[str] | None = None) -> list[tuple[str, str, bool]]:
    """(match, candidate, should air) for every answer-key moment the detectors found: planted ones should air,
    null ones shouldn't. Reads the answer keys, which only the evaluator may."""
    tasks = []
    for key_file in sorted((TRUTH / set_name).glob("*/answer_key.json")):
        match_id = key_file.parent.name
        if only and match_id not in only:
            continue
        found = T.REGISTRY.candidates(match_id)
        for row in json.loads(key_file.read_text(encoding="utf-8")):
            null = row["type"] in NULL_TYPES
            hit = next((c for c in found if c.period == row["period"] and c.creator_id == row.get("creator_id")
                        and c.t_start_ms <= row["t_end_ms"] and c.t_end_ms >= row["t_start_ms"]
                        and (null or c.type == row["type"])), None)
            if hit is not None:
                tasks.append((match_id, hit.candidate_id, not null))
    return tasks


async def scout(crew: Crew, tasks: list[tuple[str, str, bool]]) -> EvalResult:
    aired_planted = planted_total = invented = nulls = 0
    notes = []
    for match_id, cid, should in tasks:
        card = T.moment_card(match_id, cid)
        prompt = (f"Moment card:\n{as_json(card)}\n\nRecently aired moments:\n[]\n\n"
                  f"Producer settings:\n{as_json({'min_gap_s': 20, 'approval': 'auto'})}")
        try:
            d = await crew.ask("scout", prompt, ScoutDecision)
        except AgentFailed as exc:
            notes.append(f"{cid}: no decision ({exc})")
            d = None
        if should:
            planted_total += 1
            aired_planted += bool(d and d.airtime)
            if d and not d.airtime:
                notes.append(f"{cid}: kept a planted {card.get('type')} off air ({d.reason})")
        else:
            nulls += 1
            invented += bool(d and d.airtime)
            if d and d.airtime:
                notes.append(f"{cid}: aired a null moment")
    recall = aired_planted / planted_total if planted_total else 0.0
    per_null = invented / nulls if nulls else 0.0
    return EvalResult("scout", {"planted": planted_total, "recall": round(recall, 3), "nulls": nulls,
                                "invented_per_null": round(per_null, 3)},
                      recall >= BARS["scout_recall"] and per_null <= BARS["scout_invented_per_null"], notes)


def script_problems(script: ModeScript, draft: DraftOut) -> list[str]:
    """What a Persona script gets wrong, by the checks a script can be held to without a reader."""
    problems = []
    numbers = {str(c.value) for c in draft.claims if c.value is not None}
    keys = set(T.glossary("en"))
    for i, line in enumerate(script.lines):
        for lang in LANGS:
            text = getattr(line.text, lang)
            if not text.strip():
                problems.append(f"{script.mode} line {i}: no {lang}")
            for n in re.findall(r"\d+(?:[.,]\d+)?", text):
                if n.replace(",", ".") not in numbers and not re.fullmatch(r"\d{1,2}", n):
                    problems.append(f"{script.mode} line {i} ({lang}): {n} isn't in a verified claim")
        if script.mode == "casual" and len(line.text.en.split()) > CASUAL_MAX_WORDS:
            problems.append(f"casual line {i}: {len(line.text.en.split())} words")
    problems += [f"{script.mode}: unknown glossary key {k}" for k in script.glossary_terms if k not in keys]
    return problems


async def persona(crew: Crew, match_id: str, cid: str) -> EvalResult:
    draft = right_draft(match_id, cid)
    card = T.moment_card(match_id, cid)
    problems, written = [], 0
    for mode in MODES:
        prompt = (f"Viewing mode: {mode}\n\nVerified claims:\n{as_json(draft)}\n\nMoment card:\n{as_json(card)}\n\n"
                  f"Glossary by language:\n{as_json({lang: T.glossary(lang) for lang in LANGS})}")
        try:
            script = await crew.ask("persona", prompt, ModeScript)
        except AgentFailed as exc:
            problems.append(f"{mode}: no script ({exc})")
            continue
        written += 1
        problems += script_problems(script, draft)
    ok = written == len(MODES) and not problems
    return EvalResult("persona", {"modes": written, "problems": len(problems)}, ok, problems)


def showcase_moment() -> tuple[str, str]:
    return "m07", next(c["candidate_id"] for c in T.list_candidates("m07")
                       if c["period"] == 2 and c["creator_id"] == "kes-09" and c["type"] == "decoy_run")


async def run_all(crew: Crew, only: list[str] | None = None, smoke: list[str] | None = None) -> list[EvalResult]:
    agents = only or ["factchecker", "scout", "persona"]
    tasks = scout_tasks("smoke", smoke) if {"factchecker", "scout"} & set(agents) else []
    out = []
    if "factchecker" in agents:
        moments = [showcase_moment()] + [(m, c) for m, c, should in tasks if should]
        out.append(await factchecker(crew, moments))
    if "scout" in agents:
        out.append(await scout(crew, tasks))
    if "persona" in agents:
        out.append(await persona(crew, *showcase_moment()))
    return out


def report(results: list[EvalResult], model: str, timing: dict[str, dict[str, Any]] | None = None) -> str:
    lines = ["# Agent evaluations", "", f"Model: {model}. Pass bars are PRD 14.15's starting values.", "",
             "| Agent | Result | Numbers |", "| --- | --- | --- |"]
    for r in results:
        lines.append(f"| {r.agent} | {'pass' if r.passed else 'fail'} | "
                     f"{', '.join(f'{k} {v}' for k, v in r.numbers.items())} |")
    if timing:
        lines += ["", "Time per call, against each agent's p95 budget (PRD 14.10):", "",
                  "| Agent | Calls | Failed | p95 | Budget |", "| --- | --- | --- | --- | --- |"]
        for agent, t in sorted(timing.items()):
            lines.append(f"| {agent} | {t['calls']} | {t['failures']} | {t['p95_ms']:,} ms | {t['budget_ms']:,} ms |")
    for r in results:
        if r.notes:
            lines += ["", f"## {r.agent}", ""] + [f"- {n}" for n in r.notes[:30]]
    return "\n".join(lines) + "\n"
