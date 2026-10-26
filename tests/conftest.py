"""Shared fixtures. The stand-in model client here exists only for tests: it lets the workflow's wiring be
checked without a real model, and it never ships as a fallback."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from agent_framework import BaseChatClient, ChatResponse, Message

from offball.agents.schemas import (
    AnswerOut,
    ClaimCheck,
    ClaimOut,
    DraftOut,
    Line,
    ModeScript,
    PlannedOverlay,
    Schedule,
    ScoutDecision,
    ScriptCheck,
    VerdictOut,
)

ROOT = Path(__file__).resolve().parents[1]
M07 = ROOT / "datasets" / "showcase" / "m07"
GOAL_WINDOW = {"period": 2, "from_ms": 1_066_000, "to_ms": 1_093_000}


@pytest.fixture(scope="session")
def m07() -> Path:
    return M07


def _prompt(messages: list[Message]) -> str:
    return "\n".join(m.text or "" for m in messages)


def _json_after(text: str, marker: str) -> Any:
    start = text.find(marker)
    if start < 0:
        return None
    start = text.find("{", start)
    return json.JSONDecoder().raw_decode(text[start:])[0]


class ScriptedModel(BaseChatClient):
    """Answers each structured request with a fixed, valid answer, and records what it was asked."""

    def __init__(self, reject_first_draft: bool = False, failing_mode: str | None = None) -> None:
        super().__init__()
        self.calls: list[str] = []
        self.reject_first_draft = reject_first_draft
        self.failing_mode = failing_mode  # the Persona's call for this mode always fails, as a model outage would
        self._verdicts = 0

    def _answer(self, schema: type, prompt: str) -> Any:
        self.calls.append(schema.__name__)
        if schema is ScoutDecision:
            return ScoutDecision(airtime=True, priority=0, want_counterfactual=True, reason="A goal came from it.")
        if schema is DraftOut:
            return DraftOut(headline="No. 9's run pulled No. 5 away and opened the gap.", confidence=0.9, claims=[
                ClaimOut(claim_id="c1", kind="number", text="No. 5 was pulled 14.7 m out of position.",
                         metric="displacement_m", params_json=json.dumps({"player_id": "ash-05", "period": 2,
                                                                          "t_start_ms": 1081000, "t_end_ms": 1085000}),
                         value=14.7, unit="m", subject_ids=["ash-05"], evidence_ids=["m07-f2-27025"]),
                ClaimOut(claim_id="c2", kind="statement", text="No. 10 scored from the gap.", metric=None,
                         params_json=None, value=None, unit=None, subject_ids=["kes-10"], evidence_ids=["m07-e0948"]),
            ])
        if schema is VerdictOut:
            self._verdicts += 1
            ok = not (self.reject_first_draft and self._verdicts == 1)
            return VerdictOut(passed=ok, checks=[ClaimCheck(claim_id=c, ok=ok, recomputed=14.7 if c == "c1" else None,
                                                            reason="matches" if ok else "recompute it")
                                                 for c in ("c1", "c2")])
        if schema is ModeScript:
            mode = prompt.split("Viewing mode: ", 1)[1].split()[0]
            if mode == self.failing_mode:
                raise RuntimeError(f"the {mode} Persona's model is down")
            player = "kes-09" if mode == "player" else None
            return ModeScript(mode=mode, lines=[
                Line(beat="run_start", text="Watch No. 9 run.", a11y_text="No. 9 runs wide.", player_id=player,
                     claim_ids=[]),
                Line(beat="gap_opens", text="A gap opens.", a11y_text="Space opens in the centre.", player_id=player,
                     claim_ids=["c1"]),
                Line(beat="goal", text="Goal.", a11y_text="No. 10 scores.", player_id=player, claim_ids=["c2"]),
            ], runner_tag="No. 9 · decoy run", defender_tag="No. 5 follows", receiver_tag="No. 10",
                ring_label="Space opens here", stat_title="DEFENDER PULLED" if mode == "broadcaster" else "",
                stat_claim_id="c1" if mode == "broadcaster" else None, glossary_terms=["decoy run"])
        if schema is ScriptCheck:
            return ScriptCheck(flagged=[])
        if schema is Schedule:
            scripts = _json_after(prompt, "Scripts by mode") or {}
            plan = []
            for mode in scripts:
                plan.append(PlannedOverlay(mode=mode, kind="run_arrow", anchor="run", text_ref="none", line_index=None,
                                           start_beat="run_start", start_offset_s=-0.5, end_beat="gap_opens",
                                           end_offset_s=1.0, priority=1, approval="auto"))
                plan.append(PlannedOverlay(mode=mode, kind="gap_ring", anchor="gap", text_ref="ring_label",
                                           line_index=None, start_beat="gap_opens", start_offset_s=0,
                                           end_beat="goal", end_offset_s=1.0, priority=0,
                                           approval="pending" if mode == "broadcaster" else "auto"))
                for i, (beat, nxt) in enumerate((("run_start", "gap_opens"), ("gap_opens", "goal"), ("goal", "goal"))):
                    plan.append(PlannedOverlay(mode=mode, kind="caption", anchor="runner" if mode == "player" else "none",
                                               text_ref="line", line_index=i, start_beat=beat, start_offset_s=0,
                                               end_beat=nxt, end_offset_s=0.0 if beat == "run_start" else 3.0, priority=0,
                                               approval="auto"))
            return Schedule(overlays=plan, note="Run, ring and captions in every mode.")
        if schema is AnswerOut:
            return AnswerOut(state="ok", claims=[], alternative_label=None, alternative_question=None)
        raise AssertionError(f"unexpected schema {schema}")

    async def _inner_get_response(self, *, messages, stream, options, **kwargs):
        schema = options.get("response_format")
        value = self._answer(schema, _prompt(list(messages)))
        return ChatResponse(messages=[Message(role="assistant", contents=[value.model_dump_json()])],
                            response_id="scripted")


@pytest.fixture
def scripted() -> type[ScriptedModel]:
    return ScriptedModel
