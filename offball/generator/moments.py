"""Story moments as choreographies with soft constraints (PRD 12.4 step 8, 12.7).

A plan waits for its preconditions to arise naturally, then gives intents to named roles. Physics and the
true probability models still decide what happens. When the plan ends, its signals are measured with the
same public metrics the detectability gate uses; if they miss, the director rewinds and tries again.

The same plans run in counterfactual mode: from the moment's checkpoint, with one decision changed (the
creator's run removed), to measure true counterfactual credit.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

import numpy as np

from offball.generator.engine.geometry import L, W, rect
from offball.generator.engine.models import location_value, plan_aerial, plan_ground, pressure_on
from offball.generator.engine.tactics import offside_line_team
from offball.models.pitch_control import control_fast

if TYPE_CHECKING:
    from offball.generator.engine.sim import Simulator
    from offball.generator.script import StoryMoment

CounterfactualMode = Literal["actual", "with", "without"]
ZONE_STEP = 1.0


def zone_cells(polygon: list[tuple[float, float]]) -> np.ndarray:
    xs = [p[0] for p in polygon]
    ys = [p[1] for p in polygon]
    gx = np.arange(min(xs) + ZONE_STEP / 2, max(xs), ZONE_STEP)
    gy = np.arange(min(ys) + ZONE_STEP / 2, max(ys), ZONE_STEP)
    mx, my = np.meshgrid(gx, gy)
    return np.stack([mx.ravel(), my.ravel()], axis=1)


def team_control(sim: Simulator, team: int, cells: np.ndarray) -> np.ndarray:
    att = sim.active_of(team)
    dfn = sim.active_of(1 - team)
    return control_fast(sim.pos[att], sim.vel[att], sim.pos[dfn], sim.vel[dfn], cells)


def tx(sim: Simulator, team: int, xy: np.ndarray) -> tuple[float, float]:
    return sim.team_frame(team, xy)


def to_abs(sim: Simulator, team: int, x_t: float, y_t: float) -> np.ndarray:
    d = sim.teams[team].direction
    return np.array([x_t, y_t]) if d > 0 else np.array([L - x_t, W - y_t])


@dataclass
class PlanResult:
    ok: bool = False
    reason: str = ""
    signals: dict[str, float] = field(default_factory=dict)
    t_start: float = 0.0
    t_end: float = 0.0
    period: int = 1
    creator: str = ""
    dragged: list[str] = field(default_factory=list)
    receiver: str | None = None
    gap_zone: list[tuple[float, float]] = field(default_factory=list)
    outcome: str = "none"
    # For counterfactual re-runs: the zone's controlled area and value at the measurement instant.
    area_m2: float = 0.0
    zone_value: float = 0.0
    control_gain: float = 0.0
    ghost_track: list[tuple[float, float, float]] = field(default_factory=list)


class MomentPlan:
    """Base choreography. Subclasses define ready(), start(), step() and verify()."""

    kind = "base"
    max_wait_s = 180.0
    max_run_s = 12.0
    is_null = False
    gap_threshold = 0.40  # zone control gain that counts as the gap opening, in the counterfactual re-runs
    dead_ball_ok = False  # set pieces can start while the ball is dead
    cf_horizon_s = 8.0  # how long each counterfactual re-run plays

    def __init__(self, spec: StoryMoment, sim: Simulator, mode: CounterfactualMode = "actual",
                 timing: dict[str, float] | None = None) -> None:
        self.spec = spec
        self.team = 0 if sim.teams[0].club.club_id == spec.team else 1
        self.mode = mode
        self.timing = timing or {}
        self.state = "wait"
        self.t0 = sim.t
        if spec.latest_minute is not None:
            # Wait no later than the script allows.
            played = (sim.period - 1) * sim.half_s + sim.t
            self.max_wait_s = max(0.0, min(self.max_wait_s, spec.latest_minute * 60.0 - played))
        self.t_start = 0.0
        self.result = PlanResult()
        self.creator = self.dragged = self.receiver = self.passer = -1

    # ------------------------------------------------------------------ lifecycle
    def tick(self, sim: Simulator) -> bool:
        if self.state == "wait":
            if sim.t - self.t0 > self.max_wait_s:
                return self._end(sim, False, "preconditions never arose")
            live = sim.ball_state != "dead" or self.dead_ball_ok
            if live and self.mode == "actual":
                self.steer(sim)
            if live and self.ready(sim):
                self.start_checkpoint = sim.checkpoint() if self.mode == "actual" else None
                self.state = "run"
                self.t_start = sim.t
                self.result.t_start = sim.t
                self.result.period = sim.period
                self.start(sim)
            return False
        if self.state == "run":
            if sim.t - self.t_start > self.max_run_s:
                return self.finish(sim)
            return self.step(sim)
        return True

    def _end(self, sim: Simulator, ok: bool, reason: str) -> bool:
        self.state = "done"
        self.result.ok = ok
        self.result.reason = reason
        self.result.t_end = sim.t
        self.release(sim)
        return True

    def finish(self, sim: Simulator) -> bool:
        ok, reason = self.verify(sim)
        return self._end(sim, ok, reason)

    carried = ("creator", "dragged", "receiver", "passer")  # who a counterfactual re-run plays the moment with

    def carry_over(self) -> dict:
        """The participants a counterfactual re-run needs, chosen when this plan became ready."""
        return {name: getattr(self, name) for name in self.carried}

    def release(self, sim: Simulator) -> None:
        """Hand every participant back to its own policy."""
        for i in (self.creator, self.dragged, self.receiver, self.passer):
            if i >= 0:
                sim.directives.pop(i, None)
                sim.lock_until[i] = min(sim.lock_until[i], sim.t)
        for key in [k for k in sim.bias if k[0] in (self.creator, self.dragged, self.receiver)]:
            sim.bias.pop(key, None)

    # ------------------------------------------------------------------ helpers
    def slot(self, sim: Simulator, pid: str | None, team: int) -> int:
        if pid is None:
            return -1
        i = sim.slot_of(pid)
        return i if i >= 0 and sim.team_of[i] == team else -1

    def pick_role(self, sim: Simulator, team: int, roles: tuple[str, ...], key) -> int:
        cands = [i for i in sim.active_of(team) if sim.role[i] in roles]
        return max(cands, key=key) if cands else -1

    def ready(self, sim: Simulator) -> bool:
        raise NotImplementedError

    def steer(self, sim: Simulator) -> None:
        """Soft steering while waiting for preconditions: natural movements that make them likelier."""

    def causal_check(self, space_created_m2: float, gap_opens_without: bool) -> tuple[bool, str]:
        """Planted moments must have caused what they claim: checked against the counterfactual re-runs."""
        return True, "ok"

    def start(self, sim: Simulator) -> None:
        raise NotImplementedError

    def step(self, sim: Simulator) -> bool:
        raise NotImplementedError

    def verify(self, sim: Simulator) -> tuple[bool, str]:
        raise NotImplementedError


class DecoyRun(MomentPlan):
    """A striker runs diagonally wide, a centre-back follows, and a midfielder runs into the gap."""

    kind = "decoy_run"
    max_wait_s = 240.0
    cb_discipline = 0.04  # soft constraint: this defender is inclined to follow runners

    def ready(self, sim: Simulator) -> bool:
        t = self.team
        if sim.possession != t:
            return False
        # The passer is whoever has the ball, or whoever a pass in flight is going to.
        owner = sim.owner
        if owner < 0 and sim.ball_state == "flight" and sim.flight_plan.get("outcome") == "complete":
            owner = sim.flight_plan.get("receiver", -1)
        if owner < 0 or sim.team_of[owner] != t:
            return False
        if self.creator < 0 or not sim.active[self.creator]:
            self.creator = self.slot(sim, self.spec.creator_id, t)
            if self.creator < 0:
                self.creator = self.pick_role(sim, t, ("ST",), key=lambda i: tx(sim, t, sim.pos[i])[0])
        c = self.creator
        if c < 0 or owner == c:
            return False
        bx, _ = tx(sim, t, sim.ball_pos[:2])
        cx, cy = tx(sim, t, sim.pos[c])
        if not (42 <= bx <= 82 and cx >= 64 and abs(cy - W / 2) < 16):
            return False
        opp = sim.active_of(1 - t)
        wanted = self.slot(sim, self.spec.dragged_id, 1 - t)
        cbs = [k for k in opp if sim.role[k] == "CB"] if wanted < 0 else [wanted]
        if not cbs:
            return False
        d = min(cbs, key=lambda k: float(np.linalg.norm(sim.pos[k] - sim.pos[c])))
        if float(np.linalg.norm(sim.pos[d] - sim.pos[c])) > 9.0 or not sim._is_goal_side(d, c):
            return False
        if float(np.linalg.norm(sim.vel[d])) > 3.5:
            return False  # the back line is still moving: any displacement would not be the run's doing
        r = self.slot(sim, self.spec.receiver_id, t)
        if r < 0:
            mids = [i for i in sim.active_of(t) if sim.role[i] in ("AM", "CM") and i not in (owner, c)]
            if not mids:
                return False
            r = max(mids, key=lambda i: sim.run_timing[i] - 0.02 * float(np.linalg.norm(sim.pos[i] - sim.pos[d])))
        if r in (owner, c) or float(np.linalg.norm(sim.pos[r] - sim.pos[d])) > 18:
            return False
        if pressure_on(sim.pos[owner], sim.pos[opp]) > 0.55:
            return False
        ox, oy = tx(sim, t, sim.pos[owner])
        if abs(oy - W / 2) > 24 or not (10.0 <= float(np.linalg.norm(sim.pos[owner] - sim.pos[d])) <= 34.0):
            return False  # the passer needs to be central and within range of the gap
        self.dragged, self.receiver, self.passer = d, r, owner
        return True

    def steer(self, sim: Simulator) -> None:
        """While waiting, the striker plays on the centre-back's shoulder, as strikers do."""
        t = self.team
        if sim.possession != t or sim.frame % 25:
            return
        c = self.creator if self.creator >= 0 else self.slot(sim, self.spec.creator_id, t)
        if c < 0:
            c = self.pick_role(sim, t, ("ST",), key=lambda i: tx(sim, t, sim.pos[i])[0])
        if c < 0 or sim.owner == c or sim.lock_until[c] > sim.t:
            return
        self.creator = c
        opp = sim.active_of(1 - t)
        wanted = self.slot(sim, self.spec.dragged_id, 1 - t)
        cbs = [k for k in opp if sim.role[k] == "CB"] if wanted < 0 else [wanted]
        if not cbs:
            return
        d = min(cbs, key=lambda k: float(np.linalg.norm(sim.pos[k] - sim.pos[c])))
        dx, dy = tx(sim, t, sim.pos[d])
        line = sim.offside_cache[t]
        spot = to_abs(sim, t, min(dx - 2.5, line - 0.8), dy + (1.5 if dy < W / 2 else -1.5))
        sim.set_intent(c, "support", spot, 0.6, until=sim.t + 1.1)
        sim.lock_until[c] = sim.t + 1.0  # hold the movement until the next steer
        # The receiver drifts between the lines, behind the defender, ready to attack the space.
        r = self.slot(sim, self.spec.receiver_id, t)
        if r < 0:
            mids = [i for i in sim.active_of(t) if sim.role[i] in ("AM", "CM") and i not in (sim.owner, c)]
            r = max(mids, key=lambda i: sim.run_timing[i] - 0.02 * float(np.linalg.norm(sim.pos[i] - sim.pos[d]))) \
                if mids else -1
        if r >= 0 and r != sim.owner and sim.lock_until[r] <= sim.t:
            side = 4.0 if dy < W / 2 else -4.0
            between = to_abs(sim, t, max(dx - 13.0, 40.0), float(np.clip(dy + side, 8, W - 8)))
            sim.set_intent(r, "support", between, 0.55, until=sim.t + 1.1)
            sim.lock_until[r] = sim.t + 1.0

    def causal_check(self, space_created_m2: float, gap_opens_without: bool) -> tuple[bool, str]:
        if gap_opens_without:
            return False, "the gap would have opened without the run"
        if space_created_m2 < 15.0:
            return False, "the run created too little space"
        return True, "ok"

    def start(self, sim: Simulator) -> None:
        t, c, d, r = self.team, self.creator, self.dragged, self.receiver
        self.cb_start = sim.pos[d].copy()
        self.creator_start = sim.pos[c].copy()
        self.follow_corr = 0.0
        goal_side = (sim._own_goal(1 - t) - self.cb_start)
        goal_side = goal_side / (np.linalg.norm(goal_side) or 1.0)
        centre = self.cb_start + goal_side * 1.5
        self.zone = rect(float(centre[0]), float(centre[1]), 4.5, 6.0)
        self.cells = zone_cells(self.zone)
        self.control_start = float(team_control(sim, t, self.cells).mean())
        self.gap_point = centre
        xs = sorted({p[0] for p in self.zone})
        ys = sorted({p[1] for p in self.zone})
        self._targets = [np.array([x, y]) for x in np.linspace(xs[0] + 1.5, xs[-1] - 1.5, 3)
                         for y in np.linspace(ys[0] + 2.0, ys[-1] - 2.0, 3)]
        self.best_lane_p = 0.0
        self.gap_open_t: float | None = None
        self.pass_t: float | None = None
        self.pass_event: dict | None = None
        self.receiver_started = False
        self.disp_max = 0.0
        cx, cy = tx(sim, t, sim.pos[c])
        rx, ry = tx(sim, t, sim.pos[r])
        side = 1.0 if ry < cy else -1.0  # run away from the receiver's side
        line = sim.offside_cache[t]
        target_t = (min(cx + 5.0, line + 0.5, L - 8), float(np.clip(cy + side * 18.0, 5, W - 5)))
        self.run_target = to_abs(sim, t, *target_t)
        self.result.creator = sim.pid(c)
        self.result.dragged = [sim.pid(d)]
        self.result.receiver = sim.pid(r)
        self.result.gap_zone = self.zone
        # The defender decides now, as the run starts: follow or pass the runner on. The director's soft
        # constraint is only a bias on his discipline; the draw is still random.
        sim.bias[(d, "discipline")] = (self.cb_discipline, sim.t + 8.0)
        self._cover_watches(sim)
        P = sim.params
        p_track = P.track_base + P.track_discipline * (1 - self.cb_discipline) - 0.06
        if self.mode == "without" or sim.rng.random() >= float(np.clip(p_track + 0.1, 0.02, 0.98)):
            sim.set_intent(d, "mark", None, 0.75, data={"who": c, "decided": True})
            sim.log_intent(d, "pass_on", 1 - p_track)
        else:
            sim.set_intent(d, "track", None, 0.97, data={"who": c, "since": sim.t, "decided": True})
            sim.lock_until[d] = sim.t + 0.6
            sim.log_intent(d, "track_runner", p_track)
        if self.mode == "without":
            # The counterfactual: the striker doesn't make the run and stays in the team's shape.
            sim.set_intent(c, "anchor", None, 0.5)
            sim.lock_until[c] = sim.t + self.max_run_s
            sim.log_intent(c, "hold_position", 0.0)
        else:
            sim.set_intent(c, "run", self.run_target, 0.98, until=sim.t + 3.8, data={"kind": "decoy_run"})
            sim.lock_until[c] = sim.t + 3.4
            sim.log_intent(c, "decoy_run", 0.02)
        if self.mode == "actual":
            sim.directives[self.passer] = {
                "action": "pass", "to": r, "hold": True, "subtype": "through",
                "when": self._pass_when, "point_fn": lambda s: self.gap_point,
            }

    cover_hold_s = 4.0  # soft constraint: the nearest cover is caught watching the ball for this long

    def _cover_watches(self, sim: Simulator) -> None:
        """The defender best placed to cover the gap is caught watching the ball and holds his spot for a moment,
        as real covers often are. In every mode, so the counterfactual compares like with like."""
        opp = [k for k in sim.active_of(1 - self.team) if k != self.dragged and sim.role[k] != "GK"]
        if not opp or self.cover_hold_s <= 0:
            return
        k = min(opp, key=lambda k: float(np.linalg.norm(sim.pos[k] - self.gap_point)))
        if float(np.linalg.norm(sim.pos[k] - self.gap_point)) > 15.0:
            return
        sim.set_intent(k, "watch", sim.pos[k].copy(), 0.3, until=sim.t + self.cover_hold_s)
        sim.lock_until[k] = sim.t + self.cover_hold_s
        sim.log_intent(k, "ball_watching", 0.0)

    def _gain(self, sim: Simulator) -> float:
        return float(team_control(sim, self.team, self.cells).mean()) - self.control_start

    def _pass_when(self, sim: Simulator) -> bool:
        # Play it in as the gap opens and the runner arrives, so the ball and the runner meet in it, and only
        # when the lane is on: the pass still has to beat the true interception model.
        if self._gain(sim) < 0.3:
            return False
        if float(np.linalg.norm(sim.pos[self.receiver] - self.gap_point)) >= 10.0:
            return False
        passer = sim.owner
        if passer < 0:
            return False
        # Aim anywhere in the vacated space where the lane is clearest, along the ground or clipped over the
        # midfield screen, as a playmaker would. The pass still faces the true interception model.
        best_p, best_pt, best_aerial = 0.0, None, False
        for pt in self._targets:
            for aerial in (False, True):
                if aerial:
                    flight = plan_aerial(sim.pos[passer].copy(), pt.copy(), apex=3.2)
                else:
                    flight = plan_ground(sim.pos[passer].copy(), pt.copy(), arrival_speed=sim.params.pass_arrival)
                p = sim.assess(passer, self.receiver, flight).p_success
                if p > best_p:
                    best_p, best_pt, best_aerial = p, pt, aerial
        self.best_lane_p = max(self.best_lane_p, best_p)
        if best_pt is None or best_p < 0.35:
            return False
        self.gap_point = best_pt
        sim.idata[self.receiver]["point"] = best_pt  # the runner adjusts to where the ball is going
        if passer in sim.directives:
            sim.directives[passer]["aerial"] = best_aerial
            sim.directives[passer]["subtype"] = "lofted" if best_aerial else "through"
        return True

    def step(self, sim: Simulator) -> bool:
        t, d, r = self.team, self.dragged, self.receiver
        elapsed = sim.t - self.t_start
        disp = float(np.linalg.norm(sim.pos[d] - self.cb_start))
        if elapsed <= 3.0:
            self.disp_max = max(self.disp_max, disp)
            self.follow_corr = _cosine(sim.pos[d] - self.cb_start, sim.pos[self.creator] - self.creator_start)
        if self.gap_open_t is None and self._gain(sim) >= 0.40:
            self.gap_open_t = sim.t
        go_at = self.timing.get("receiver_go", None)
        go = (elapsed >= go_at) if go_at is not None else (disp >= 3.0 or elapsed >= 1.2)
        if not self.receiver_started and go:
            self.receiver_started = True
            self.timing["receiver_go"] = elapsed
            sim.set_intent(r, "run", self.gap_point, 1.0, until=sim.t + 3.5, data={"kind": "run_into_gap"})
            sim.lock_until[r] = sim.t + 2.5
            sim.log_intent(r, "run_into_gap", 0.02)
        if self.mode != "actual":
            measure_at = self.timing.get("measure_at", 2.6)
            if elapsed >= measure_at:
                self._measure(sim)
                return self._end(sim, True, "counterfactual measured")
            return False
        # Actual play: watch for the pass, then for the finish.
        if self.pass_t is None:
            if sim.ball_state == "flight" and sim.flight_plan.get("passer") == self.passer:
                self.pass_t = sim.t
                self.timing["measure_at"] = elapsed
                self._measure(sim)
                self.pass_event = sim.flight_plan.get("event")
                if self.spec.outcome in ("goal", "shot"):
                    sure = "goal" if self.spec.sure and self.spec.outcome == "goal" else None
                    sim.directives[r] = {"action": "shoot_on_receive", "outcome": sure}
            elif sim.possession != t:
                return self._end(sim, False, "lost the ball before the pass")
            elif elapsed > 8.0:
                self.result.signals["best_lane_p"] = round(self.best_lane_p, 3)
                return self._end(sim, False, "the gap never opened in time")
            return False
        # After the pass: wait for the shot to resolve, or for the move to break down.
        shots = [e for e in sim.events if e["type"] == "shot" and e.get("t_ms", 0) >= int(self.pass_t * 1000)
                 and e["period"] == sim.period]
        if shots:
            if sim.ball_state != "flight" or sim.flight_plan.get("kind") != "shot":
                self.result.outcome = "goal" if shots[0]["outcome"] == "goal" else "shot"
                return self.finish(sim)
            return False
        if sim.possession != t or sim.t - self.pass_t > 4.5:
            self.result.outcome = "chance" if sim.owner == r else "none"
            return self.finish(sim)
        return False

    def _measure(self, sim: Simulator) -> None:
        ctrl = team_control(sim, self.team, self.cells)
        values = np.array([location_value(*tx(sim, self.team, c)) for c in self.cells])
        self.result.area_m2 = float(ctrl.sum() * ZONE_STEP * ZONE_STEP)
        self.result.zone_value = float((ctrl * values).mean())
        self.result.control_gain = float(ctrl.mean()) - self.control_start
        self.result.ghost_track = [(sim.t, float(sim.pos[self.creator][0]), float(sim.pos[self.creator][1]))]

    def verify(self, sim: Simulator) -> tuple[bool, str]:
        s = self.result.signals
        s["defender_displacement_m"] = round(self.disp_max, 2)
        s["zone_control_gain_pts"] = round(100 * self.result.control_gain, 1)
        if self.pass_t is None:
            delay = 99.0
        elif self.gap_open_t is None or self.gap_open_t >= self.pass_t:
            delay = 0.0  # the pass anticipated the gap
        else:
            delay = self.pass_t - self.gap_open_t
        s["pass_after_gap_s"] = round(delay, 2)
        s["defender_follow_cosine"] = round(self.follow_corr, 2)
        if self.disp_max < 8.0:
            return False, "the defender didn't follow far enough"
        if self.follow_corr < 0.6:
            return False, "the defender moved, but not with the runner"
        if self.result.control_gain < 0.40:
            return False, "the gap didn't open enough"
        if delay > 2.0:
            return False, "the pass came too late"
        ev = self.pass_event
        if ev is None or ev.get("end_xy") is None or not _inside(np.array(ev["end_xy"]), self.zone, pad=3.0):
            return False, "the pass didn't go into the gap"
        if self.spec.outcome in ("chance", "shot", "goal") and ev.get("outcome") != "complete":
            return False, "the pass into the gap didn't arrive"
        if self.spec.outcome == "goal" and self.result.outcome != "goal":
            return False, "no goal"
        if self.spec.outcome == "shot" and self.result.outcome not in ("goal", "shot"):
            return False, "no shot"
        return True, "ok"


class NullRun(DecoyRun):
    """A decoy run the defender correctly passes on: no gap opens, and any credit given is invented."""

    kind = "null_run"
    is_null = True
    cb_discipline = 0.97
    cover_hold_s = 0.0  # the defence is switched on: nobody is caught watching

    def start(self, sim: Simulator) -> None:
        super().start(sim)
        sim.directives.pop(self.passer, None)  # nobody plays into a gap that isn't there

    def step(self, sim: Simulator) -> bool:
        elapsed = sim.t - self.t_start
        disp = float(np.linalg.norm(sim.pos[self.dragged] - self.cb_start))
        if elapsed <= 3.0:
            self.disp_max = max(self.disp_max, disp)
        if elapsed >= 3.5:
            self._measure(sim)
            return self.finish(sim)
        return False

    def causal_check(self, space_created_m2: float, gap_opens_without: bool) -> tuple[bool, str]:
        return True, "ok"  # a null run creates nothing by construction; verify() already checked that

    def verify(self, sim: Simulator) -> tuple[bool, str]:
        s = self.result.signals
        s["defender_displacement_m"] = round(self.disp_max, 2)
        s["zone_control_gain_pts"] = round(100 * self.result.control_gain, 1)
        if self.disp_max >= 5.0:
            return False, "the defender followed the runner"
        if self.result.control_gain >= 0.15:
            return False, "a gap opened anyway"
        return True, "ok"


FULL_BACK_ROLES = ("RB", "LB", "RWB", "LWB")
THROUGH_ARRIVAL = 13.0  # a driven through ball still runs at this speed when it reaches the runner, m/s
FORWARD_ROLES = ("ST", "RW", "LW", "AM")


def _holder(sim: Simulator, t: int) -> int:
    """Whoever has the ball for team t, or whoever a completed pass in flight is going to; -1 otherwise."""
    owner = sim.owner
    if owner < 0 and sim.ball_state == "flight" and sim.flight_plan.get("outcome") == "complete":
        owner = sim.flight_plan.get("receiver", -1)
    return owner if owner >= 0 and sim.team_of[owner] == t else -1


def _dist(sim: Simulator, a: int, b: int) -> float:
    return float(np.linalg.norm(sim.pos[a] - sim.pos[b]))


def _through_ball(sim: Simulator, t: int, passer: int, runner: int, run_target: np.ndarray
                  ) -> tuple[float, np.ndarray | None, bool]:
    """The best ball into a runner's path: a driven pass along the ground or a chip over the line, into the
    channel either side of his line of run, at a few leads. Returns its true success chance, the point and
    whether it goes in the air."""
    heading = run_target - sim.pos[runner]
    heading = heading / (float(np.linalg.norm(heading)) or 1.0)
    pace = max(float(np.linalg.norm(sim.vel[runner])), 5.0)
    best_p, best_air, pt = 0.0, False, None
    for lead_s in (0.6, 1.1, 1.6):
        for lateral in (-5.0, 0.0, 5.0):
            lead = tx(sim, t, sim.pos[runner] + heading * pace * (lead_s + _dist(sim, passer, runner) / 25.0))
            cand = to_abs(sim, t, min(lead[0], L - 9.0), float(np.clip(lead[1] + lateral, 4.0, W - 4.0)))
            for air in (False, True):
                flight = (plan_aerial(sim.pos[passer].copy(), cand.copy(), apex=3.6) if air
                          else plan_ground(sim.pos[passer].copy(), cand.copy(), arrival_speed=THROUGH_ARRIVAL))
                p = sim.assess(passer, runner, flight).p_success
                if p > best_p:
                    best_p, best_air, pt = p, air, cand
    return best_p, pt, best_air


def _separation(sim: Simulator, t: int, i: int) -> float:
    """Distance from player i to the nearest opponent of team t."""
    opp = sim.active_of(1 - t)
    return float(np.min(np.linalg.norm(sim.pos[opp] - sim.pos[i], axis=1))) if opp else 99.0


class _Finish:
    """Shared ending for plans that set up a final ball: wait for the shot, or for the move to break down."""

    def _await_finish(self: MomentPlan, sim: Simulator, since: float, holder: int) -> bool:
        shots = [e for e in sim.events if e["type"] == "shot" and e.get("t_ms", 0) >= int(since * 1000)
                 and e["period"] == sim.period]
        if shots:
            if sim.ball_state != "flight" or sim.flight_plan.get("kind") != "shot":
                self.result.outcome = "goal" if shots[0]["outcome"] == "goal" else "shot"
                return self.finish(sim)
            return False
        if sim.possession != self.team or sim.t - since > 4.5:
            self.result.outcome = "chance" if sim.owner == holder else "none"
            return self.finish(sim)
        return False

    def _check_outcome(self: MomentPlan) -> tuple[bool, str]:
        if self.spec.outcome == "goal" and self.result.outcome != "goal":
            return False, "no goal"
        if self.spec.outcome == "shot" and self.result.outcome not in ("goal", "shot"):
            return False, "no shot"
        return True, "ok"


class Overlap(_Finish, MomentPlan):
    """A full-back runs round the outside of the wide player on the ball, the defender facing them has to
    choose, and a cross or cut-back follows (PRD 12.7, Overlap)."""

    kind = "overlap"
    max_wait_s = 240.0
    max_run_s = 11.0
    gap_threshold = 0.30  # the wide zone turning this much more ours without the run means it wasn't the run
    tracked = False  # the null version: a second defender tracks the overlap

    # ------------------------------------------------------------------ setup
    def _side(self, sim: Simulator, owner: int) -> float:
        """-1 when the ball is on the flank at y' = 0 in the team's frame, +1 on the flank at y' = W."""
        return -1.0 if tx(sim, self.team, sim.pos[owner])[1] < W / 2 else 1.0

    def _zone(self, sim: Simulator, owner: int) -> list[tuple[float, float]]:
        """The flank channel ahead of the wide player that the overlap attacks."""
        ox, _ = tx(sim, self.team, sim.pos[owner])
        side = self._side(sim, owner)
        centre = to_abs(sim, self.team, min(ox + 12.0, L - 7.0), W / 2 + side * (W / 2 - 6.0))
        return rect(float(centre[0]), float(centre[1]), 8.0, 6.0)

    def _full_back(self, sim: Simulator, owner: int) -> int:
        t = self.team
        c = self.slot(sim, self.spec.creator_id, t)
        if c >= 0:
            return c
        side = self._side(sim, owner)
        cands = [i for i in sim.active_of(t) if sim.role[i] in FULL_BACK_ROLES and i != owner
                 and (tx(sim, t, sim.pos[i])[1] - W / 2) * side > 0]
        return min(cands, key=lambda i: _dist(sim, i, owner)) if cands else -1

    def ready(self, sim: Simulator) -> bool:
        t = self.team
        if sim.possession != t:
            return False
        owner = _holder(sim, t)
        if owner < 0 or sim.role[owner] in ("GK", *FULL_BACK_ROLES):
            return False
        ox, oy = tx(sim, t, sim.pos[owner])
        if not (50 <= ox <= 80 and abs(oy - W / 2) > 12):
            return False  # a wide player on the ball in the attacking half
        c = self._full_back(sim, owner)
        if c < 0 or c == owner:
            return False
        cx, cy = tx(sim, t, sim.pos[c])
        if not (ox - 24 <= cx <= ox - 2 and abs(cy - oy) < 16):
            return False  # the full-back is behind the ball on the same flank, with ground to make up
        opp = [k for k in sim.active_of(1 - t) if sim.role[k] != "GK"]
        if pressure_on(sim.pos[owner], sim.pos[opp]) > 0.6:
            return False
        wanted = self.slot(sim, self.spec.dragged_id, 1 - t)
        cands = [k for k in opp if sim._is_goal_side(k, owner)] if wanted < 0 else [wanted]
        if not cands:
            return False
        d = min(cands, key=lambda k: _dist(sim, k, owner))
        if _dist(sim, d, owner) > 10.0:
            return False
        if not self._defence_ready(sim, owner, d, opp):
            return False
        self.creator, self.dragged, self.receiver, self.passer = c, d, c, owner
        return True

    def _defence_ready(self, sim: Simulator, owner: int, d: int, opp: list[int]) -> bool:
        """One defender facing the ball on that flank, so the overlap can make it two against one, and the
        channel ahead still the defence's."""
        if any(_dist(sim, k, owner) < 12.0 for k in opp if k != d):
            return False
        return float(team_control(sim, self.team, zone_cells(self._zone(sim, owner))).mean()) < 0.45

    def steer(self, sim: Simulator) -> None:
        """While waiting, the full-back pushes on behind the play down his flank, as attacking full-backs do."""
        t = self.team
        if sim.possession != t or sim.frame % 25:
            return
        owner = _holder(sim, t)
        if owner < 0 or sim.role[owner] in ("GK", *FULL_BACK_ROLES):
            return
        ox, oy = tx(sim, t, sim.pos[owner])
        if ox < 42 or abs(oy - W / 2) < 8:
            return
        c = self._full_back(sim, owner)
        if c < 0 or c == owner or sim.lock_until[c] > sim.t:
            return
        spot = self._waiting_spot(sim, ox, self._side(sim, owner))
        sim.set_intent(c, "support", spot, 0.6, until=sim.t + 1.1)
        sim.lock_until[c] = sim.t + 1.0

    def start(self, sim: Simulator) -> None:
        t, c, d, o = self.team, self.creator, self.dragged, self.passer
        ox, oy = tx(sim, t, sim.pos[o])
        side = self._side(sim, o)
        self.zone = self._zone(sim, o)
        self.cells = zone_cells(self.zone)
        self.control_start = float(team_control(sim, t, self.cells).mean())
        self.control_max = self.control_start
        self.two_v_one = self.two_v_one_max = 0.0
        self.pass_t: float | None = None
        self.pass_event: dict | None = None
        self.received_t: float | None = None
        self.delivery_t: float | None = None
        self.delivery_event: dict | None = None
        self.target = -1
        self.best_lane_p = 0.0
        self.overlap_point = sim.pos[c].copy()
        self.run_target = self._run_spot(sim, ox, side)
        self.result.creator = sim.pid(c)
        self.result.dragged = [sim.pid(d)]
        self.result.receiver = sim.pid(c)
        self.result.gap_zone = self.zone
        if self.mode == "without":
            # The counterfactual: the full-back stays in the team's shape.
            sim.set_intent(c, "anchor", None, 0.5)
            sim.lock_until[c] = sim.t + self.max_run_s
            sim.log_intent(c, "hold_position", 0.0)
        else:
            sim.set_intent(c, "run", self.run_target, 0.95, until=sim.t + 4.2, data={"kind": self.kind})
            sim.lock_until[c] = sim.t + 3.6
            sim.log_intent(c, self.kind, 0.02)
        # The wide player holds it up and shapes away from the run, which commits the defender facing him.
        if sim.owner == o:
            sim.set_intent(o, "carry", self._carry_spot(sim, ox, oy, side), 0.4, until=sim.t + 1.0)
            sim.lock_until[o] = sim.t + 0.9
        self._attack_box(sim)
        if self.tracked:
            self._track_overlap(sim)
        elif self.mode == "actual":
            sim.directives[o] = {"action": "pass", "to": c, "hold": True, "when": self._pass_when,
                                 "point_fn": lambda s: self.overlap_point}

    def _run_spot(self, sim: Simulator, ox: float, side: float) -> np.ndarray:
        """Where the run goes: round the outside, down the touchline."""
        return to_abs(sim, self.team, min(ox + 15.0, L - 6.0), W / 2 + side * (W / 2 - 3.0))

    def _carry_spot(self, sim: Simulator, ox: float, oy: float, side: float) -> np.ndarray:
        """Where the wide player takes the ball while the run goes on: inside, away from the overlap."""
        return to_abs(sim, self.team, ox + 2.0, oy - side * 4.0)

    def _waiting_spot(self, sim: Simulator, ox: float, side: float) -> np.ndarray:
        """Where the runner waits for the moment: behind the play, out wide."""
        return to_abs(sim, self.team, max(ox - 11.0, 30.0), W / 2 + side * (W / 2 - 7.0))

    def _track_overlap(self, sim: Simulator) -> None:
        """The null version: the nearest free defender tracks the overlapping run, so no 2 v 1 forms."""

    # ------------------------------------------------------------------ play
    def _pair_is_two_v_one(self, sim: Simulator) -> bool:
        o, c = self.passer, self.creator
        gap = _dist(sim, o, c)
        if gap > 18.0:
            return False
        mid = (sim.pos[o] + sim.pos[c]) / 2
        radius = max(6.0, gap / 2 + 3.0)
        defenders = sum(float(np.linalg.norm(sim.pos[k] - mid)) < radius for k in sim.active_of(1 - self.team))
        return defenders <= 1

    def _pass_when(self, sim: Simulator) -> bool:
        o, c = sim.owner, self.creator
        if o < 0:
            return False
        ox, _ = tx(sim, self.team, sim.pos[o])
        cx, _ = tx(sim, self.team, sim.pos[c])
        if cx < ox - 1.0 or (self.two_v_one < 0.4 and self.two_v_one_max < 1.5):
            return False  # wait until he is round the outside and the 2 v 1 has been made
        lead = tx(sim, self.team, sim.pos[c] + sim.vel[c] * 0.7)
        pt = to_abs(sim, self.team, min(lead[0], L - 4.0), float(np.clip(lead[1], 2.0, W - 2.0)))
        flight = plan_ground(sim.pos[o].copy(), pt, arrival_speed=sim.params.pass_arrival)
        p = sim.assess(o, c, flight).p_success
        self.best_lane_p = max(self.best_lane_p, p)
        if p < 0.45:
            return False
        self.overlap_point = pt
        return True

    def _attack_box(self, sim: Simulator) -> None:
        """As the overlap goes on, the forwards attack the near post and the penalty spot."""
        t = self.team
        side = self._side(sim, self.passer)
        line = sim.offside_cache[t] - 0.8  # arriving, not waiting offside
        spots = [(min(L - 7.0, line), W / 2 + side * 5.0), (min(L - 12.0, line - 3.0), W / 2 - side * 2.0)]
        fwd = sorted([i for i in sim.active_of(t) if sim.role[i] in FORWARD_ROLES and i not in (self.creator, self.passer)],
                     key=lambda i: -tx(sim, t, sim.pos[i])[0])
        for i, (sx, sy) in zip(fwd, spots, strict=False):
            sim.set_intent(i, "run", to_abs(sim, t, sx, sy), 0.85, until=sim.t + 5.0, data={"kind": "box_run"})
            sim.lock_until[i] = sim.t + 4.0

    def _set_delivery(self, sim: Simulator) -> bool:
        """Pick the cross or cut-back: the teammate in or arriving at the box with the best ball to him."""
        t, c = self.team, self.creator
        best = None
        for j in sim.active_of(t):
            if j == c or sim.role[j] == "GK" or sim._is_offside(j):
                continue
            jx, jy = tx(sim, t, sim.pos[j])
            if jx < L - 35.0 or abs(jy - W / 2) > 22.0:
                continue
            target = np.clip(sim.pos[j] + sim.vel[j] * 0.5, [1.0, 1.0], [L - 1.0, W - 1.0])
            ground = plan_ground(sim.pos[c].copy(), target.copy(), arrival_speed=sim.params.pass_arrival)
            p_ground = sim.assess(c, j, ground).p_success
            aerial = plan_aerial(sim.pos[c].copy(), target.copy(), apex=3.5)
            p_air = sim._assess_cross(c, j, aerial).p_success
            value = location_value(*tx(sim, t, target), sim.params)
            for p, air in ((p_ground, False), (p_air, True)):
                if best is None or p * value > best[0]:
                    best = (p * value, j, air)
        if best is None:
            return False
        _, j, air = best
        self.target = j
        sim.directives[c] = {"action": "pass", "to": j, "hold": False, "aerial": air,
                             "subtype": "cross" if air else "cutback", "apex": 3.5}
        return True

    def step(self, sim: Simulator) -> bool:
        t, c = self.team, self.creator
        elapsed = sim.t - self.t_start
        if sim.frame % 5 == 0 and self.delivery_t is None:
            self.control_max = max(self.control_max, float(team_control(sim, t, self.cells).mean()))
            self.two_v_one = self.two_v_one + 0.2 if self._pair_is_two_v_one(sim) else 0.0
            self.two_v_one_max = max(self.two_v_one_max, self.two_v_one)
        if self.mode != "actual" or self.tracked:
            if elapsed >= self.timing.get("measure_at", 2.6):
                self._measure(sim)
                return self.finish(sim) if self.tracked else self._end(sim, True, "counterfactual measured")
            return False
        if self.pass_t is None:
            if sim.ball_state == "flight" and sim.flight_plan.get("passer") == self.passer:
                self.pass_t = sim.t
                self.timing["measure_at"] = elapsed
                self._measure(sim)
                self.pass_event = sim.flight_plan.get("event")
                self._attack_box(sim)  # the line has moved: time the runs again
            elif sim.possession != t:
                return self._end(sim, False, "lost the ball before the overlap pass")
            elif elapsed > 6.5:
                return self._end(sim, False, f"the overlap was never found (2 v 1 for {self.two_v_one_max:.1f} s, "
                                             f"best lane {self.best_lane_p:.2f})")
            elif sim.owner == self.passer:
                sim.next_decision[self.passer] = min(sim.next_decision[self.passer], sim.t)  # watch for the moment
            return False
        if self.received_t is None:
            if sim.owner == c:
                self.received_t = sim.t
                if not self._set_delivery(sim):
                    return self._end(sim, False, "nobody in the box to cross to")
            elif sim.possession != t or sim.t - self.pass_t > 4.0:
                outcome = (self.pass_event or {}).get("outcome")
                return self._end(sim, False, f"the overlap pass didn't arrive ({outcome})")
            return False
        if self.delivery_t is None:
            if sim.ball_state == "flight" and sim.flight_plan.get("passer") == c:
                self.delivery_t = sim.t
                self.delivery_event = sim.flight_plan.get("event")
                if self.spec.outcome in ("goal", "shot"):
                    sim.directives[self.target] = {"action": "shoot_on_receive"}
            elif sim.possession != t or sim.t - self.received_t > 3.0:
                return self._end(sim, False, "no cross or cut-back followed")
            return False
        return self._await_finish(sim, self.delivery_t, self.target)

    def release(self, sim: Simulator) -> None:
        super().release(sim)
        if getattr(self, "target", -1) >= 0:
            sim.directives.pop(self.target, None)

    def _measure(self, sim: Simulator) -> None:
        ctrl = team_control(sim, self.team, self.cells)
        values = np.array([location_value(*tx(sim, self.team, c)) for c in self.cells])
        self.result.area_m2 = float(ctrl.sum() * ZONE_STEP * ZONE_STEP)
        self.result.zone_value = float((ctrl * values).mean())
        self.result.control_gain = float(ctrl.mean()) - self.control_start
        self.result.ghost_track = [(sim.t, float(sim.pos[self.creator][0]), float(sim.pos[self.creator][1]))]

    def causal_check(self, space_created_m2: float, gap_opens_without: bool) -> tuple[bool, str]:
        if gap_opens_without:
            return False, "the flank would have opened without the overlap"
        if space_created_m2 < 15.0:
            return False, "the overlap created too little space"
        return True, "ok"

    def verify(self, sim: Simulator) -> tuple[bool, str]:
        s = self.result.signals
        s["wide_zone_control_start_pct"] = round(100 * self.control_start, 1)
        s["wide_zone_control_pct"] = round(100 * self.control_max, 1)
        s["two_v_one_s"] = round(self.two_v_one_max, 2)
        s["delivery_follows"] = 1.0 if self.delivery_event is not None else 0.0
        if self.control_start >= 0.5:
            return False, "the flank was already ours"
        if self.control_max < 0.6:
            return False, "the wide zone never turned"
        if self.two_v_one_max < 1.5:
            return False, "no 2 v 1 formed"
        if self.delivery_event is None:
            return False, "no cross or cut-back followed"
        if self.delivery_event.get("outcome") == "offside":
            return False, "the cross found a man offside"
        if self.spec.outcome in ("chance", "shot", "goal") and (self.pass_event or {}).get("outcome") != "complete":
            return False, "the overlap pass didn't arrive"
        return self._check_outcome()


class NullOverlap(Overlap):
    """An overlap the defence handles: a second defender tracks the run, no 2 v 1 forms, and any credit given
    is invented."""

    kind = "null_overlap"
    is_null = True
    tracked = True

    def _helpers(self, sim: Simulator, owner: int, d: int) -> list[int]:
        """Defenders other than the one facing the ball who are already near the flank channel."""
        zone = np.array(self._zone(sim, owner))
        centre = zone.mean(axis=0)
        return [k for k in sim.active_of(1 - self.team) if sim.role[k] != "GK" and k != d
                and float(np.linalg.norm(sim.pos[k] - centre)) < 15.0]

    def _defence_ready(self, sim: Simulator, owner: int, d: int, opp: list[int]) -> bool:
        """A defence set up to handle it: a second defender is already near the channel the overlap attacks."""
        if not self._helpers(sim, owner, d):
            return False
        return float(team_control(sim, self.team, zone_cells(self._zone(sim, owner))).mean()) < 0.5

    def _track_overlap(self, sim: Simulator) -> None:
        c = self.creator
        helpers = self._helpers(sim, self.passer, self.dragged)
        if not helpers:
            return
        centre = np.array(self.zone).mean(axis=0)
        k = min(helpers, key=lambda k: float(np.linalg.norm(sim.pos[k] - centre)))
        sim.bias[(k, "discipline")] = (0.95, sim.t + 8.0)
        sim.set_intent(k, "track", None, 0.97, data={"who": c, "since": sim.t, "decided": True})
        sim.lock_until[k] = sim.t + 3.0
        sim.log_intent(k, "track_runner", 0.9)

    def causal_check(self, space_created_m2: float, gap_opens_without: bool) -> tuple[bool, str]:
        return True, "ok"  # nothing is created by construction; verify() checked that

    def verify(self, sim: Simulator) -> tuple[bool, str]:
        s = self.result.signals
        s["wide_zone_control_gain_pts"] = round(100 * (self.control_max - self.control_start), 1)
        s["two_v_one_s"] = round(self.two_v_one_max, 2)
        if self.control_max - self.control_start >= 0.15:
            return False, "the flank opened anyway"
        if self.two_v_one_max > 0.5:
            return False, "a 2 v 1 formed"
        return True, "ok"


UNDERLAP_ROLES = ("CM", "AM", *FULL_BACK_ROLES)


class Underlap(Overlap):
    """A midfielder or full-back runs inside the wide player on the ball, into the half-space, and is found
    there with room to turn (PRD 12.7, Underlap)."""

    kind = "underlap"

    def _zone(self, sim: Simulator, owner: int) -> list[tuple[float, float]]:
        """The half-space channel ahead of the wide player, inside him, that the underlap attacks."""
        ox, _ = tx(sim, self.team, sim.pos[owner])
        side = self._side(sim, owner)
        centre = to_abs(sim, self.team, min(ox + 10.0, L - 12.0), W / 2 + side * 12.0)
        return rect(float(centre[0]), float(centre[1]), 8.0, 5.0)

    def _full_back(self, sim: Simulator, owner: int) -> int:
        """The runner: a central midfielder or the full-back, coming from behind and inside the wide player."""
        t = self.team
        c = self.slot(sim, self.spec.creator_id, t)
        if c >= 0:
            return c
        _, oy = tx(sim, t, sim.pos[owner])
        side = self._side(sim, owner)
        cands = [i for i in sim.active_of(t) if i != owner and sim.role[i] in UNDERLAP_ROLES
                 and (tx(sim, t, sim.pos[i])[1] - W / 2) * side > -4.0
                 and abs(tx(sim, t, sim.pos[i])[1] - W / 2) < abs(oy - W / 2) - 3.0]
        return min(cands, key=lambda i: _dist(sim, i, owner)) if cands else -1

    def _defence_ready(self, sim: Simulator, owner: int, d: int, opp: list[int]) -> bool:
        """The half-space ahead is still the defence's."""
        return float(team_control(sim, self.team, zone_cells(self._zone(sim, owner))).mean()) < 0.45

    def _run_spot(self, sim: Simulator, ox: float, side: float) -> np.ndarray:
        return to_abs(sim, self.team, min(ox + 12.0, L - 12.0), W / 2 + side * 11.0)

    def _carry_spot(self, sim: Simulator, ox: float, oy: float, side: float) -> np.ndarray:
        """The wide player holds the width, so the defender facing him can't drop into the half-space."""
        return to_abs(sim, self.team, ox + 2.0, float(np.clip(oy + side * 3.0, 2.0, W - 2.0)))

    def _waiting_spot(self, sim: Simulator, ox: float, side: float) -> np.ndarray:
        return to_abs(sim, self.team, max(ox - 9.0, 30.0), W / 2 + side * 9.0)

    def start(self, sim: Simulator) -> None:
        super().start(sim)
        self.separation: float | None = None

    def _pass_when(self, sim: Simulator) -> bool:
        o, c = sim.owner, self.creator
        if o < 0:
            return False
        ox, _ = tx(sim, self.team, sim.pos[o])
        cx, _ = tx(sim, self.team, sim.pos[c])
        if cx < ox - 2.0 or _separation(sim, self.team, c) < 2.5:
            return False  # wait until he is level, inside, and free
        pt = np.clip(sim.pos[c] + sim.vel[c] * 0.8, [1.0, 1.0], [L - 1.0, W - 1.0])
        flight = plan_ground(sim.pos[o].copy(), pt.copy(), arrival_speed=sim.params.pass_arrival)
        p = sim.assess(o, c, flight).p_success
        self.best_lane_p = max(self.best_lane_p, p)
        if p < 0.35:
            return False
        self.overlap_point = pt
        return True

    def step(self, sim: Simulator) -> bool:
        t, c = self.team, self.creator
        elapsed = sim.t - self.t_start
        if sim.frame % 5 == 0 and self.received_t is None:
            self.control_max = max(self.control_max, float(team_control(sim, t, self.cells).mean()))
        if self.mode != "actual":
            if elapsed >= self.timing.get("measure_at", 2.6):
                self._measure(sim)
                return self._end(sim, True, "counterfactual measured")
            return False
        if self.pass_t is None:
            if sim.ball_state == "flight" and sim.flight_plan.get("passer") == self.passer:
                self.pass_t = sim.t
                self.timing["measure_at"] = elapsed
                self._measure(sim)
                self.pass_event = sim.flight_plan.get("event")
                if self.spec.outcome in ("goal", "shot"):
                    sim.directives[c] = {"action": "shoot_on_receive"}
            elif sim.possession != t:
                return self._end(sim, False, "lost the ball before the underlap pass")
            elif elapsed > 7.0:
                return self._end(sim, False, f"the underlap was never found (best lane {self.best_lane_p:.2f})")
            elif sim.owner == self.passer:
                sim.next_decision[self.passer] = min(sim.next_decision[self.passer], sim.t)  # watch for the moment
            return False
        if self.received_t is None:
            if sim.owner == c:
                self.received_t = sim.t
                self.separation = _separation(sim, t, c)
            elif sim.possession != t or sim.t - self.pass_t > 4.0:
                return self.finish(sim)
            return False
        return self._await_finish(sim, self.received_t, c)

    def causal_check(self, space_created_m2: float, gap_opens_without: bool) -> tuple[bool, str]:
        if gap_opens_without:
            return False, "the half-space would have opened without the underlap"
        if space_created_m2 < 15.0:
            return False, "the underlap created too little space"
        return True, "ok"

    def verify(self, sim: Simulator) -> tuple[bool, str]:
        s = self.result.signals
        s["half_space_control_start_pct"] = round(100 * self.control_start, 1)
        s["half_space_control_pct"] = round(100 * self.control_max, 1)
        s["receiver_separation_m"] = round(self.separation, 2) if self.separation is not None else 0.0
        if self.control_start >= 0.6:
            return False, "the half-space was already ours"
        if self.control_max < 0.6 or self.control_max - self.control_start < 0.15:
            return False, "the half-space never turned"
        if self.separation is None or (self.pass_event or {}).get("outcome") != "complete":
            return False, f"the underlap pass didn't arrive ({(self.pass_event or {}).get('outcome')})"
        if self.separation < 3.0:
            return False, "received without room to turn"
        return self._check_outcome()


LINK_ROLES = ("ST", "AM", "CM", "RW", "LW")
THIRD_MAN_ROLES = ("ST", "AM", "CM", "RW", "LW", "RM", "LM")


class ThirdManRun(_Finish, MomentPlan):
    """A passes to B, who lays it off first time to C, already running beyond the line (PRD 12.7, Third-man
    run). C is the creator and the receiver; B is the link."""

    kind = "third_man_run"
    max_wait_s = 240.0
    max_run_s = 10.0
    link = -1
    carried = (*MomentPlan.carried, "link")

    def ready(self, sim: Simulator) -> bool:
        t = self.team
        if sim.possession != t or sim.owner < 0 or sim.team_of[sim.owner] != t:
            return False
        a = sim.owner
        ax, _ = tx(sim, t, sim.pos[a])
        if sim.role[a] == "GK" or not (30 <= ax <= 72):
            return False
        opp = [k for k in sim.active_of(1 - t) if sim.role[k] != "GK"]
        if pressure_on(sim.pos[a], sim.pos[opp]) > 0.45:
            return False
        line = sim.offside_cache[t]
        if line > 84.0:
            return False  # no room in behind
        wanted = self.slot(sim, self.spec.creator_id, t)
        runners = [wanted] if wanted >= 0 else [i for i in sim.active_of(t) if i != a and sim.role[i] in THIRD_MAN_ROLES]
        runners = [i for i in runners if line - 12.0 <= tx(sim, t, sim.pos[i])[0] <= line - 2.0]
        links = [b for b in sim.active_of(t) if b != a and sim.role[b] in LINK_ROLES
                 and ax + 4.0 <= tx(sim, t, sim.pos[b])[0] <= line - 1.0 and 8.0 <= _dist(sim, a, b) <= 25.0
                 and pressure_on(sim.pos[b], sim.pos[opp]) < 0.7]
        for c in sorted(runners, key=lambda i: -tx(sim, t, sim.pos[i])[0]):
            for b in links:
                if b == c or not 6.0 <= _dist(sim, b, c) <= 25.0:
                    continue
                to_feet = plan_ground(sim.pos[a].copy(), sim.pos[b] + sim.vel[b] * 0.3,
                                      arrival_speed=sim.params.pass_arrival)
                if sim.assess(a, b, to_feet).p_success < 0.6:
                    continue
                line_men = [k for k in opp if tx(sim, t, sim.pos[k])[0] >= line - 3.0]
                if not line_men:
                    return False
                self.creator, self.receiver, self.passer, self.link = c, c, a, b
                self.dragged = min(line_men, key=lambda k: _dist(sim, k, c))
                return True
        return False

    def start(self, sim: Simulator) -> None:
        t, c, d, a, b = self.team, self.creator, self.dragged, self.passer, self.link
        line = sim.offside_cache[t]
        _, cy = tx(sim, t, sim.pos[c])
        ty = float(np.clip(cy + (W / 2 - cy) * 0.25, 6, W - 6))
        self.run_target = to_abs(sim, t, min(line + 14.0, L - 7.0), ty)
        centre = to_abs(sim, t, min(line + 7.0, L - 8.0), ty)
        self.zone = rect(float(centre[0]), float(centre[1]), 7.0, 6.0)
        self.cells = zone_cells(self.zone)
        self.control_start = float(team_control(sim, t, self.cells).mean())
        self.ball_point = self.run_target.copy()
        self.b_point = sim.pos[b].copy() if b >= 0 else sim.pos[c].copy()
        self.best_lane_p = 0.0
        self.pass1_t: float | None = None
        self.pass1_event: dict | None = None
        self.b_recv_t: float | None = None
        self.pass2_t: float | None = None
        self.pass2_event: dict | None = None
        self.received_t: float | None = None
        self.beyond: float | None = None
        self.result.creator = sim.pid(c)
        self.result.dragged = [sim.pid(d)]
        self.result.receiver = sim.pid(c)
        self.result.gap_zone = self.zone
        self.run_started, self.run_t = False, None
        if self.mode == "without":
            sim.set_intent(c, "anchor", None, 0.5)
            sim.lock_until[c] = sim.t + self.max_run_s
            sim.log_intent(c, "hold_position", 0.0)
        else:
            # C waits off the line and goes just before the ball reaches B: running before B receives, but
            # still onside when B lays it off.
            wait = to_abs(sim, t, line - 4.0, ty)
            sim.set_intent(c, "support", wait, 0.45, until=sim.t + 4.0)
            sim.lock_until[c] = sim.t + 4.0
        if self.mode == "actual" and b >= 0:
            sim.directives[a] = {"action": "pass", "to": b, "hold": True, "when": self._pass1_when,
                                 "point_fn": lambda s: self.b_point}

    def _pass1_when(self, sim: Simulator) -> bool:
        """A plays it into B's feet once C's run is under way, so C is moving before B receives."""
        a, b = sim.owner, self.link
        if a < 0 or sim.t - self.t_start < 0.3:
            return False
        pt = np.clip(sim.pos[b] + sim.vel[b] * 0.3, [1.0, 1.0], [L - 1.0, W - 1.0])
        flight = plan_ground(sim.pos[a].copy(), pt.copy(), arrival_speed=sim.params.pass_arrival)
        if sim.assess(a, b, flight).p_success < 0.55:
            return False
        self.b_point = pt
        return True

    def _pass2_when(self, sim: Simulator) -> bool:
        """B lays it off first time into C's path, while C is still onside."""
        t, b, c = self.team, sim.owner, self.creator
        if b < 0:
            return False
        line = offside_line_team(sim, t)
        if tx(sim, t, sim.pos[c])[0] > line + 0.25:
            return False
        best_p, pt, air = _through_ball(sim, t, b, c, self.run_target)
        self.best_lane_p = max(self.best_lane_p, best_p)
        if pt is None or best_p < 0.25:
            return False
        self.ball_point = pt
        sim.idata[c]["point"] = pt  # the runner bends his run onto the ball
        if b in sim.directives:
            sim.directives[b].update(aerial=air, apex=3.6, arrival=THROUGH_ARRIVAL)
        return True

    @staticmethod
    def flight_t_end(sim: Simulator) -> float:
        """Seconds until the ball in flight arrives."""
        return float(sim.flight_t0 + sim.flight_plan.get("end_time", 0.0) - sim.t)

    def _go(self, sim: Simulator) -> None:
        c = self.creator
        self.run_started, self.run_t = True, sim.t
        sim.set_intent(c, "run", self.run_target, 0.95, until=sim.t + 4.5, data={"kind": "third_man_run"})
        sim.lock_until[c] = sim.t + 3.5
        sim.log_intent(c, "third_man_run", 0.02)

    def step(self, sim: Simulator) -> bool:
        t, a, b, c = self.team, self.passer, self.link, self.creator
        elapsed = sim.t - self.t_start
        if self.mode != "actual":
            if self.mode == "with" and not self.run_started and elapsed >= self.timing.get("run_at", 0.6):
                self._go(sim)  # the same timing as the real run
            if elapsed >= self.timing.get("measure_at", 2.5):
                self._measure(sim)
                return self._end(sim, True, "counterfactual measured")
            return False
        if self.pass1_t is None:
            if sim.ball_state == "flight" and sim.flight_plan.get("passer") == a:
                self.pass1_t = sim.t
                self.pass1_event = sim.flight_plan.get("event")
            elif sim.possession != t:
                return self._end(sim, False, "lost the ball before the first pass")
            elif elapsed > 4.0:
                return self._end(sim, False, "the pass to the link never came")
            elif sim.owner == a:
                sim.next_decision[a] = min(sim.next_decision[a], sim.t)
            return False
        if not self.run_started:
            left = (self.flight_t_end(sim) if sim.ball_state == "flight" else 0.0)
            if left <= 0.5 or sim.owner == b:
                self.timing["run_at"] = elapsed
                self._go(sim)
        if self.b_recv_t is None:
            if sim.owner == b:
                self.b_recv_t = sim.t
                sim.directives[b] = {"action": "pass", "to": c, "hold": True, "subtype": "through",
                                     "when": self._pass2_when, "point_fn": lambda s: self.ball_point}
            elif sim.possession != t or sim.t - self.pass1_t > 3.0:
                outcome = (self.pass1_event or {}).get("outcome")
                return self._end(sim, False, f"the pass to the link didn't arrive ({outcome})")
            return False
        if self.pass2_t is None:
            if sim.ball_state == "flight" and sim.flight_plan.get("passer") == b:
                self.pass2_t = sim.t
                self.pass2_event = sim.flight_plan.get("event")
                self.timing["measure_at"] = elapsed
                self._measure(sim)
                if self.spec.outcome in ("goal", "shot"):
                    sim.directives[c] = {"action": "shoot_on_receive"}
            elif sim.possession != t:
                return self._end(sim, False, "lost the ball before the lay-off")
            elif sim.t - self.b_recv_t > 2.0:
                return self._end(sim, False, f"the lay-off never came (best lane {self.best_lane_p:.2f})")
            elif sim.owner == b:
                sim.next_decision[b] = min(sim.next_decision[b], sim.t)
            return False
        if self.received_t is None:
            if sim.owner == c:
                self.received_t = sim.t
                self.beyond = tx(sim, t, sim.pos[c])[0] - offside_line_team(sim, t)
            elif sim.possession != t or sim.t - self.pass2_t > 4.0:
                return self.finish(sim)
            return False
        return self._await_finish(sim, self.received_t, c)

    def release(self, sim: Simulator) -> None:
        super().release(sim)
        if self.link >= 0:
            sim.directives.pop(self.link, None)

    def _measure(self, sim: Simulator) -> None:
        ctrl = team_control(sim, self.team, self.cells)
        values = np.array([location_value(*tx(sim, self.team, p)) for p in self.cells])
        self.result.area_m2 = float(ctrl.sum() * ZONE_STEP * ZONE_STEP)
        self.result.zone_value = float((ctrl * values).mean())
        self.result.control_gain = float(ctrl.mean()) - self.control_start
        self.result.ghost_track = [(sim.t, float(sim.pos[self.creator][0]), float(sim.pos[self.creator][1]))]

    def causal_check(self, space_created_m2: float, gap_opens_without: bool) -> tuple[bool, str]:
        if gap_opens_without:
            return False, "the space in behind was there without the run"
        if space_created_m2 < 15.0:
            return False, "the run won too little space in behind"
        return True, "ok"

    def verify(self, sim: Simulator) -> tuple[bool, str]:
        s = self.result.signals
        s["run_before_link_receives"] = (1.0 if self.b_recv_t is not None and self.run_t is not None
                                         and self.run_t < self.b_recv_t else 0.0)
        s["passes"] = 2.0 if self.pass2_event is not None else (1.0 if self.pass1_event is not None else 0.0)
        s["line_broken_m"] = round(self.beyond, 2) if self.beyond is not None else 0.0
        if (self.pass1_event or {}).get("outcome") != "complete":
            return False, "the pass to the link didn't arrive"
        if self.pass2_event is None:
            return False, "no lay-off"
        if self.pass2_event.get("outcome") == "offside":
            return False, "the third man was offside"
        if self.beyond is None or self.pass2_event.get("outcome") != "complete":
            return False, f"the lay-off didn't arrive ({self.pass2_event.get('outcome')})"
        if self.beyond < 1.0:
            return False, "the line wasn't broken"
        return self._check_outcome()


class TimedRunInBehind(_Finish, MomentPlan):
    """A runner on the last defender's shoulder times his run to beat the offside line and is found in behind
    (PRD 12.7, Timed run in behind)."""

    kind = "timed_run_in_behind"
    max_wait_s = 240.0
    max_run_s = 10.0
    gap_threshold = 0.40

    def _runner(self, sim: Simulator, owner: int) -> int:
        t = self.team
        c = self.slot(sim, self.spec.creator_id, t)
        if c >= 0:
            return c
        cands = [i for i in sim.active_of(t) if sim.role[i] in FORWARD_ROLES and i != owner]
        return max(cands, key=lambda i: tx(sim, t, sim.pos[i])[0]) if cands else -1

    def ready(self, sim: Simulator) -> bool:
        t = self.team
        if sim.possession != t or sim.owner < 0 or sim.team_of[sim.owner] != t:
            return False
        o = sim.owner
        ox, _ = tx(sim, t, sim.pos[o])
        if not (35 <= ox <= 78) or sim.role[o] == "GK":
            return False
        opp = [k for k in sim.active_of(1 - t) if sim.role[k] != "GK"]
        if pressure_on(sim.pos[o], sim.pos[opp]) > 0.45:
            return False
        line = sim.offside_cache[t]
        if line > 84.0:
            return False  # no room in behind
        c = self._runner(sim, o)
        if c < 0 or c == o:
            return False
        cx, cy = tx(sim, t, sim.pos[c])
        if not (line - 6.0 <= cx <= line - 1.5) or abs(cy - W / 2) > 24 or not (12.0 <= _dist(sim, o, c) <= 40.0):
            return False  # onside, a few metres off the line, and within range of the passer
        wanted = self.slot(sim, self.spec.dragged_id, 1 - t)
        line_men = [k for k in opp if tx(sim, t, sim.pos[k])[0] >= line - 3.0] if wanted < 0 else [wanted]
        if not line_men:
            return False
        self.creator, self.receiver, self.passer = c, c, o
        self.dragged = min(line_men, key=lambda k: _dist(sim, k, c))
        return True

    def steer(self, sim: Simulator) -> None:
        """While waiting, the runner plays on the last defender's shoulder, as strikers do."""
        t = self.team
        if sim.possession != t or sim.frame % 25:
            return
        c = self._runner(sim, sim.owner)
        if c < 0 or sim.owner == c or sim.lock_until[c] > sim.t:
            return
        _, cy = tx(sim, t, sim.pos[c])
        spot = to_abs(sim, t, sim.offside_cache[t] - 3.0, float(np.clip(cy, 10, W - 10)))
        sim.set_intent(c, "support", spot, 0.6, until=sim.t + 1.1)
        sim.lock_until[c] = sim.t + 1.0

    def start(self, sim: Simulator) -> None:
        t, c, d, o = self.team, self.creator, self.dragged, self.passer
        line = sim.offside_cache[t]
        _, cy = tx(sim, t, sim.pos[c])
        ty = float(np.clip(cy + (W / 2 - cy) * 0.3, 6, W - 6))
        self.run_target = to_abs(sim, t, min(line + 15.0, L - 7.0), ty)
        centre = to_abs(sim, t, min(line + 7.0, L - 8.0), ty)
        self.zone = rect(float(centre[0]), float(centre[1]), 7.0, 6.0)
        self.cells = zone_cells(self.zone)
        self.control_start = float(team_control(sim, t, self.cells).mean())
        self.ball_point = self.run_target.copy()
        self.closest, self.best_lane_p = 99.0, 0.0
        self.release_margin: float | None = None
        self.beyond: float | None = None
        self.pass_t: float | None = None
        self.pass_event: dict | None = None
        self.received_t: float | None = None
        self.result.creator = sim.pid(c)
        self.result.dragged = [sim.pid(d)]
        self.result.receiver = sim.pid(c)
        self.result.gap_zone = self.zone
        if self.mode == "without":
            sim.set_intent(c, "anchor", None, 0.5)
            sim.lock_until[c] = sim.t + self.max_run_s
            sim.log_intent(c, "hold_position", 0.0)
        else:
            sim.set_intent(c, "run", self.run_target, 0.98, until=sim.t + 3.6, data={"kind": "timed_run"})
            sim.lock_until[c] = sim.t + 3.2
            sim.log_intent(c, "timed_run_in_behind", 0.02)
        if self.mode == "actual":
            sim.directives[o] = {"action": "pass", "to": c, "hold": True, "subtype": "through",
                                 "when": self._pass_when, "point_fn": lambda s: self.ball_point}

    def _pass_when(self, sim: Simulator) -> bool:
        # Release as he reaches the line at speed: still level, about to be clean through.
        t, o, c = self.team, sim.owner, self.creator
        if o < 0:
            return False
        line = offside_line_team(sim, t)
        cx, _ = tx(sim, t, sim.pos[c])
        forward = float(sim.vel[c][0]) * sim.teams[t].direction
        self.closest = min(self.closest, abs(cx - line))
        if not (line - 3.0 <= cx <= line + 0.25) or forward < 2.5:
            return False
        best_p, pt, best_air = _through_ball(sim, t, o, c, self.run_target)
        self.best_lane_p = max(self.best_lane_p, best_p)
        if pt is None or best_p < 0.3:
            return False
        self.ball_point = pt
        self.release_margin = line - cx
        sim.idata[c]["point"] = pt  # the runner bends his run onto the ball
        if o in sim.directives:
            sim.directives[o].update(aerial=best_air, apex=3.6, arrival=THROUGH_ARRIVAL)
        return True

    def step(self, sim: Simulator) -> bool:
        t, c = self.team, self.creator
        elapsed = sim.t - self.t_start
        if self.mode != "actual":
            if elapsed >= self.timing.get("measure_at", 2.0):
                self._measure(sim)
                return self._end(sim, True, "counterfactual measured")
            return False
        if self.pass_t is None:
            if sim.ball_state == "flight" and sim.flight_plan.get("passer") == self.passer:
                self.pass_t = sim.t
                self.timing["measure_at"] = elapsed
                self._measure(sim)
                self.pass_event = sim.flight_plan.get("event")
                if self.spec.outcome in ("goal", "shot"):
                    sim.directives[c] = {"action": "shoot_on_receive"}
            elif sim.possession != t:
                return self._end(sim, False, "lost the ball before the pass")
            elif elapsed > 5.0:
                return self._end(sim, False, f"the pass never came while he was onside (best lane "
                                             f"{self.best_lane_p:.2f}, closest to the line {self.closest:.1f} m)")
            elif sim.owner == self.passer:
                sim.next_decision[self.passer] = min(sim.next_decision[self.passer], sim.t)  # watch for the moment
            return False
        if self.received_t is None:
            if sim.owner == c:
                self.received_t = sim.t
                self.beyond = tx(sim, t, sim.pos[c])[0] - offside_line_team(sim, t)
            elif sim.possession != t or sim.t - self.pass_t > 4.0:
                return self.finish(sim)
            return False
        return self._await_finish(sim, self.received_t, c)

    def _measure(self, sim: Simulator) -> None:
        ctrl = team_control(sim, self.team, self.cells)
        values = np.array([location_value(*tx(sim, self.team, p)) for p in self.cells])
        self.result.area_m2 = float(ctrl.sum() * ZONE_STEP * ZONE_STEP)
        self.result.zone_value = float((ctrl * values).mean())
        self.result.control_gain = float(ctrl.mean()) - self.control_start
        self.result.ghost_track = [(sim.t, float(sim.pos[self.creator][0]), float(sim.pos[self.creator][1]))]

    def causal_check(self, space_created_m2: float, gap_opens_without: bool) -> tuple[bool, str]:
        if gap_opens_without:
            return False, "the space in behind was there without the run"
        if space_created_m2 < 15.0:
            return False, "the run won too little space in behind"
        return True, "ok"

    def verify(self, sim: Simulator) -> tuple[bool, str]:
        s = self.result.signals
        margin = self.release_margin if self.release_margin is not None else -99.0
        s["onside_margin_m"] = round(margin, 2)
        s["onside_at_release"] = 1.0 if margin >= -0.3 else 0.0
        s["beyond_line_on_receipt_m"] = round(self.beyond, 2) if self.beyond is not None else 0.0
        if self.pass_event is None:
            return False, "no pass"
        if margin < -0.3 or self.pass_event.get("outcome") == "offside":
            return False, "offside at release"
        if self.beyond is None or self.pass_event.get("outcome") != "complete":
            return False, f"the pass in behind didn't arrive ({self.pass_event.get('outcome')})"
        if self.beyond < 3.0:
            return False, "not clear of the line on receipt"
        return self._check_outcome()


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    na, nb = float(np.linalg.norm(a)), float(np.linalg.norm(b))
    if na < 1e-6 or nb < 1e-6:
        return 0.0
    return float(a @ b / (na * nb))


def _inside(point: np.ndarray, polygon: list[tuple[float, float]], pad: float = 0.0) -> bool:
    xs = [p[0] for p in polygon]
    ys = [p[1] for p in polygon]
    return min(xs) - pad <= point[0] <= max(xs) + pad and min(ys) - pad <= point[1] <= max(ys) + pad


PLANS: dict[str, type[MomentPlan]] = {
    "decoy_run": DecoyRun,
    "null_run": NullRun,
    "overlap": Overlap,
    "null_overlap": NullOverlap,
    "timed_run_in_behind": TimedRunInBehind,
    "underlap": Underlap,
    "third_man_run": ThirdManRun,
}


def make_plan(spec: StoryMoment, sim: Simulator, mode: CounterfactualMode = "actual",
              timing: dict[str, float] | None = None) -> MomentPlan:
    try:
        cls = PLANS[spec.type]
    except KeyError as exc:
        raise NotImplementedError(f"No choreography for {spec.type} yet") from exc
    return cls(spec, sim, mode=mode, timing=timing)


def angle_between(a: np.ndarray, b: np.ndarray) -> float:
    na, nb = float(np.linalg.norm(a)), float(np.linalg.norm(b))
    if na < 1e-9 or nb < 1e-9:
        return 0.0
    return math.acos(float(np.clip(a @ b / (na * nb), -1, 1)))


# The team and passing moments live in their own module, which registers them in PLANS when imported.
import offball.generator.moments_extra  # noqa: E402, F401
