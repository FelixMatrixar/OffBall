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
    "overlap": {"wide_zone_control_pct_min": 60, "two_v_one_s_min": 1.5, "delivery_follows": 1},
    "null_overlap": {"wide_zone_control_gain_pts_max": 15, "two_v_one_s_max": 0.5},
    "timed_run_in_behind": {"onside_at_release": 1, "beyond_line_on_receipt_m_min": 3},
    "underlap": {"half_space_control_pct_min": 60, "receiver_separation_m_min": 3},
    "third_man_run": {"run_before_link_receives": 1, "line_broken_m_min": 1, "passes_max": 2},
    "switch_of_play": {"block_shift_lag_s_min": 1.5, "winger_space_m_min": 5},
    "press_broken": {"pressers_committed_min": 4, "defenders_bypassed_min": 6, "transition_2v3": 1},
    "pinning": {"pinned_s_min": 2, "receiver_space_m_min": 5},
    "rest_defence_exposed": {"cover_short_min": 1, "half_space_overload_min": 1},
    "blind_side_run": {"start_outside_view_cone": 1, "separation_growth_m_min": 3},
    "false_9_drop": {"cb_step_up_m_min": 10, "space_behind_gain_m2_min": 150},
    "cover_shadow": {"pass_prob_drop_pts_min": 30, "ball_backwards_or_sideways": 1},
    "rotation": {"zones_swapped": 1, "marker_switch": 1, "receiver_separation_m_min": 4},
    "set_piece_screen": {"header_separation_gain_m_min": 2},
    "space_lost": {"line_height_drop_m_min": 8, "drop_minutes_min": 5, "field_tilt_swing_pts_min": 10},
    "fatigue_gap": {"recovery_speed_drop_pct_min": 15, "flank_share_gain_pts_min": 20},
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
                    half_minutes=script.half_minutes, params=params,
                    home_direction=1 if script.home_attacks_right_first else -1,
                    subs_after_s=script.subs_after_minute * 60.0)
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
        # Long enough for the plan's own wait and run: team moments play out over minutes.
        deadline = sim.t + max(spec.window_minutes * 60, plan.max_wait_s + plan.max_run_s) + 20
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
            for name, value in plan.carry_over().items():
                setattr(cf, name, value)
            cf.state, cf.t_start = "run", fork.t
            cf.result.t_start = fork.t
            cf.start(fork)
            fork.plans.append(cf)
            limit = fork.t + plan.cf_horizon_s
            while cf.state != "done" and fork.t < limit and not fork.period_over:
                fork.step()
            if cf.state == "done":
                rows[mode].append(cf.result)
    area_w = np.median([r.area_m2 for r in rows["with"]]) if rows["with"] else plan.result.area_m2
    area_wo = np.median([r.area_m2 for r in rows["without"]]) if rows["without"] else 0.0
    val_w = np.median([r.zone_value for r in rows["with"]]) if rows["with"] else plan.result.zone_value
    val_wo = np.median([r.zone_value for r in rows["without"]]) if rows["without"] else 0.0
    opens = [r.control_gain >= plan.gap_threshold for r in rows["without"]]
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


# The showcase goal's clock: period 2 from 63:00, and the seconds after that of each beat.
SHOWCASE_T0_S = 18 * 60.0
SHOWCASE_BEATS = {"run": 1.0, "follow": 2.5, "gap": 3.8, "pass": 4.2, "shot": 6.4, "goal": 6.9}


def showcase_script() -> MatchScript:
    """Kestrel Bay v Ashmoor, round 27: the decoy-run goal on 63 minutes that the demo is built around."""
    from offball.generator.script import ScorePath

    return MatchScript(
        match_id="m07",
        home="kes",
        away="ash",
        seed=7,
        round=27,
        home_attacks_right_first=False,
        subs_after_minute=64.0,
        brief=("A tight game: Kestrel Bay's striker keeps testing Ashmoor's centre-backs. One passes the runner on "
               "early; on 63 minutes Hendricx follows Velmar's decoy run and Arkwell scores through the gap."),
        moments=[
            StoryMoment(key="k01", type="null_run", team="kes", minute=11.0, creator_id="kes-09",
                        note="Ashmoor's other centre-back passes Velmar on correctly; no gap opens."),
            StoryMoment(key="k02", type="decoy_run", team="kes", minute=24.0, creator_id="kes-09",
                        outcome="chance", note="Velmar pulls a centre-back wide; the chance goes begging."),
            StoryMoment(key="k03", type="decoy_run", team="kes", minute=59.0, latest_minute=63.0, creator_id="kes-09",
                        dragged_id="ash-05", receiver_id="kes-10", outcome="goal", sure=True,
                        note="The showcase goal: Velmar drags Hendricx wide, Arkwell runs into the gap and scores."),
            StoryMoment(key="k04", type="null_run", team="kes", minute=76.0, creator_id="kes-09",
                        note="Ashmoor have learned: the runner is passed on and no gap opens."),
        ],
        score_path=[ScorePath(minute=59.0, max_goals={"kes": 0, "ash": 0}),
                    ScorePath(minute=63.5, max_goals={"kes": 1, "ash": 0})],
    )


def place_showcase_goal(dm: DirectedMatch) -> None:
    """Put the showcase goal on SHOWCASE_T0_S: its run, pass, shot and goal on their SHOWCASE_BEATS, and the
    follow and the gap where play puts them in between."""
    import tempfile
    from pathlib import Path

    from offball.generator.retime import retime_moment
    from offball.generator.writer import write_match
    from offball.models.match_data import MatchData
    from offball.models.metrics import moment_beats

    goal = next((r for r in dm.answer_key if r.type == "decoy_run" and r.outcome == "goal"), None)
    if goal is None or goal.receiver_id is None or not goal.dragged_ids:
        return
    with tempfile.TemporaryDirectory() as tmp:
        write_match(dm.result, Path(tmp) / "data", Path(tmp) / "truth")
        md = MatchData.load(Path(tmp) / "data")
        beats = moment_beats(md, goal.period, goal.team_id, goal.t_start_ms, goal.dragged_ids[0], goal.receiver_id,
                             goal.gap_zone)
    targets = {name: int(round((SHOWCASE_T0_S + SHOWCASE_BEATS[name]) * 1000)) for name in ("run", "pass", "shot", "goal")}
    retime_moment(dm.result, dm.answer_key, goal.period, beats, targets, derived_seed(dm.script.seed, "clock"),
                  firm=("pass", "shot", "goal"))
