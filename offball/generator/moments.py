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

    def __init__(self, spec: StoryMoment, sim: Simulator, mode: CounterfactualMode = "actual",
                 timing: dict[str, float] | None = None) -> None:
        self.spec = spec
        self.team = 0 if sim.teams[0].club.club_id == spec.team else 1
        self.mode = mode
        self.timing = timing or {}
        self.state = "wait"
        self.t0 = sim.t
        self.t_start = 0.0
        self.result = PlanResult()
        self.creator = self.dragged = self.receiver = self.passer = -1

    # ------------------------------------------------------------------ lifecycle
    def tick(self, sim: Simulator) -> bool:
        if self.state == "wait":
            if sim.t - self.t0 > self.max_wait_s:
                return self._end(sim, False, "preconditions never arose")
            if sim.ball_state != "dead" and self.mode == "actual":
                self.steer(sim)
            if sim.ball_state != "dead" and self.ready(sim):
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
                    sim.directives[r] = {"action": "shoot_on_receive"}
            elif sim.possession != t:
                return self._end(sim, False, "lost the ball before the pass")
            elif elapsed > 7.0:
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
