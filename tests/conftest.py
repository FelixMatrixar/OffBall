"""Shared fixtures. The stand-in model client here exists only for tests: it lets the workflow's wiring be
checked without a real model, and it never ships as a fallback."""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any

import pytest
from agent_framework import (
    BaseChatClient,
    ChatMiddlewareLayer,
    ChatResponse,
    Content,
    FunctionInvocationLayer,
    Message,
)

from offball.agents.schemas import (
    AnswerClaim,
    AnswerOut,
    ClaimCheck,
    ClaimOut,
    DraftOut,
    EngineerDecision,
    Line,
    Localized,
    ModeScript,
    NumberUsed,
    PlannedOverlay,
    Schedule,
    ScoutDecision,
    ScriptCheck,
    TacticianOut,
    VerdictOut,
)

ROOT = Path(__file__).resolve().parents[1]
M07 = ROOT / "datasets" / "showcase" / "m07"
GOAL_WINDOW = {"period": 2, "from_ms": 1_066_000, "to_ms": 1_093_000}


@pytest.fixture(scope="session")
def m07() -> Path:
    return M07


def _l(en: str, es: str, fr: str) -> Localized:
    return Localized(en=en, es=es, fr=fr)


def _live_schedule(scripts: dict, have: set[str]) -> Schedule:
    """For a moment explained before its outcome (a live run): only the beats it has, held past its end."""
    plan = []
    ring_from = "gap_opens" if "gap_opens" in have else "run_start"
    for mode in scripts:
        plan.append(PlannedOverlay(mode=mode, kind="run_arrow", anchor="run", text_ref="none", line_index=None,
                                   start_beat="run_start", start_offset_s=-0.5, end_beat="after", end_offset_s=6.0,
                                   priority=1, approval="auto"))
        plan.append(PlannedOverlay(mode=mode, kind="gap_ring", anchor="gap", text_ref="ring_label", line_index=None,
                                   start_beat=ring_from, start_offset_s=0, end_beat="after", end_offset_s=6.0,
                                   priority=0, approval="pending" if mode == "broadcaster" else "auto"))
        for i, beat in enumerate(("run_start", "gap_opens", "goal")):
            start = beat if beat in have else "run_start"
            plan.append(PlannedOverlay(mode=mode, kind="caption", anchor="runner" if mode == "player" else "none",
                                       text_ref="line", line_index=i, start_beat=start, start_offset_s=float(i),
                                       end_beat="after", end_offset_s=6.0 + i, priority=0, approval="auto"))
    return Schedule(overlays=plan, note="Only the beats the moment has so far.")


def _prompt(messages: list[Message]) -> str:
    return "\n".join(m.text or "" for m in messages)


def _json_after(text: str, marker: str) -> Any:
    start = text.find(marker)
    if start < 0:
        return None
    start = text.find("{", start)
    return json.JSONDecoder().raw_decode(text[start:])[0]


class ScriptedModel(FunctionInvocationLayer, ChatMiddlewareLayer, BaseChatClient):
    """Answers each structured request with a fixed, valid answer, and records what it was asked."""

    def __init__(self, reject_first_draft: bool = False, failing_mode: str | None = None, scout_priority: int = 0,
                 slow: dict[str, float] | None = None, reject_rechecks: bool = False) -> None:
        super().__init__()
        self.calls: list[str] = []
        self.prompts: dict[str, list[str]] = {}  # every prompt, by schema name
        self.reject_first_draft = reject_first_draft
        self.reject_rechecks = reject_rechecks  # a re-check after a feed correction finds the aired draft wrong
        self.failing_mode = failing_mode  # the Persona's call for this mode always fails, as a model outage would
        self.scout_priority = scout_priority
        self.slow = slow or {}  # seconds to wait before answering, by schema name
        self._verdicts = 0

    def _answer(self, schema: type, prompt: str) -> Any:
        self.calls.append(schema.__name__)
        self.prompts.setdefault(schema.__name__, []).append(prompt)
        if schema is ScoutDecision:
            return ScoutDecision(airtime=True, priority=self.scout_priority, want_counterfactual=True,
                                 reason="A goal came from it.")
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
            if "Check these claims from an answer" in prompt:
                ids = re.findall(r'"claim_id":"(a\d+)"', prompt)
                return VerdictOut(passed=True, checks=[ClaimCheck(claim_id=i, ok=True, recomputed=None, reason="shown")
                                                       for i in ids])
            if "feed correction changed" in prompt:
                ok = not self.reject_rechecks
                return VerdictOut(passed=ok, checks=[ClaimCheck(claim_id="c2", ok=ok, recomputed=None,
                                                                reason="still holds" if ok else "the scorer changed")])
            self._verdicts += 1
            ok = not (self.reject_first_draft and self._verdicts == 1)
            # A credulous checker: it passes every claim it is shown (the evaluations catch exactly this).
            ids = list(dict.fromkeys(re.findall(r'"claim_id":"(c\d+)"', prompt))) or ["c1", "c2"]
            return VerdictOut(passed=ok, checks=[ClaimCheck(claim_id=c, ok=ok, recomputed=14.7 if c == "c1" else None,
                                                            reason="matches" if ok else "recompute it")
                                                 for c in ids])
        if schema is ModeScript:
            mode = prompt.split("Viewing mode: ", 1)[1].split()[0]
            if mode == self.failing_mode:
                raise RuntimeError(f"the {mode} Persona's model is down")
            player = "kes-09" if mode == "player" else None
            caster = mode == "broadcaster"
            return ModeScript(mode=mode, lines=[
                Line(beat="run_start", text=_l("Watch No. 9 run.", "Mira la carrera del 9.", "Regardez la course du 9."),
                     a11y_text=_l("No. 9 runs wide.", "El 9 corre hacia la banda.", "Le 9 part vers l'aile."),
                     player_id=player, claim_ids=[]),
                Line(beat="gap_opens", text=_l("A gap opens.", "Se abre un hueco.", "Une brèche s'ouvre."),
                     a11y_text=_l("Space opens in the centre.", "Se abre espacio en el centro.",
                                  "L'espace s'ouvre dans l'axe."), player_id=player, claim_ids=["c1"]),
                Line(beat="goal", text=_l("Goal.", "Gol.", "But."),
                     a11y_text=_l("No. 10 scores.", "Marca el 10.", "Le 10 marque."), player_id=player,
                     claim_ids=["c2"]),
            ], runner_tag=_l("No. 9 · decoy run", "9 · desmarque de arrastre", "9 · appel leurre"),
                defender_tag=_l("No. 5 follows", "El 5 le sigue", "Le 5 suit"), receiver_tag=_l("No. 10", "El 10", "Le 10"),
                ring_label=_l("Space opens here", "Aquí se abre espacio", "L'espace s'ouvre ici"),
                stat_title=_l("DEFENDER PULLED", "DEFENSA ARRASTRADO", "DÉFENSEUR ATTIRÉ") if caster else _l("", "", ""),
                stat_claim_id="c1" if caster else None, glossary_terms=["decoy_run"])
        if schema is ScriptCheck:
            return ScriptCheck(flagged=[])
        if schema is Schedule:
            scripts = _json_after(prompt, "Scripts by mode") or {}
            card = _json_after(prompt, "Moment card") or {}
            have = {b["key"] for b in card.get("beats", [])}
            if not {"gap_opens", "goal"} <= have:
                return _live_schedule(scripts, have)
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
            text = "El 9 arrastró al 5 fuera del centro." if "Answer in Spanish" in prompt else \
                "No. 9 pulled No. 5 out of the centre."
            # The play that shows it: the decoy run, a couple of seconds before No. 9 sets off, with both rung.
            return AnswerOut(state="ok", claims=[AnswerClaim(text=text, verified=True, evidence=["m07-e0948"])],
                             alternative_label=None, alternative_question=None, show_period=2,
                             show_from_ms=1_079_500, show_to_ms=1_087_000, show_player_ids=["kes-09", "ash-05", "nobody"],
                             show_moment_id=None)
        if schema is TacticianOut:
            seen = _json_after(prompt, "Numbers from the replays") or {}
            space = seen.get("space_created_m2", 0.0)
            words = Localized(en=f"In the replays the run made {space} m² of space.",
                              es=f"En las repeticiones, el desmarque creó {space} m² de espacio.",
                              fr=f"Dans les rejeux, l’appel a créé {space} m² d’espace.")
            return TacticianOut(headline=Localized(en="The run made the gap", es="El desmarque abrió el hueco",
                                                   fr="L’appel a ouvert l’espace"),
                                plain=words, analyst=words, numbers=[NumberUsed(name="space_created_m2", value=space)])
        if schema is EngineerDecision:
            # The playbook's first rule: an Explainer well over budget on the reasoning tier moves to the fast one.
            seen = _json_after(prompt, "Telemetry and flags") or {}
            ex = seen.get("agents", {}).get("explainer")
            if ex and ex["tier"] == "reasoning" and ex["p95_ms"] > 2 * ex["budget_ms"]:
                return EngineerDecision(action="set_flag", flag="explainer.model_tier", value="fast", severity="warning",
                                        summary="The Explainer is slow, so it runs on the fast tier for now.",
                                        evidence=[f"explainer p95 {ex['p95_ms']} ms, budget {ex['budget_ms']}"])
            return EngineerDecision(action="none", flag=None, value=None, severity="info", summary="All healthy.",
                                    evidence=[])
        raise AssertionError(f"unexpected schema {schema}")

    async def _inner_get_response(self, *, messages, stream, options, **kwargs):
        schema = options.get("response_format")
        if self.slow.get(schema.__name__):
            await asyncio.sleep(self.slow[schema.__name__])
        messages = list(messages)
        if schema is AnswerOut and not any(c.type == "function_result" for m in messages for c in m.contents):
            # The Pundit looks something up first, so the tool call streams to the panel.
            call = Content.from_function_call("call-1", "match_facts", arguments={"match_id": "m07"})
            return ChatResponse(messages=[Message(role="assistant", contents=[call])], response_id="scripted-tool")
        value = self._answer(schema, _prompt(messages))
        return ChatResponse(messages=[Message(role="assistant", contents=[value.model_dump_json()])],
                            response_id="scripted",
                            usage_details={"input_token_count": 100, "output_token_count": 50, "total_token_count": 150})


@pytest.fixture
def scripted() -> type[ScriptedModel]:
    return ScriptedModel


@pytest.fixture
async def no_model_client(monkeypatch):
    """The API with no model, and a live run of m07 started by this test's producer: (client, producer token)."""
    import httpx

    from offball.agents import llm
    from offball.services.api import app

    monkeypatch.setattr(llm.ModelSettings, "from_env",
                        classmethod(lambda cls: (_ for _ in ()).throw(llm.ModelNotConfigured("no model"))))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post("/api/live-runs", json={"match_id": "m07", "period": 2, "from_ms": 1244000,
                                                      "to_ms": 1245000, "speed": 60})
        assert r.status_code == 201, r.text
        yield client, r.json()["producer_token"]
