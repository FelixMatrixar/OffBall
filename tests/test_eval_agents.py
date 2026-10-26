"""The per-agent evaluations (PRD 14.15), run on the test-only stand-in model. The stand-in's Fact-checker passes
everything it is shown, so its planted-mistake score must come out at zero: the harness catches a credulous checker."""

from __future__ import annotations

from offball.agents.crew import Crew
from offball.agents.schemas import ModeScript
from offball.eval import agents as E
from offball.mcp import tools as T


def test_planted_mistakes_change_one_thing_each() -> None:
    match_id, cid = E.showcase_moment()
    draft = E.right_draft(match_id, cid)
    assert draft is not None and [c.kind for c in draft.claims] == ["number", "number", "statement"]
    variants = E.planted(draft, T.REGISTRY.data(match_id).players)
    assert [what for what, _ in variants] == ["a wrong number", "a wrong player", "a reversed relation"]
    for _, bad in variants:
        assert sum(a != b for a, b in zip(draft.claims, bad.claims, strict=True)) == 1


async def test_a_credulous_fact_checker_fails_its_bar(scripted) -> None:
    crew = Crew.with_clients({"fast": scripted(), "reasoning": scripted()})
    result = await E.factchecker(crew, [E.showcase_moment()])
    assert result.numbers["passes"] == 1.0 and result.numbers["catches"] == 0.0 and not result.passed
    assert len(result.notes) == 3


async def test_scout_and_persona_evaluations_run(scripted) -> None:
    crew = Crew.with_clients({"fast": scripted(), "reasoning": scripted()})
    tasks = E.scout_tasks("smoke", ["smk1"])
    assert tasks and all(match == "smk1" for match, _, _ in tasks)
    scout = await E.scout(crew, tasks)
    assert scout.numbers["recall"] == 1.0
    persona = await E.persona(crew, *E.showcase_moment())
    assert persona.passed, persona.notes
    assert "| persona | pass |" in E.report([scout, persona], "stand-in")


def test_script_problems_are_named() -> None:
    match_id, cid = E.showcase_moment()
    draft = E.right_draft(match_id, cid)
    line = {"beat": "gap_opens", "text": {"en": "He was pulled 99.9 m.", "es": "", "fr": "Il a été tiré."},
            "a11y_text": {"en": "a", "es": "a", "fr": "a"}, "player_id": None, "claim_ids": []}
    tags = {"en": "x", "es": "x", "fr": "x"}
    script = ModeScript.model_validate({"mode": "casual", "lines": [line], "runner_tag": tags, "defender_tag": tags,
                                        "receiver_tag": tags, "ring_label": tags, "stat_title": tags,
                                        "stat_claim_id": None, "glossary_terms": ["not_a_term"]})
    problems = E.script_problems(script, draft)
    assert any("no es" in p for p in problems) and any("99.9" in p for p in problems)
    assert any("not_a_term" in p for p in problems)
