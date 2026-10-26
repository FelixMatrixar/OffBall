"""The broadcast crew's workflow (PRD 14.2, 14.11), built with Microsoft Agent Framework.

    Scout -> Explainer -> Fact-checker --(rejected, at most twice)--> Explainer
                                       --(verified)--> fan-out: Persona x 6 modes --> fan-in: Producer -> publish

Every step is a model's decision. A step whose agent fails after its retry ends the moment: nothing airs, and
the outcome says why. Each hand-off is appended to the match state as a typed envelope, so the producer console
can show the trace for any graphic (PRD 14.3).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Literal

from agent_framework import Executor, WorkflowBuilder, WorkflowContext, handler

from offball.agents.crew import AgentFailed, Crew, as_json
from offball.agents.publish import PublishError, build_overlays
from offball.agents.schemas import (
    MODES,
    DraftOut,
    Mode,
    ModeScript,
    Schedule,
    ScoutDecision,
    ScriptCheck,
    VerdictOut,
)
from offball.contracts import Claim, ClaimVerdict, Draft, MomentPick, Verdict
from offball.mcp import tools as T
from offball.services.state import MatchState

log = logging.getLogger("offball.broadcast")
MAX_DRAFTS = 3  # the first draft and at most two rewrites (PRD 14.5)


@dataclass
class MomentJob:
    match_id: str
    candidate_id: str
    card: dict
    settings: dict = field(default_factory=dict)


@dataclass
class DraftReady:
    job: MomentJob
    draft: DraftOut
    attempt: int


@dataclass
class Revision:
    job: MomentJob
    draft: DraftOut
    verdict: VerdictOut
    attempt: int


@dataclass
class Verified:
    job: MomentJob
    draft: DraftOut
    verdict: VerdictOut


@dataclass
class ModeReady:
    verified: Verified
    script: ModeScript


@dataclass
class Outcome:
    candidate_id: str
    status: Literal["published", "skipped", "dropped", "failed"]
    overlay_ids: list[str]
    note: str


def _draft_contract(job: MomentJob, d: DraftOut, attempt: int) -> Draft:
    claims = []
    for c in d.claims:
        try:
            params = json.loads(c.params_json) if c.params_json else {}
        except json.JSONDecodeError:
            params = {"unparsed": c.params_json}
        claims.append(Claim(claim_id=c.claim_id, kind=c.kind, text=c.text, metric=c.metric,
                            params=params if isinstance(params, dict) else {"value": params}, value=c.value,
                            unit=c.unit, subject_ids=c.subject_ids, evidence_ids=c.evidence_ids))
    return Draft(draft_id=f"{job.candidate_id}-draft{attempt}", candidate_id=job.candidate_id, attempt=attempt,
                 headline=d.headline, claims=claims, source="agent")


class Step(Executor):
    """A workflow step that runs one or more agents and records what they hand on."""

    def __init__(self, id: str, crew: Crew, state: MatchState) -> None:
        super().__init__(id=id)
        self.crew = crew
        self.state = state

    def record(self, kind: str, payload, agent: str) -> None:
        self.state.append(kind, payload, produced_by=agent)


class ScoutStep(Step):
    @handler
    async def decide(self, job: MomentJob, ctx: WorkflowContext[MomentJob, Outcome]) -> None:
        aired = [e.payload for e in self.state.of_kind("moment") if e.payload.get("airtime")]
        prompt = (f"Moment card:\n{as_json(job.card)}\n\nRecently aired moments:\n{as_json(aired[-5:])}\n\n"
                  f"Producer settings:\n{as_json(job.settings)}")
        try:
            d = await self.crew.ask("scout", prompt, ScoutDecision)
        except AgentFailed as exc:
            await ctx.yield_output(Outcome(job.candidate_id, "failed", [], str(exc)))
            return
        rank = len(aired) + 1 if d.airtime else 0
        self.record("moment", MomentPick(candidate_id=job.candidate_id, airtime=d.airtime, rank=rank,
                                         priority=d.priority, reason=d.reason,
                                         want_counterfactual=d.want_counterfactual, decided_by="agent"), "scout")
        if d.airtime:
            await ctx.send_message(job)
        else:
            await ctx.yield_output(Outcome(job.candidate_id, "skipped", [], d.reason))


class ExplainStep(Step):
    async def _draft(self, job: MomentJob, prompt: str, attempt: int, ctx: WorkflowContext) -> None:
        try:
            draft = await self.crew.ask("explainer", prompt, DraftOut)
        except AgentFailed as exc:
            await ctx.yield_output(Outcome(job.candidate_id, "failed", [], str(exc)))
            return
        self.record("draft", _draft_contract(job, draft, attempt), "explainer")
        await ctx.send_message(DraftReady(job, draft, attempt))

    @handler
    async def first(self, job: MomentJob, ctx: WorkflowContext[DraftReady, Outcome]) -> None:
        prompt = (f"Explain this moment in match {job.match_id}.\n\nMoment card:\n{as_json(job.card)}")
        await self._draft(job, prompt, 1, ctx)

    @handler
    async def rewrite(self, r: Revision, ctx: WorkflowContext[DraftReady, Outcome]) -> None:
        prompt = (f"Rewrite your explanation of this moment in match {r.job.match_id}.\n\n"
                  f"Moment card:\n{as_json(r.job.card)}\n\nYour previous draft:\n{as_json(r.draft)}\n\n"
                  f"The Fact-checker's verdict:\n{as_json(r.verdict)}")
        await self._draft(r.job, prompt, r.attempt + 1, ctx)


class FactCheckStep(Step):
    @handler
    async def check(self, d: DraftReady, ctx: WorkflowContext[Verified | Revision, Outcome]) -> None:
        job = d.job
        prompt = (f"Check this draft about a moment in match {job.match_id}.\n\nMoment card:\n{as_json(job.card)}\n\n"
                  f"Draft:\n{as_json(d.draft)}")
        try:
            v = await self.crew.ask("factchecker", prompt, VerdictOut)
        except AgentFailed as exc:
            await ctx.yield_output(Outcome(job.candidate_id, "failed", [], str(exc)))
            return
        passed = v.passed and all(c.ok for c in v.checks) and len(v.checks) >= len(d.draft.claims)
        self.record("verdict", Verdict(draft_id=f"{job.candidate_id}-draft{d.attempt}", candidate_id=job.candidate_id,
                                       passed=passed, checked_by="agent",
                                       verdicts=[ClaimVerdict(claim_id=c.claim_id, ok=c.ok, recomputed=c.recomputed,
                                                              reason=c.reason) for c in v.checks]), "factchecker")
        if passed:
            await ctx.send_message(Verified(job, d.draft, v))
        elif d.attempt < MAX_DRAFTS:
            await ctx.send_message(Revision(job, d.draft, v, d.attempt))
        else:
            await ctx.yield_output(Outcome(job.candidate_id, "dropped", [],
                                           "the Fact-checker rejected every draft, so nothing airs"))


class Dispatch(Step):
    @handler
    async def fan_out(self, v: Verified, ctx: WorkflowContext[Verified]) -> None:
        await ctx.send_message(v)


class PersonaStep(Step):
    def __init__(self, mode: Mode, crew: Crew, state: MatchState) -> None:
        super().__init__(f"persona-{mode}", crew, state)
        self.mode = mode

    @handler
    async def voice(self, v: Verified, ctx: WorkflowContext[ModeReady]) -> None:
        prompt = (f"Viewing mode: {self.mode}\n\nVerified claims:\n{as_json(v.draft)}\n\n"
                  f"Moment card:\n{as_json(v.job.card)}")
        try:
            script = await self.crew.ask("persona", prompt, ModeScript)
        except AgentFailed as exc:
            log.warning("No %s script for %s: %s", self.mode, v.job.candidate_id, exc)
            # An empty script, built without validation (a real script needs a line), so the Producer leaves
            # this mode out and the other modes still air (PRD 14.1).
            script = ModeScript.model_construct(mode=self.mode, lines=[], runner_tag="", defender_tag="",
                                                receiver_tag="", ring_label="", stat_title="", stat_claim_id=None,
                                                glossary_terms=[])
        script.mode = self.mode
        self.record("script", {"candidate_id": v.job.candidate_id, **script.model_dump(mode="json")}, "persona")
        await ctx.send_message(ModeReady(v, script))


class ProduceStep(Step):
    """Collects every mode's script, has the Fact-checker read them, schedules, and publishes."""

    @handler
    async def produce(self, ready: list[ModeReady], ctx: WorkflowContext[None, Outcome]) -> None:
        v = ready[0].verified
        job = v.job
        scripts = {r.script.mode: r.script for r in ready if r.script.lines}
        if not scripts:
            await ctx.yield_output(Outcome(job.candidate_id, "failed", [], "no mode has a script"))
            return
        try:
            check = await self.crew.ask(
                "factchecker",
                f"Check these scripts against the verified claims.\n\nVerified claims:\n{as_json(v.draft)}\n\n"
                f"Moment card:\n{as_json(job.card)}\n\nScripts by mode:\n"
                f"{as_json({m: s.model_dump(mode='json') for m, s in scripts.items()})}",
                ScriptCheck)
        except AgentFailed as exc:
            await ctx.yield_output(Outcome(job.candidate_id, "failed", [], str(exc)))
            return
        flagged = {(f.mode, f.line_index) for f in check.flagged}
        for mode, s in list(scripts.items()):
            s.lines = [ln for i, ln in enumerate(s.lines) if (mode, i) not in flagged]
            if not s.lines:
                del scripts[mode]
        self.record("script_check", {"candidate_id": job.candidate_id, **check.model_dump(mode="json")}, "factchecker")
        live_clock = T.REGISTRY.live_clock(job.match_id) if job.settings.get("live", True) else None
        base = (f"Moment card:\n{as_json(job.card)}\n\nScripts by mode (line indexes count from 0):\n"
                f"{as_json({m: s.model_dump(mode='json') for m, s in scripts.items()})}\n\n"
                f"Producer settings:\n{as_json(job.settings)}")
        if live_clock:
            base += (f"\n\nThe match is live and its clock is at period {live_clock[0]}, t_ms {live_clock[1]}. "
                     "Graphics timed before the clock will never be seen; use the beat \"now\" for those.")
        prompt, problems = base, ""
        for attempt in (1, 2):
            if problems:
                prompt = f"{base}\n\nYour previous schedule couldn't be published:\n{problems}\nFix it."
            try:
                schedule = await self.crew.ask("producer", prompt, Schedule)
            except AgentFailed as exc:
                await ctx.yield_output(Outcome(job.candidate_id, "failed", [], str(exc)))
                return
            try:
                overlays = build_overlays(self.state, job.card, scripts, schedule, v.draft, live_clock)
            except PublishError as exc:
                problems = str(exc)
                log.warning("Schedule for %s rejected (attempt %d): %s", job.candidate_id, attempt, problems)
                continue
            self.record("schedule", {"candidate_id": job.candidate_id, **schedule.model_dump(mode="json")}, "producer")
            for o in overlays:
                self.state.upsert_overlay(o)
            await ctx.yield_output(Outcome(job.candidate_id, "published", [o.overlay_id for o in overlays],
                                           schedule.note))
            return
        await ctx.yield_output(Outcome(job.candidate_id, "failed", [], f"no publishable schedule: {problems}"))


def build_workflow(crew: Crew, state: MatchState):
    scout = ScoutStep("scout", crew, state)
    explain = ExplainStep("explainer", crew, state)
    check = FactCheckStep("factchecker", crew, state)
    dispatch = Dispatch("dispatch", crew, state)
    personas = [PersonaStep(m, crew, state) for m in MODES]
    produce = ProduceStep("producer", crew, state)
    return (
        WorkflowBuilder(name="broadcast", start_executor=scout, output_from=[scout, explain, check, produce])
        .add_edge(scout, explain)
        .add_edge(explain, check)
        .add_edge(check, explain, condition=lambda m: isinstance(m, Revision))
        .add_edge(check, dispatch, condition=lambda m: isinstance(m, Verified))
        .add_fan_out_edges(dispatch, personas)
        .add_fan_in_edges(personas, produce)
        .build()
    )


async def run_moment(crew: Crew, state: MatchState, match_id: str, candidate_id: str,
                     settings: dict | None = None) -> Outcome:
    """Take one candidate moment through the crew. Returns what happened to it."""
    job = MomentJob(match_id, candidate_id, T.moment_card(match_id, candidate_id),
                    settings or {"min_gap_s": 20, "approval": "auto"})
    result = await build_workflow(crew, state).run(job)
    outcomes = [o for o in result.get_outputs() if isinstance(o, Outcome)]
    outcome = outcomes[-1] if outcomes else Outcome(candidate_id, "failed", [], "the workflow ended without an outcome")
    state.append("outcome", {"candidate_id": candidate_id, "status": outcome.status,
                             "overlay_ids": outcome.overlay_ids, "note": outcome.note}, produced_by="broadcast")
    return outcome
