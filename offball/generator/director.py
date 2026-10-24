"""Directed playback: play a match script with checkpoints, retries and counterfactual truth (PRD 12.4, 12.5).

The engine plays the match in segments. Each scripted moment is attempted from a checkpoint; if its signals
don't verify, the engine rewinds and tries again with new random draws, up to 20 times, then reports back
so the Match director can revise the script. Unscripted goals that break the script's score path rewind the
current segment. For every planted moment that verifies, re-runs from the moment's checkpoint with and
without the creator's decision give the true counterfactual credit.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

import numpy as np

from offball.contracts import AnswerKeyMoment, CounterfactualTruth
from offball.core import answer_key_id, match_minute
from offball.generator.engine.params import EngineParams
from offball.generator.engine.sim import MatchResult, Simulator
from offball.generator.league import League, kit_for_fixture
from offball.generator.moments import MomentPlan, make_plan
from offball.generator.script import MatchScript, StoryMoment

SEGMENT_S = 300.0
EXPECTED: dict[str, dict[str, float]] = {
    "decoy_run": {"defender_displacement_m_min": 8, "zone_control_gain_pts_min": 40, "pass_after_gap_s_max": 2,
                  "defender_follow_cosine_min": 0.6},
    "null_run": {"defender_displacement_m_max": 5, "zone_control_gain_pts_max": 15},
}


@dataclass
class MomentReport:
    key: str
    type: str
    attempts: int
    ok: bool
    reasons: list[str] = field(default_factory=list)


@dataclass
class DirectedMatch:
    script: MatchScript
    result: MatchResult
    answer_key: list[AnswerKeyMoment]
    reports: list[MomentReport]
    segment_retries: int


def derived_seed(*parts: object) -> int:
    digest = hashlib.sha256("/".join(str(p) for p in parts).encode()).digest()
    return int.from_bytes(digest[:4], "little")


def _score(sim: Simulator) -> dict[str, int]:
    return {t.club.club_id: t.score for t in sim.teams}


def _violates(script: MatchScript, sim: Simulator) -> bool:
    minute = match_minute(sim.period, sim.t_ms)
    score = _score(sim)
    for rule in script.score_path:
        if minute < rule.minute and any(score.get(c, 0) > g for c, g in rule.max_goals.items()):
            return True
    return False


def play_script(
    league: League,
    script: MatchScript,
    params: EngineParams | None = None,
    counterfactual_runs: int = 8,
    max_attempts: int = 30,
    max_segment_retries: int = 40,
) -> DirectedMatch:
    problems = script.validate_against(league)
    if problems:
        raise ValueError("Invalid script: " + "; ".join(problems))
    kits = kit_for_fixture(league.club(script.home), league.club(script.away))
    sim = Simulator(league, script.home, script.away, script.match_id, seed=script.seed, kits=kits,
                    half_minutes=script.half_minutes, params=params)
    pending = sorted(script.moments, key=lambda m: m.minute)
    answer_key: list[AnswerKeyMoment] = []
    reports: list[MomentReport] = []
    segment_retries = 0
    half = script.half_minutes

    for period in (1, 2):
        sim.start_period(period)
        seg_cp, seg_start, seg_try = sim.checkpoint(), sim.t, 0
        while not sim.period_over:
            minute = (period - 1) * 45 + sim.t / 60.0
            if pending and pending[0].minute <= minute and (pending[0].minute < half) == (period == 1):
                spec = pending.pop(0)
                attempts = max_attempts * (2 if spec.outcome == "goal" else 1)
                report, row = _attempt(sim, script, spec, len(answer_key) + 1, counterfactual_runs, attempts)
                reports.append(report)
                if row is not None:
                    answer_key.append(row)
                seg_cp, seg_start, seg_try = sim.checkpoint(), sim.t, 0
                continue
            sim.step()
            if _violates(script, sim) and seg_try < max_segment_retries:
                sim.restore(seg_cp)
                seg_try += 1
                segment_retries += 1
                sim.reseed(derived_seed(script.seed, "segment", period, round(seg_start), seg_try))
                continue
            if sim.t - seg_start >= SEGMENT_S:
                seg_cp, seg_start, seg_try = sim.checkpoint(), sim.t, 0
        sim.end_period()
        # Moments scripted for the period that just ended but never reached are reported as missed.
        while pending and (pending[0].minute < half) == (period == 1):
            spec = pending.pop(0)
            reports.append(MomentReport(spec.key, spec.type, 0, False, ["the period ended first"]))
    return DirectedMatch(script, sim.result(), answer_key, reports, segment_retries)


def _attempt(sim: Simulator, script: MatchScript, spec: StoryMoment, n: int, cf_runs: int,
             max_attempts: int) -> tuple[MomentReport, AnswerKeyMoment | None]:
    cp = sim.checkpoint()
    reasons: list[str] = []
    for attempt in range(1, max_attempts + 1):
        plan = make_plan(spec, sim)
        sim.plans.append(plan)
        deadline = sim.t + spec.window_minutes * 60 + 20
        broke_script = False
        while plan.state != "done" and not sim.period_over and sim.t < deadline:
            sim.step()
            if _violates(script, sim):
                broke_script = True
                break
        if plan in sim.plans:
            sim.plans.remove(plan)
        if plan.state == "done" and plan.result.ok and not broke_script and not _violates(script, sim):
            cf = _counterfactual(sim, plan, cf_runs) if not plan.is_null else _null_counterfactual()
            causal, why = plan.causal_check(cf.space_created_m2, cf.gap_opens_without_run)
            if causal:
                row = _answer_key_row(sim, script, spec, plan, n, cf, attempt)
                return MomentReport(spec.key, spec.type, attempt, True, reasons), row
            plan.result.reason = why
        reasons.append("broke the score path" if broke_script else (plan.result.reason or "timed out"))
        sim.restore(cp)
        sim.reseed(derived_seed(script.seed, spec.key, attempt))
    return MomentReport(spec.key, spec.type, max_attempts, False, reasons), None


def _counterfactual(sim: Simulator, plan: MomentPlan, runs: int) -> CounterfactualTruth:
    """Re-run the moment from its checkpoint with and without the creator's decision."""
    rows: dict[str, list] = {"with": [], "without": []}
    for k in range(runs):
        for mode in ("with", "without"):
            fork = sim.fork(plan.start_checkpoint)
            fork.reseed(derived_seed(sim.match_id, plan.spec.key, "cf", mode, k))
            cf = make_plan(plan.spec, fork, mode=mode, timing=dict(plan.timing))
            cf.creator, cf.dragged, cf.receiver, cf.passer = plan.creator, plan.dragged, plan.receiver, plan.passer
            cf.state, cf.t_start = "run", fork.t
            cf.result.t_start = fork.t
            cf.start(fork)
            fork.plans.append(cf)
            limit = fork.t + 8.0
            while cf.state != "done" and fork.t < limit and not fork.period_over:
                fork.step()
            if cf.state == "done":
                rows[mode].append(cf.result)
    area_w = np.median([r.area_m2 for r in rows["with"]]) if rows["with"] else plan.result.area_m2
    area_wo = np.median([r.area_m2 for r in rows["without"]]) if rows["without"] else 0.0
    val_w = np.median([r.zone_value for r in rows["with"]]) if rows["with"] else plan.result.zone_value
    val_wo = np.median([r.zone_value for r in rows["without"]]) if rows["without"] else 0.0
    opens = [r.control_gain >= 0.40 for r in rows["without"]]
    return CounterfactualTruth(
        space_created_m2=round(float(area_w - area_wo), 1),
        epv_gain=round(float(val_w - val_wo), 4),
        gap_opens_without_run=bool(np.mean(opens) > 0.5) if opens else False,
        runs=len(rows["with"]) + len(rows["without"]),
    )


def _null_counterfactual() -> CounterfactualTruth:
    return CounterfactualTruth(space_created_m2=0.0, epv_gain=0.0, gap_opens_without_run=False, runs=0)


def _answer_key_row(sim: Simulator, script: MatchScript, spec: StoryMoment, plan: MomentPlan, n: int,
                    cf: CounterfactualTruth, attempts: int) -> AnswerKeyMoment:
    r = plan.result
    return AnswerKeyMoment(
        moment_id=answer_key_id(script.match_id, n),
        match_id=script.match_id,
        source="planted",
        type=spec.type,
        period=r.period,
        t_start_ms=int(round(r.t_start * 1000)),
        t_end_ms=int(round(r.t_end * 1000)),
        team_id=spec.team,
        creator_id=r.creator,
        dragged_ids=r.dragged,
        receiver_id=r.receiver,
        gap_zone=r.gap_zone,
        expected=EXPECTED.get(spec.type, {}),
        observed=r.signals,
        counterfactual=cf,
        is_null=plan.is_null,
        outcome=r.outcome,
        attempts=attempts,
    )


def showcase_script() -> MatchScript:
    """Kestrel Bay v Ashmoor, round 27: the decoy-run goal on 63 minutes that the demo is built around."""
    from offball.generator.script import ScorePath

    return MatchScript(
        match_id="m07",
        home="kes",
        away="ash",
        seed=7,
        round=27,
        brief=("A tight game: Kestrel Bay's striker keeps testing Ashmoor's centre-backs. One passes the runner on "
               "early; on 63 minutes Hendricx follows Velmar's decoy run and Arkwell scores through the gap."),
        moments=[
            StoryMoment(key="k01", type="null_run", team="kes", minute=11.0, creator_id="kes-09",
                        note="Ashmoor's other centre-back passes Velmar on correctly; no gap opens."),
            StoryMoment(key="k02", type="decoy_run", team="kes", minute=27.0, creator_id="kes-09",
                        outcome="chance", note="Velmar pulls a centre-back wide; the chance goes begging."),
            StoryMoment(key="k03", type="decoy_run", team="kes", minute=62.5, creator_id="kes-09",
                        dragged_id="ash-05", receiver_id="kes-10", outcome="goal",
                        note="The showcase goal: Velmar drags Hendricx wide, Arkwell runs into the gap and scores."),
            StoryMoment(key="k04", type="null_run", team="kes", minute=76.0, creator_id="kes-09",
                        note="Ashmoor have learned: the runner is passed on and no gap opens."),
        ],
        score_path=[ScorePath(minute=62.5, max_goals={"kes": 0, "ash": 0})],
    )
