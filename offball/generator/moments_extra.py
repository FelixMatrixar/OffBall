"""More story moments (PRD 12.7): team and passing moments built on the same choreography machinery as the runs
in `moments.py`. Each waits for its preconditions, gives intents to named roles as soft constraints, lets the
true probability models decide what happens, and verifies the signals the moment must leave.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from offball.generator.engine.geometry import L, W, rect
from offball.generator.engine.models import location_value, plan_aerial, plan_ground, pressure_on
from offball.generator.moments import (
    FORWARD_ROLES,
    FULL_BACK_ROLES,
    PLANS,
    THROUGH_ARRIVAL,
    ZONE_STEP,
    MomentPlan,
    _dist,
    _Finish,
    _separation,
    _through_ball,
    team_control,
    to_abs,
    tx,
    zone_cells,
)

if TYPE_CHECKING:
    from offball.generator.engine.sim import Simulator

WIDE_ROLES = ("RW", "LW", "RM", "LM", "RWB", "LWB", *FULL_BACK_ROLES)
LINK_ROLES = ("ST", "AM", "CM", "RW", "LW", "RM", "LM")


def _outfield(sim: Simulator, team: int) -> list[int]:
    return [k for k in sim.active_of(team) if sim.role[k] != "GK"]


class _PassMoment(_Finish, MomentPlan):
    """A moment that sets up a situation and is completed by a pass to the receiver: wait for the pass, record
    what the receipt looked like, then for the shot or the move breaking down."""

    max_wait_s = 240.0
    max_run_s = 10.0
    pass_window_s = 5.0
    measure_default = 2.0
    receive_window_s = 4.0

    def _common_start(self, sim: Simulator, zone: list[tuple[float, float]]) -> None:
        self.zone = zone
        self.cells = zone_cells(zone)
        self.control_start = float(team_control(sim, self.team, self.cells).mean())
        self.pass_t: float | None = None
        self.pass_event: dict | None = None
        self.received_t: float | None = None
        self.best_lane_p = 0.0
        self.pass_point = sim.pos[self.receiver].copy()
        self.pass_air = False
        self.result.creator = sim.pid(self.creator)
        self.result.receiver = sim.pid(self.receiver) if self.receiver >= 0 else None
        self.result.gap_zone = zone

    def _direct_pass(self, sim: Simulator, subtype: str | None = None, apex: float = 3.2) -> None:
        if self.mode == "actual":
            sim.directives[self.passer] = {"action": "pass", "to": self.receiver, "hold": True, "subtype": subtype,
                                           "apex": apex, "when": self._pass_when, "point_fn": lambda s: self.pass_point}

    def _lane(self, sim: Simulator, point: np.ndarray, aerial: bool, apex: float = 3.2, arrival: float | None = None
              ) -> float:
        o, r = sim.owner, self.receiver
        flight = (plan_aerial(sim.pos[o].copy(), point.copy(), apex=apex) if aerial
                  else plan_ground(sim.pos[o].copy(), point.copy(), arrival_speed=arrival or sim.params.pass_arrival))
        return sim.assess(o, r, flight).p_success

    def _pass_when(self, sim: Simulator) -> bool:
        raise NotImplementedError

    def _track(self, sim: Simulator) -> None:
        """Per-tick signal bookkeeping while the moment runs."""

    def _on_receipt(self, sim: Simulator) -> None:
        """What to record when the receiver gets the ball."""

    def step(self, sim: Simulator) -> bool:
        t, r = self.team, self.receiver
        elapsed = sim.t - self.t_start
        self._track(sim)
        if self.mode != "actual":
            if elapsed >= self.timing.get("measure_at", self.measure_default):
                self._measure(sim)
                return self._end(sim, True, "counterfactual measured")
            return False
        if self.pass_t is None:
            if sim.ball_state == "flight" and sim.flight_plan.get("passer") == self.passer:
                self.pass_t = sim.t
                self.pass_event = sim.flight_plan.get("event")
                if self.spec.outcome in ("goal", "shot"):
                    sim.directives[r] = {"action": "shoot_on_receive"}
            elif sim.possession != t:
                return self._end(sim, False, "lost the ball before the pass")
            elif elapsed > self.pass_window_s:
                return self._end(sim, False, f"the pass never came (best lane {self.best_lane_p:.2f})")
            elif sim.owner == self.passer:
                sim.next_decision[self.passer] = min(sim.next_decision[self.passer], sim.t)
            return False
        if self.received_t is None:
            if sim.owner == r:
                self.received_t = sim.t
                self.timing["measure_at"] = elapsed
                self._measure(sim)
                self._on_receipt(sim)
            elif sim.possession != t or sim.t - self.pass_t > self.receive_window_s:
                return self.finish(sim)
            return False
        return self._await_finish(sim, self.received_t, r)

    def _measure(self, sim: Simulator) -> None:
        ctrl = team_control(sim, self.team, self.cells)
        values = np.array([location_value(*tx(sim, self.team, p)) for p in self.cells])
        self.result.area_m2 = float(ctrl.sum() * ZONE_STEP * ZONE_STEP)
        self.result.zone_value = float((ctrl * values).mean())
        self.result.control_gain = float(ctrl.mean()) - self.control_start
        self.result.ghost_track = [(sim.t, float(sim.pos[self.creator][0]), float(sim.pos[self.creator][1]))]

    def causal_check(self, space_created_m2: float, gap_opens_without: bool) -> tuple[bool, str]:
        if gap_opens_without:
            return False, "the space was there without the creator's decision"
        if space_created_m2 < 10.0:
            return False, "the creator's decision made too little difference"
        return True, "ok"

    def _received(self) -> tuple[bool, str]:
        outcome = (self.pass_event or {}).get("outcome")
        if self.pass_event is None:
            return False, "no pass"
        if outcome == "offside":
            return False, "offside"
        if self.received_t is None or outcome != "complete":
            return False, f"the pass didn't arrive ({outcome})"
        return True, "ok"


# ------------------------------------------------------------------------------------------------ switch of play


class SwitchOfPlay(_PassMoment):
    """The ball goes across quickly to the far winger, who has held his width, and the block can't shift in time:
    he is isolated one against one (PRD 12.7, Switch of play). The winger is the creator: holding the width is
    the decision the counterfactual removes."""

    kind = "switch_of_play"
    measure_default = 2.5
    receive_window_s = 5.5

    def ready(self, sim: Simulator) -> bool:
        t = self.team
        if sim.possession != t or sim.owner < 0 or sim.team_of[sim.owner] != t:
            return False
        o = sim.owner
        ox, oy = tx(sim, t, sim.pos[o])
        if sim.role[o] == "GK" or not (25 <= ox <= 75) or abs(oy - W / 2) < 5:
            return False
        if pressure_on(sim.pos[o], sim.pos[_outfield(sim, 1 - t)]) > 0.5:
            return False
        side = 1.0 if oy > W / 2 else -1.0
        wanted = self.slot(sim, self.spec.creator_id, t)
        cands = [wanted] if wanted >= 0 else [i for i in sim.active_of(t) if sim.role[i] in WIDE_ROLES]
        for w in cands:
            wx, wy = tx(sim, t, sim.pos[w])
            if w == o or (wy - W / 2) * side > -14.0 or not (ox - 15 <= wx <= ox + 30):
                continue
            if not (28.0 <= _dist(sim, o, w) <= 55.0) or _separation(sim, t, w) < 6.0:
                continue
            self.creator, self.receiver, self.passer = w, w, o
            self.dragged = int(min(_outfield(sim, 1 - t), key=lambda k: _dist(sim, k, w)))
            return True
        return False

    def start(self, sim: Simulator) -> None:
        t, w = self.team, self.creator
        self._common_start(sim, rect(float(sim.pos[w][0]), float(sim.pos[w][1]), 7.0, 7.0))
        self.result.dragged = [sim.pid(self.dragged)]
        self.series: list[tuple[float, float, float]] = []
        self.space: float | None = None
        if self.mode == "without":
            # The counterfactual: the winger comes inside instead of holding the touchline.
            wx, wy = tx(sim, t, sim.pos[w])
            sim.set_intent(w, "support", to_abs(sim, t, wx, W / 2 + np.sign(wy - W / 2) * 4.0), 0.7, until=sim.t + 6.0)
            sim.lock_until[w] = sim.t + self.max_run_s
            sim.log_intent(w, "come_inside", 0.0)
        else:
            sim.set_intent(w, "support", sim.pos[w].copy(), 0.3, until=sim.t + 3.0)
            sim.lock_until[w] = sim.t + 2.0
            sim.log_intent(w, "hold_width", 0.02)
        self._direct_pass(sim, subtype="switch", apex=6.0)

    def _pass_when(self, sim: Simulator) -> bool:
        if sim.owner < 0:
            return False
        w = self.receiver
        pt = np.clip(sim.pos[w] + sim.vel[w] * 1.0, [1.0, 1.0], [L - 1.0, W - 1.0])
        p = self._lane(sim, pt, aerial=True, apex=6.0)
        self.best_lane_p = max(self.best_lane_p, p)
        if p < 0.45:
            return False
        self.pass_point = pt
        if sim.owner in sim.directives:
            sim.directives[sim.owner]["aerial"] = True
        return True

    def _track(self, sim: Simulator) -> None:
        if sim.frame % 2 == 0:
            block = sim.pos[_outfield(sim, 1 - self.team)][:, 1]
            self.series.append((sim.t, float(sim.ball_pos[1]), float(block.mean())))

    def _on_receipt(self, sim: Simulator) -> None:
        self.space = _separation(sim, self.team, self.receiver)

    def block_lag(self) -> float:
        """How long after the ball the defensive block got halfway across, s."""
        if self.pass_t is None or self.received_t is None:
            return 0.0
        s = np.array(self.series)
        if len(s) < 5:
            return 0.0
        after = s[s[:, 0] >= self.pass_t]
        b0, k0 = after[0, 1], after[0, 2]
        b_rec = after[after[:, 0] <= self.received_t + 0.05][-1, 1]
        k_end = after[min(len(after) - 1, int(np.searchsorted(after[:, 0], self.received_t + 3.0)))][2]
        ball_move, block_move = b_rec - b0, k_end - k0
        if abs(ball_move) < 1.0 or block_move * ball_move <= 0:
            return 0.0
        t_ball = after[np.argmax(np.abs(after[:, 1] - b0) >= 0.5 * abs(ball_move)), 0]
        moved = (after[:, 2] - k0) * np.sign(block_move) >= 0.5 * abs(block_move)
        t_block = after[np.argmax(moved), 0] if moved.any() else after[-1, 0]
        return float(t_block - t_ball)

    def verify(self, sim: Simulator) -> tuple[bool, str]:
        s = self.result.signals
        lag = self.block_lag()
        s["block_shift_lag_s"] = round(lag, 2)
        s["winger_space_m"] = round(self.space, 2) if self.space is not None else 0.0
        ok, why = self._received()
        if not ok:
            return ok, why
        if lag < 1.5:
            return False, f"the block shifted in time ({lag:.1f} s behind the ball)"
        if (self.space or 0.0) < 5.0:
            return False, "the winger had no room on the ball"
        return self._check_outcome()


# ------------------------------------------------------------------------------------------------ press broken


class PressBroken(_PassMoment):
    """A high press commits four or more players, and one pass into the player who has found the pocket behind it
    beats them (PRD 12.7, Press broken). The receiver is the creator: finding the pocket is his decision."""

    kind = "press_broken"
    measure_default = 1.5
    LOFTS = (4.0, 8.0)  # apexes of a chip and of a ball lofted over the press, m
    carried = (*MomentPlan.carried, "pressers")

    def _pressers(self, sim: Simulator, o: int) -> list[int]:
        return [k for k in _outfield(sim, 1 - self.team) if _dist(sim, k, o) < 22.0]

    def ready(self, sim: Simulator) -> bool:
        t = self.team
        if sim.possession != t or sim.owner < 0 or sim.team_of[sim.owner] != t:
            return False
        o = sim.owner
        ox, _ = tx(sim, t, sim.pos[o])
        if not (5 <= ox <= 50):
            return False
        pressers = self._pressers(sim, o)
        if len(pressers) < 4:
            return False
        opp = _outfield(sim, 1 - t)
        wanted = self.slot(sim, self.spec.creator_id, t)
        cands = [wanted] if wanted >= 0 else [i for i in sim.active_of(t) if sim.role[i] in LINK_ROLES]
        pockets = []
        for r in cands:
            rx, _ = tx(sim, t, sim.pos[r])
            if r == o or rx < ox + 10 or not (12.0 <= _dist(sim, o, r) <= 40.0) or _separation(sim, t, r) < 2.5:
                continue
            if sum(tx(sim, t, sim.pos[k])[0] > rx for k in opp) > 4:
                continue  # not beyond the press
            a, b = sim.pos[o].copy(), sim.pos[r].copy()
            lane = max(sim.assess(o, r, flight).p_success for flight in (
                plan_ground(a, b, arrival_speed=sim.params.pass_arrival),
                *(plan_aerial(a, b, apex=h) for h in self.LOFTS)))
            pockets.append((lane, r))
        if not pockets:
            return False
        # The player in the pocket the passer can actually find.
        _, r = max(pockets)
        self.creator, self.receiver, self.passer = r, r, o
        self.pressers = sorted(pressers, key=lambda k: _dist(sim, k, o))[:4]
        self.dragged = self.pressers[0]
        return True

    def start(self, sim: Simulator) -> None:
        r = self.creator
        self._common_start(sim, rect(float(sim.pos[r][0]), float(sim.pos[r][1]), 6.0, 6.0))
        self.result.dragged = [sim.pid(k) for k in self.pressers]
        self.committed = len(self._pressers(sim, self.passer))
        self.bypassed: int | None = None
        self.transition = 0.0
        if self.mode == "without":
            # The counterfactual: the receiver drops back towards the ball instead of holding the pocket.
            sim.set_intent(r, "support", (sim.pos[r] + sim.pos[self.passer]) / 2, 0.6, until=sim.t + 5.0)
            sim.lock_until[r] = sim.t + self.max_run_s
            sim.log_intent(r, "drop_short", 0.0)
        else:
            sim.set_intent(r, "support", sim.pos[r].copy(), 0.3, until=sim.t + 3.0)
            sim.lock_until[r] = sim.t + 1.5
            sim.log_intent(r, "find_the_pocket", 0.02)
        self._direct_pass(sim)

    def _pass_when(self, sim: Simulator) -> bool:
        if sim.owner < 0:
            return False
        r = self.receiver
        pt = np.clip(sim.pos[r] + sim.vel[r] * 0.4, [1.0, 1.0], [L - 1.0, W - 1.0])
        # Through the press along the ground, or chipped or lofted over it.
        options = [(self._lane(sim, pt, False), False, 3.2)] + [(self._lane(sim, pt, True, apex=h), True, h)
                                                                for h in self.LOFTS]
        best = max(options, key=lambda x: x[0])
        self.best_lane_p = max(self.best_lane_p, best[0])
        if best[0] < 0.3:
            return False  # breaking a press is a risky ball
        self.pass_point, self.pass_air = pt, best[1]
        if sim.owner in sim.directives:
            sim.directives[sim.owner].update(aerial=best[1], apex=best[2])
        return True

    def _track(self, sim: Simulator) -> None:
        if self.mode != "without" and self.pass_t is None and sim.frame % 5 == 0:
            _drift_into_space(sim, self.team, self.receiver)

    def _on_receipt(self, sim: Simulator) -> None:
        t = self.team
        bx, _ = tx(sim, t, sim.ball_pos[:2])
        opp = _outfield(sim, 1 - t)
        goal_side = [k for k in opp if tx(sim, t, sim.pos[k])[0] > bx]
        self.bypassed = len(opp) - len(goal_side)
        ahead = [i for i in _outfield(sim, t) if tx(sim, t, sim.pos[i])[0] >= bx - 2.0
                 and float(np.linalg.norm(sim.pos[i] - sim.ball_pos[:2])) < 25.0]
        near_def = [k for k in goal_side if float(np.linalg.norm(sim.pos[k] - sim.ball_pos[:2])) < 25.0]
        self.transition = 1.0 if len(ahead) >= 2 and len(near_def) <= 3 else 0.0

    def verify(self, sim: Simulator) -> tuple[bool, str]:
        s = self.result.signals
        s["pressers_committed"] = float(self.committed)
        s["defenders_bypassed"] = float(self.bypassed or 0)
        s["transition_2v3"] = self.transition
        ok, why = self._received()
        if not ok:
            return ok, why
        if self.committed < 4:
            return False, "the press wasn't committed"
        if (self.bypassed or 0) < 6:
            return False, "the pass didn't beat the press"
        if self.transition < 1.0:
            return False, "no overload in transition"
        return self._check_outcome()


# ------------------------------------------------------------------------------------------------ pinning


class Pinning(_PassMoment):
    """One attacker holds two defenders, and the teammate they would have picked up receives with room
    (PRD 12.7, Pinning). The pinning attacker is the creator; the freed teammate receives."""

    kind = "pinning"
    max_run_s = 9.0
    pass_window_s = 6.0
    carried = (*MomentPlan.carried, "pinned_by")

    def _pinners(self, sim: Simulator, p: int) -> list[int]:
        return [k for k in _outfield(sim, 1 - self.team) if _dist(sim, k, p) < 5.0]

    def steer(self, sim: Simulator) -> None:
        """While waiting, the striker plays in the seam between the two centre-backs, as strikers do."""
        t = self.team
        if sim.possession != t or sim.frame % 25:
            return
        wanted = self.slot(sim, self.spec.creator_id, t)
        pins = [wanted] if wanted >= 0 else [i for i in sim.active_of(t) if sim.role[i] == "ST"]
        cbs = [k for k in sim.active_of(1 - t) if sim.role[k] == "CB"]
        for p in pins:
            if p == sim.owner or sim.lock_until[p] > sim.t or len(cbs) < 2:
                continue
            pair = sorted(cbs, key=lambda k: _dist(sim, k, p))[:2]
            seam = sim.pos[pair].mean(axis=0)
            toward_ball = sim.ball_pos[:2] - seam
            n = float(np.linalg.norm(toward_ball)) or 1.0
            sim.set_intent(p, "support", seam + toward_ball / n * 1.5, 0.6, until=sim.t + 1.1)
            sim.lock_until[p] = sim.t + 1.0

    def ready(self, sim: Simulator) -> bool:
        t = self.team
        if sim.possession != t or sim.owner < 0 or sim.team_of[sim.owner] != t:
            return False
        o = sim.owner
        ox, _ = tx(sim, t, sim.pos[o])
        if not (35 <= ox <= 80) or pressure_on(sim.pos[o], sim.pos[_outfield(sim, 1 - t)]) > 0.5:
            return False
        wanted = self.slot(sim, self.spec.creator_id, t)
        pins = [wanted] if wanted >= 0 else [i for i in sim.active_of(t) if sim.role[i] in ("ST", "AM")]
        for p in pins:
            if p == o or len(self._pinners(sim, p)) < 2:
                continue
            free = [f for f in sim.active_of(t) if f not in (o, p) and sim.role[f] in LINK_ROLES
                    and _separation(sim, t, f) >= 6.0 and 10.0 <= _dist(sim, o, f) <= 30.0 and _dist(sim, p, f) <= 25.0]
            if not free:
                continue
            self.creator, self.passer = p, o
            self.receiver = max(free, key=lambda f: _separation(sim, t, f))
            self.pinned_by = sorted(self._pinners(sim, p), key=lambda k: _dist(sim, k, p))[:2]
            self.dragged = self.pinned_by[0]
            return True
        return False

    def start(self, sim: Simulator) -> None:
        p, f = self.creator, self.receiver
        self._common_start(sim, rect(float(sim.pos[f][0]), float(sim.pos[f][1]), 6.0, 6.0))
        self.result.dragged = [sim.pid(k) for k in self.pinned_by]
        self.pinned = self.pinned_max = 0.0
        self.space: float | None = None
        if self.mode == "without":
            # The counterfactual: the striker drifts off towards the ball and the two defenders are free.
            sim.set_intent(p, "support", (sim.pos[p] + sim.pos[self.passer]) / 2, 0.6, until=sim.t + 6.0)
            sim.lock_until[p] = sim.t + self.max_run_s
            sim.log_intent(p, "drift_off", 0.0)
        else:
            sim.set_intent(p, "support", sim.pos[p].copy(), 0.25, until=sim.t + 5.0)
            sim.lock_until[p] = sim.t + 4.0
            sim.log_intent(p, "pin_the_line", 0.02)
            # Soft constraint: a striker sitting in the seam keeps both centre-backs honest for a few seconds,
            # as real ones do. Only while he pins them, so the counterfactual leaves them free.
            for k in self.pinned_by:
                sim.set_intent(k, "mark", None, 0.6, until=sim.t + self.hold_s, data={"who": p, "decided": True})
                sim.lock_until[k] = sim.t + self.hold_s
                sim.log_intent(k, "mark_striker", 0.0)
        self._direct_pass(sim)

    hold_s = 3.0

    def _track(self, sim: Simulator) -> None:
        if sim.frame % 5 == 0 and self.received_t is None:
            self.pinned = self.pinned + 0.2 if len(self._pinners(sim, self.creator)) >= 2 else 0.0
            self.pinned_max = max(self.pinned_max, self.pinned)
            if self.mode != "without" and sim.lock_until[self.creator] > sim.t:
                # Pinning is holding a position between them as they shuffle, not standing still.
                mid = sim.pos[self.pinned_by].mean(axis=0)
                sim.idata[self.creator]["point"] = mid + (sim.pos[self.creator] - mid) * 0.3
            if self.pass_t is None:
                _drift_into_space(sim, self.team, self.receiver)

    def _pass_when(self, sim: Simulator) -> bool:
        if sim.owner < 0 or self.pinned < 2.0 or _separation(sim, self.team, self.receiver) < 5.0:
            return False
        f = self.receiver
        pt = np.clip(sim.pos[f] + sim.vel[f] * 0.4, [1.0, 1.0], [L - 1.0, W - 1.0])
        p = self._lane(sim, pt, aerial=False)
        self.best_lane_p = max(self.best_lane_p, p)
        if p < 0.5:
            return False
        self.pass_point = pt
        return True

    def _on_receipt(self, sim: Simulator) -> None:
        self.space = _separation(sim, self.team, self.receiver)

    def verify(self, sim: Simulator) -> tuple[bool, str]:
        s = self.result.signals
        s["pinned_s"] = round(self.pinned_max, 2)
        s["receiver_space_m"] = round(self.space, 2) if self.space is not None else 0.0
        ok, why = self._received()
        if not ok:
            return ok, why
        if self.pinned_max < 2.0:
            return False, "the two defenders didn't stay with him"
        if (self.space or 0.0) < 5.0:
            return False, "the free man had no room on the ball"
        return self._check_outcome()


# ------------------------------------------------------------------------------------------------ rest defence


class RestDefenceExposed(_PassMoment):
    """A turnover catches the other team without cover behind the ball, and the counter overloads a half-space
    within seconds (PRD 12.7, Rest defence exposed). The player who wins the ball is the creator; a forward
    attacks the half-space."""

    kind = "rest_defence_exposed"
    max_run_s = 8.0
    pass_window_s = 3.0
    measure_default = 2.0
    _last_n = -1

    def _behind_ball(self, sim: Simulator) -> int:
        bx, _ = tx(sim, self.team, sim.ball_pos[:2])
        return sum(tx(sim, self.team, sim.pos[k])[0] > bx for k in _outfield(sim, 1 - self.team))

    def steer(self, sim: Simulator) -> None:
        """While the other team builds up from its own half, its full-backs and holding midfielder push on beyond
        the ball, as possession sides do: a ball won there leaves them few behind it."""
        t = self.team
        if sim.possession != 1 - t or sim.frame % 25:
            return
        bx, _ = tx(sim, 1 - t, sim.ball_pos[:2])
        if not 15 <= bx <= 55:
            return
        for k in sim.active_of(1 - t):
            if sim.role[k] in (*FULL_BACK_ROLES, "DM") and k != sim.owner and sim.lock_until[k] <= sim.t:
                kx, ky = tx(sim, 1 - t, sim.pos[k])
                ahead = 8.0 if sim.role[k] in FULL_BACK_ROLES else 4.0
                sim.set_intent(k, "support", to_abs(sim, 1 - t, max(kx, bx + ahead), ky), 0.6, until=sim.t + 1.1)
                sim.lock_until[k] = sim.t + 1.0
        # ...and we press the ball there, as a side does when it smells a high turnover.
        if sim.owner >= 0:
            near = sorted(_outfield(sim, t), key=lambda i: _dist(sim, i, sim.owner))[:3]
            for i in near:
                if _dist(sim, i, sim.owner) < 25.0 and sim.lock_until[i] <= sim.t:
                    sim.set_intent(i, "press", None, 0.85)
                    sim.lock_until[i] = sim.t + 1.0

    def ready(self, sim: Simulator) -> bool:
        t = self.team
        n, self._last_n = self._last_n, sim.possession_n
        if n < 0 or sim.possession_n == n or sim.possession != t or sim.owner < 0 or sim.team_of[sim.owner] != t:
            return False  # only at the moment the ball is won
        club = sim.teams[t].club.club_id
        won = [e for e in sim.events[-3:] if e["type"] in ("interception", "tackle") and e.get("outcome") == "won"
               and e["team_id"] == club and sim.t * 1000 - e["t_ms"] < 600]
        if not won:
            return False  # won in open play, not from a restart
        bx, _ = tx(sim, t, sim.ball_pos[:2])
        if bx > 88 or self._behind_ball(sim) >= 3:
            return False  # won high up, with fewer than three of them back
        fwd = [i for i in sim.active_of(t) if sim.role[i] in FORWARD_ROLES and i != sim.owner]
        if not fwd:
            return False
        self.creator, self.passer = sim.owner, sim.owner
        self.receiver = max(fwd, key=lambda i: tx(sim, t, sim.pos[i])[0])
        self.dragged = -1
        return True

    def _half_space(self, sim: Simulator) -> tuple[float, float]:
        bx, by = tx(sim, self.team, sim.ball_pos[:2])
        _, ry = tx(sim, self.team, sim.pos[self.receiver])
        side = 1.0 if ry >= W / 2 else -1.0
        return bx + 14.0, W / 2 + side * 14.0  # 2-26 m ahead of the ball, clipped at the goal line

    def start(self, sim: Simulator) -> None:
        t, r = self.team, self.receiver
        hx, hy = self._half_space(sim)
        centre = to_abs(sim, t, hx, hy)
        self._common_start(sim, rect(float(centre[0]), float(centre[1]), 12.0, 7.0))
        self.result.dragged = []
        self.cover_short = 3 - self._behind_ball(sim)
        self.overload = -9
        self.run_target = to_abs(sim, t, min(hx + 6.0, L - 6.0), hy)
        if self.mode == "without":
            sim.set_intent(r, "anchor", None, 0.5)
            sim.lock_until[r] = sim.t + self.max_run_s
            sim.log_intent(r, "hold_position", 0.0)
        else:
            sim.set_intent(r, "run", self.run_target, 0.95, until=sim.t + 3.5, data={"kind": "counter_run"})
            sim.lock_until[r] = sim.t + 3.0
            sim.log_intent(r, "counter_run", 0.02)
        self._direct_pass(sim, subtype="through")

    def _track(self, sim: Simulator) -> None:
        if sim.frame % 5 == 0 and sim.t - self.t_start <= 3.0:
            att = sum(1 for i in sim.active_of(self.team) if _inside_rect(sim.pos[i], self.zone))
            dfn = sum(1 for k in sim.active_of(1 - self.team) if _inside_rect(sim.pos[k], self.zone))
            self.overload = max(self.overload, att - dfn)

    def _pass_when(self, sim: Simulator) -> bool:
        if sim.owner < 0:
            return False
        best_p, pt, air = _through_ball(sim, self.team, sim.owner, self.receiver, self.run_target)
        self.best_lane_p = max(self.best_lane_p, best_p)
        if pt is None or best_p < 0.3:
            return False
        self.pass_point = pt
        if sim.owner in sim.directives:
            sim.directives[sim.owner].update(aerial=air, apex=3.6, arrival=THROUGH_ARRIVAL)
        return True

    def step(self, sim: Simulator) -> bool:
        # The signals settle within 3 s of the turnover; the pass is a bonus, not a requirement.
        if self.mode == "actual" and self.pass_t is None and sim.t - self.t_start > self.pass_window_s:
            self._track(sim)
            return self.finish(sim)
        return super().step(sim)

    def verify(self, sim: Simulator) -> tuple[bool, str]:
        s = self.result.signals
        s["cover_short"] = float(self.cover_short)
        s["half_space_overload"] = float(max(self.overload, 0))
        if self.cover_short < 1:
            return False, "three or more were behind the ball"
        if self.overload < 1:
            return False, "the counter never outnumbered them in the half-space"
        return self._check_outcome()


# ------------------------------------------------------------------------------------------------ blind-side run


VIEW_CONE = np.radians(70.0)  # half-angle a defender sees without turning his head


def _angle(a: np.ndarray, b: np.ndarray) -> float:
    na, nb = float(np.linalg.norm(a)), float(np.linalg.norm(b))
    if na < 1e-6 or nb < 1e-6:
        return 0.0
    return float(np.arccos(np.clip(a @ b / (na * nb), -1.0, 1.0)))


def _facing(sim: Simulator, k: int) -> np.ndarray:
    return np.array([np.cos(sim.ori[k]), np.sin(sim.ori[k])])


class BlindSideRun(_PassMoment):
    """An attacker runs across a defender's back while the defender watches the ball (PRD 12.7, Blind-side run)."""

    kind = "blind_side_run"
    pass_window_s = 5.0
    measure_default = 1.5

    def ready(self, sim: Simulator) -> bool:
        t = self.team
        if sim.possession != t or sim.owner < 0 or sim.team_of[sim.owner] != t:
            return False
        o = sim.owner
        ox, _ = tx(sim, t, sim.pos[o])
        if not (40 <= ox <= 80) or pressure_on(sim.pos[o], sim.pos[_outfield(sim, 1 - t)]) > 0.5:
            return False
        if sim.offside_cache[t] > 88.0:
            return False
        wanted = self.slot(sim, self.spec.creator_id, t)
        runners = [wanted] if wanted >= 0 else [i for i in sim.active_of(t) if sim.role[i] in FORWARD_ROLES and i != o]
        for c in runners:
            for d in _outfield(sim, 1 - t):
                gap = _dist(sim, c, d)
                if not 3.0 <= gap <= 8.0:
                    continue
                facing = _facing(sim, d)
                if _angle(facing, sim.ball_pos[:2] - sim.pos[d]) > np.radians(50.0):
                    continue  # he isn't watching the ball
                if _angle(facing, sim.pos[c] - sim.pos[d]) <= VIEW_CONE:
                    continue  # he can see the runner
                self.creator, self.receiver, self.passer, self.dragged = c, c, o, d
                return True
        return False

    def start(self, sim: Simulator) -> None:
        t, c, d = self.team, self.creator, self.dragged
        goal = sim._own_goal(1 - t)
        g = goal - sim.pos[d]
        g = g / (float(np.linalg.norm(g)) or 1.0)
        to_ball = sim.ball_pos[:2] - sim.pos[d]
        lateral = to_ball - (to_ball @ g) * g
        lateral = lateral / (float(np.linalg.norm(lateral)) or 1.0)
        self.run_target = np.clip(sim.pos[d] + g * 10.0 + lateral * 8.0, [2.0, 2.0], [L - 2.0, W - 2.0])
        self._common_start(sim, rect(float(self.run_target[0]), float(self.run_target[1]), 6.0, 6.0))
        self.result.dragged = [sim.pid(d)]
        self.cone_angle = _angle(_facing(sim, d), sim.pos[c] - sim.pos[d])
        self.gap0 = _dist(sim, c, d)
        self.growth: float | None = None
        if self.mode == "without":
            sim.set_intent(c, "anchor", None, 0.5)
            sim.lock_until[c] = sim.t + self.max_run_s
            sim.log_intent(c, "hold_position", 0.0)
        else:
            sim.set_intent(c, "run", self.run_target, 0.95, until=sim.t + 3.0, data={"kind": "blind_side_run"})
            sim.lock_until[c] = sim.t + 2.8
            sim.log_intent(c, "blind_side_run", 0.02)
        # The defender is watching the ball, not the runner, for a moment (in every mode, so re-runs compare alike).
        sim.set_intent(d, "watch", sim.pos[d].copy(), 0.3, until=sim.t + 1.5)
        sim.lock_until[d] = sim.t + 1.5
        sim.log_intent(d, "ball_watching", 0.0)
        self._direct_pass(sim, subtype="through")

    def _track(self, sim: Simulator) -> None:
        if self.growth is None and sim.t - self.t_start >= 1.5:
            self.growth = _dist(sim, self.creator, self.dragged) - self.gap0

    def _pass_when(self, sim: Simulator) -> bool:
        if sim.owner < 0 or sim.t - self.t_start < 0.8:
            return False
        line = sim.offside_cache[self.team]
        if tx(sim, self.team, sim.pos[self.creator])[0] > line + 0.25:
            return False
        best_p, pt, air = _through_ball(sim, self.team, sim.owner, self.creator, self.run_target)
        self.best_lane_p = max(self.best_lane_p, best_p)
        if pt is None or best_p < 0.3:
            return False
        self.pass_point = pt
        if sim.owner in sim.directives:
            sim.directives[sim.owner].update(aerial=air, apex=3.6, arrival=THROUGH_ARRIVAL)
        return True

    def verify(self, sim: Simulator) -> tuple[bool, str]:
        s = self.result.signals
        s["start_outside_view_cone"] = 1.0 if self.cone_angle > VIEW_CONE else 0.0
        s["separation_growth_m"] = round(self.growth if self.growth is not None else 0.0, 2)
        if (self.growth or 0.0) < 3.3:  # clear of the 3 m signal, so the data shows it as well
            return False, "he didn't get away from the defender"
        if self.spec.outcome in ("chance", "shot", "goal"):
            ok, why = self._received()
            if not ok:
                return ok, why
        return self._check_outcome()


# ------------------------------------------------------------------------------------------------ false 9 drop


class FalseNineDrop(_Finish, MomentPlan):
    """The striker drops into midfield, the centre-back marking him steps up with him, and the space behind the
    line opens (PRD 12.7, False 9 drop)."""

    kind = "false_9_drop"
    max_wait_s = 240.0
    max_run_s = 6.0
    gap_threshold = 0.30
    follow = 0.85  # soft constraint: how inclined the centre-back is to step up with his man

    def ready(self, sim: Simulator) -> bool:
        t = self.team
        if sim.possession != t or sim.owner < 0 or sim.team_of[sim.owner] != t:
            return False
        o = sim.owner
        ox, _ = tx(sim, t, sim.pos[o])
        if not (35 <= ox <= 70):
            return False
        line = sim.offside_cache[t]
        wanted = self.slot(sim, self.spec.creator_id, t)
        strikers = [wanted] if wanted >= 0 else [i for i in sim.active_of(t) if sim.role[i] == "ST"]
        for s in strikers:
            if s == o or tx(sim, t, sim.pos[s])[0] < line - 4.0:
                continue
            cbs = [k for k in _outfield(sim, 1 - t) if _dist(sim, k, s) < 6.0 and sim._is_goal_side(k, s)]
            if not cbs:
                continue
            self.creator, self.passer, self.receiver = s, o, -1
            self.dragged = min(cbs, key=lambda k: _dist(sim, k, s))
            return True
        return False

    def start(self, sim: Simulator) -> None:
        t, s, d = self.team, self.creator, self.dragged
        self.d_start = sim.pos[d].copy()
        g = sim._own_goal(1 - t) - self.d_start
        g = g / (float(np.linalg.norm(g)) or 1.0)
        centre = self.d_start + g * 9.0
        self.zone = rect(float(centre[0]), float(centre[1]), 12.0, 8.0)
        self.cells = zone_cells(self.zone)
        self.area_start = float(team_control(sim, t, self.cells).sum())
        self.control_start = self.area_start / max(len(self.cells), 1)
        self.area_gain = 0.0
        self.step_up = 0.0
        self.result.creator = sim.pid(s)
        self.result.dragged = [sim.pid(d)]
        self.result.gap_zone = self.zone
        sx, sy = tx(sim, t, sim.pos[s])
        _, by = tx(sim, t, sim.ball_pos[:2])
        self.drop_target = to_abs(sim, t, max(sx - 14.0, 30.0), sy + (by - sy) * 0.4)
        if self.mode == "without":
            sim.set_intent(s, "anchor", None, 0.5)
            sim.lock_until[s] = sim.t + self.max_run_s
            sim.log_intent(s, "hold_position", 0.0)
        else:
            sim.set_intent(s, "run", self.drop_target, 0.85, until=sim.t + 3.5, data={"kind": "false_9_drop"})
            sim.lock_until[s] = sim.t + 3.2
            sim.log_intent(s, "false_9_drop", 0.02)
        # The centre-back decides now whether to step up with him; the director only leans on his discipline.
        sim.bias[(d, "discipline")] = (0.1, sim.t + 8.0)
        if self.mode == "without" or sim.rng.random() < self.follow:
            sim.set_intent(d, "track", None, 0.9, data={"who": s, "since": sim.t, "decided": True})
            sim.lock_until[d] = sim.t + 0.6
            sim.log_intent(d, "step_up", self.follow)
        else:
            sim.log_intent(d, "hold_line", 1 - self.follow)
        # A runner attacks the space as it opens.
        runners = [i for i in sim.active_of(t) if sim.role[i] in ("RW", "LW", "AM", "CM") and i != self.passer]
        self.runner = min(runners, key=lambda i: float(np.linalg.norm(sim.pos[i] - centre))) if runners else -1

    def step(self, sim: Simulator) -> bool:
        t, d = self.team, self.dragged
        elapsed = sim.t - self.t_start
        if elapsed <= 4.0:
            self.step_up = max(self.step_up, float(np.linalg.norm(sim.pos[d] - self.d_start)))
        if self.runner >= 0 and self.step_up >= 5.0 and sim.intent[self.runner] != "run" and self.mode != "without":
            centre = np.array(self.zone).mean(axis=0)
            sim.set_intent(self.runner, "run", centre, 0.95, until=sim.t + 2.5, data={"kind": "run_in_behind"})
            sim.lock_until[self.runner] = sim.t + 2.0
        if sim.frame % 5 == 0:
            self.area_gain = max(self.area_gain, float(team_control(sim, t, self.cells).sum()) - self.area_start)
        if elapsed >= self.timing.get("measure_at", 4.0):
            self.timing["measure_at"] = elapsed
            self._measure(sim)
            if self.mode != "actual":
                return self._end(sim, True, "counterfactual measured")
            self.result.outcome = "chance" if self.area_gain >= 150.0 else "none"
            return self.finish(sim)
        if self.mode == "actual" and sim.possession != t:
            return self._end(sim, False, "lost the ball during the drop")
        return False

    def _measure(self, sim: Simulator) -> None:
        ctrl = team_control(sim, self.team, self.cells)
        values = np.array([location_value(*tx(sim, self.team, p)) for p in self.cells])
        self.result.area_m2 = float(ctrl.sum() * ZONE_STEP * ZONE_STEP)
        self.result.zone_value = float((ctrl * values).mean())
        self.result.control_gain = float(ctrl.mean()) - self.control_start
        self.result.ghost_track = [(sim.t, float(sim.pos[self.creator][0]), float(sim.pos[self.creator][1]))]

    def causal_check(self, space_created_m2: float, gap_opens_without: bool) -> tuple[bool, str]:
        if gap_opens_without:
            return False, "the space behind opened without the drop"
        if space_created_m2 < 15.0:
            return False, "the drop created too little space"
        return True, "ok"

    def verify(self, sim: Simulator) -> tuple[bool, str]:
        s = self.result.signals
        s["cb_step_up_m"] = round(self.step_up, 2)
        s["space_behind_gain_m2"] = round(self.area_gain, 1)
        if self.step_up < 10.0:
            return False, f"the centre-back stepped up only {self.step_up:.1f} m"
        if self.area_gain < 150.0:
            return False, f"only {self.area_gain:.0f} m2 opened behind"
        return self._check_outcome() if self.spec.outcome in ("shot", "goal") else (True, "ok")


# ------------------------------------------------------------------------------------------------ cover shadow


class CoverShadow(_Finish, MomentPlan):
    """A defender steps into the lane to an open player, the pass to him is off, and the ball goes backwards or
    sideways (PRD 12.7, Cover shadow). The moment belongs to the defending team; the defender is the creator."""

    kind = "cover_shadow"
    max_wait_s = 240.0
    max_run_s = 6.0
    gap_threshold = 0.30

    def ready(self, sim: Simulator) -> bool:
        t = self.team  # the defending team
        a = 1 - t
        if sim.possession != a or sim.owner < 0 or sim.team_of[sim.owner] != a:
            return False
        o = sim.owner
        ox, _ = tx(sim, a, sim.pos[o])
        if sim.role[o] == "GK" or not (30 <= ox <= 80):
            return False
        wanted = self.slot(sim, self.spec.creator_id, t)
        for q in sim.active_of(a):
            if q == o or sim.role[q] == "GK" or not 12.0 <= _dist(sim, o, q) <= 30.0 or _separation(sim, a, q) < 5.0:
                continue
            if self._lane_p(sim, o, q) < 0.6:
                continue
            mid = (sim.pos[o] + sim.pos[q]) / 2
            cands = [wanted] if wanted >= 0 else _outfield(sim, t)
            cands = [d for d in cands if float(np.linalg.norm(sim.pos[d] - mid)) < 9.0 and _seg_dist(sim, d, o, q) > 2.5]
            if cands:
                self.creator = min(cands, key=lambda d: float(np.linalg.norm(sim.pos[d] - mid)))
                self.passer, self.receiver, self.dragged = o, q, q
                return True
        return False

    def _lane_p(self, sim: Simulator, o: int, q: int) -> float:
        flight = plan_ground(sim.pos[o].copy(), sim.pos[q].copy(), arrival_speed=sim.params.pass_arrival)
        return sim.assess(o, q, flight).p_success

    def start(self, sim: Simulator) -> None:
        t, d, o, q = self.team, self.creator, self.passer, self.receiver
        mid = (sim.pos[o] + sim.pos[q]) / 2
        span = sim.pos[q] - sim.pos[o]
        n = float(np.linalg.norm(span)) or 1.0
        perp = np.array([-span[1], span[0]]) / n
        self.zone = rect(float(mid[0]), float(mid[1]), max(abs(span[0]) / 2, 3.0), max(abs(span[1]) / 2, 3.0))
        self.cells = zone_cells(self.zone)
        self.control_start = float(team_control(sim, t, self.cells).mean())
        self.p0 = self._lane_p(sim, o, q)
        self.p_min = self.p0
        self.next_pass: dict | None = None
        self.result.creator = sim.pid(d)
        self.result.dragged = [sim.pid(q)]
        self.result.receiver = None
        self.result.gap_zone = self.zone
        # The shadow: on the line between the ball and the open man, a little nearer the ball.
        shadow = sim.pos[o] + span * 0.4
        shadow = shadow + perp * np.sign((sim.pos[d] - shadow) @ perp) * 0.5
        if self.mode == "without":
            sim.set_intent(d, "anchor", None, 0.5)
            sim.lock_until[d] = sim.t + self.max_run_s
            sim.log_intent(d, "hold_position", 0.0)
        else:
            sim.set_intent(d, "support", shadow, 0.85, until=sim.t + 3.0)
            sim.lock_until[d] = sim.t + 2.5
            sim.log_intent(d, "cover_shadow", 0.02)
        # The passer takes a look before he plays (in every mode, so the re-runs compare alike), then decides freely.
        sim.directives[o] = {"action": "pass", "to": q, "hold": True, "when": lambda s: False}
        self.look_until = sim.t + 1.6
        self.lane_gap_at_pass: float | None = None
        self.passer_gap_at_pass = 0.0
        self._events_at = len(sim.events)

    def step(self, sim: Simulator) -> bool:
        a, o, q = 1 - self.team, self.passer, self.receiver
        elapsed = sim.t - self.t_start
        if sim.t >= self.look_until and o in sim.directives and sim.directives[o].get("to") == q:
            sim.directives.pop(o, None)
        if sim.frame % 5 == 0 and sim.owner == o:
            self.p_min = min(self.p_min, self._lane_p(sim, o, q))
        if self.mode != "actual":
            if elapsed >= self.timing.get("measure_at", 1.5):
                self._measure(sim)
                return self._end(sim, True, "counterfactual measured")
            return False
        club = sim.teams[a].club.club_id
        passes = [e for e in sim.events[self._events_at:] if e["type"] == "pass" and e["team_id"] == club]
        if passes:
            self.next_pass = passes[0]
            self.lane_gap_at_pass = _seg_dist(sim, self.creator, o, q)
            self.passer_gap_at_pass = _dist(sim, self.creator, o)
            self.timing["measure_at"] = elapsed
            self._measure(sim)
            return self.finish(sim)
        if sim.possession != a:
            self.timing["measure_at"] = elapsed
            self._measure(sim)
            return self.finish(sim)
        return False

    def _measure(self, sim: Simulator) -> None:
        ctrl = team_control(sim, self.team, self.cells)
        self.result.area_m2 = float(ctrl.sum() * ZONE_STEP * ZONE_STEP)
        self.result.zone_value = float(ctrl.mean())
        self.result.control_gain = float(ctrl.mean()) - self.control_start
        self.result.ghost_track = [(sim.t, float(sim.pos[self.creator][0]), float(sim.pos[self.creator][1]))]

    def causal_check(self, space_created_m2: float, gap_opens_without: bool) -> tuple[bool, str]:
        if space_created_m2 < 10.0:
            return False, "the shadow denied too little"
        return True, "ok"

    def verify(self, sim: Simulator) -> tuple[bool, str]:
        s = self.result.signals
        drop = 100.0 * (self.p0 - self.p_min)
        s["pass_prob_drop_pts"] = round(drop, 1)
        backwards = 0.0
        if self.next_pass is not None and self.next_pass.get("end_xy"):
            a = 1 - self.team
            sx = tx(sim, a, np.array(self.next_pass["start_xy"]))[0]
            ex = tx(sim, a, np.array(self.next_pass["end_xy"]))[0]
            backwards = 1.0 if ex - sx <= 3.0 and self.next_pass.get("recipient_id") != sim.pid(self.receiver) else 0.0
        s["ball_backwards_or_sideways"] = backwards
        s["defender_lane_gap_m"] = round(self.lane_gap_at_pass, 2) if self.lane_gap_at_pass is not None else 99.0
        if drop < 30.0:
            return False, f"the lane stayed open ({drop:.0f} points)"
        if backwards < 1.0:
            return False, "the ball still went forward"
        if self.lane_gap_at_pass is None or self.lane_gap_at_pass > 2.0:
            return False, "someone else shut the lane"
        if self.passer_gap_at_pass < 3.0:
            return False, "he ended up pressing the passer, not shadowing the lane"  # as the detector judges it
        return True, "ok"


def _seg_dist(sim: Simulator, d: int, o: int, q: int) -> float:
    """Distance from player d to the passing lane between o and q."""
    a, b, p = sim.pos[o], sim.pos[q], sim.pos[d]
    ab = b - a
    s = float(np.clip((p - a) @ ab / max(float(ab @ ab), 1e-6), 0.0, 1.0))
    return float(np.linalg.norm(a + s * ab - p))


# ------------------------------------------------------------------------------------------------ rotation


class Rotation(_PassMoment):
    """Three attackers swap zones, the defenders lose their marks, and one of the three receives with room
    (PRD 12.7, Rotation). The receiver is the creator: he ends the rotation free."""

    kind = "rotation"
    pass_window_s = 6.0
    measure_default = 3.0
    carried = (*MomentPlan.carried, "trio")

    def ready(self, sim: Simulator) -> bool:
        t = self.team
        if sim.possession != t or sim.owner < 0 or sim.team_of[sim.owner] != t:
            return False
        o = sim.owner
        ox, _ = tx(sim, t, sim.pos[o])
        if not (40 <= ox <= 85):
            return False
        pool = [i for i in sim.active_of(t) if i != o and sim.role[i] in (*WIDE_ROLES, "AM", "ST", "CM")]
        opp = _outfield(sim, 1 - t)
        marked = [i for i in pool if any(_dist(sim, k, i) < 6.0 for k in opp)]
        for a in marked:
            near = sorted((i for i in marked if i != a and 6.0 <= _dist(sim, a, i) <= 20.0), key=lambda i: _dist(sim, a, i))
            for b in near:
                for c in near:
                    if c != b and 6.0 <= _dist(sim, b, c) <= 20.0:
                        self.trio = [a, b, c]
                        self.creator, self.receiver, self.passer, self.dragged = a, a, o, -1
                        return True
        return False

    def start(self, sim: Simulator) -> None:
        a, b, c = self.trio
        spots = [sim.pos[b].copy(), sim.pos[c].copy(), sim.pos[a].copy()]  # a -> b, b -> c, c -> a
        centre = np.mean([sim.pos[i] for i in self.trio], axis=0)
        self._common_start(sim, rect(float(centre[0]), float(centre[1]), 10.0, 10.0))
        self.spots = spots
        self.markers0 = [self._marker(sim, i) for i in self.trio]
        self.swapped = 0.0
        self.switched = 0.0
        self.space: float | None = None
        self.result.dragged = [sim.pid(k) for k in self.markers0 if k >= 0]
        for i, spot in zip(self.trio, spots, strict=True):
            if self.mode == "without":
                sim.set_intent(i, "anchor", None, 0.5)
                sim.lock_until[i] = sim.t + self.max_run_s
            else:
                sim.set_intent(i, "run", spot, 0.8, until=sim.t + 4.0, data={"kind": "rotation"})
                sim.lock_until[i] = sim.t + 3.5
        sim.log_intent(a, "hold_position" if self.mode == "without" else "rotation", 0.02)
        self._direct_pass(sim)

    def _marker(self, sim: Simulator, i: int) -> int:
        opp = _outfield(sim, 1 - self.team)
        return min(opp, key=lambda k: _dist(sim, k, i)) if opp else -1

    def _track(self, sim: Simulator) -> None:
        if sim.frame % 5 or self.swapped >= 1.0 or sim.t - self.t_start > 4.0:
            return
        if all(float(np.linalg.norm(sim.pos[i] - spot)) < 5.0 for i, spot in zip(self.trio, self.spots, strict=True)):
            self.swapped = 1.0
            now = [self._marker(sim, i) for i in self.trio]
            self.switched = 1.0 if any(m0 != m1 for m0, m1 in zip(self.markers0, now, strict=True)) else 0.0

    def _pass_when(self, sim: Simulator) -> bool:
        if sim.owner < 0 or self.swapped < 1.0:
            return False
        free = max(self.trio, key=lambda i: _separation(sim, self.team, i))
        if _separation(sim, self.team, free) < 4.0:
            return False
        if free != self.receiver:
            # The free man is the one to find: point the pass at him (it goes on the next look).
            self.receiver = self.creator = free
            self.result.creator = self.result.receiver = sim.pid(free)
            if sim.owner in sim.directives:
                sim.directives[sim.owner]["to"] = free
            return False
        pt = np.clip(sim.pos[free] + sim.vel[free] * 0.4, [1.0, 1.0], [L - 1.0, W - 1.0])
        p = self._lane(sim, pt, aerial=False)
        self.best_lane_p = max(self.best_lane_p, p)
        if p < 0.35:
            return False
        self.pass_point = pt
        return True

    def _on_receipt(self, sim: Simulator) -> None:
        self.space = _separation(sim, self.team, self.receiver)

    def verify(self, sim: Simulator) -> tuple[bool, str]:
        s = self.result.signals
        s["zones_swapped"] = self.swapped
        s["marker_switch"] = self.switched
        s["receiver_separation_m"] = round(self.space, 2) if self.space is not None else 0.0
        if self.swapped < 1.0:
            return False, "the three didn't complete the rotation"
        if self.switched < 1.0:
            return False, "the defenders kept their men"
        ok, why = self._received()
        if not ok:
            return ok, why
        if (self.space or 0.0) < 4.0:
            return False, "nobody came out of it free"
        return self._check_outcome()


# ------------------------------------------------------------------------------------------------ set-piece screen


class SetPieceScreen(_Finish, MomentPlan):
    """At a corner, a teammate screens the target's marker, and the target meets the delivery with more room than
    he had when it was struck (PRD 12.7, Set-piece screen). The screener is the creator; the target receives."""

    kind = "set_piece_screen"
    dead_ball_ok = True
    max_wait_s = 1500.0
    max_run_s = 8.0

    def ready(self, sim: Simulator) -> bool:
        r = sim.restart
        t = self.team
        if r is None or r["team"] != t or r["taker"] < 0 or r["ready"] - sim.t > 2.0:
            return False
        if not (r["kind"] == "corner" or (r["kind"] == "free_kick" and sim._dangerous_fk(t, r["spot"]))):
            return False  # a corner, or a free kick close enough to cross
        taker = r["taker"]
        box = [i for i in sim.active_of(t) if i != taker and sim._in_box(i)]
        if len(box) < 2:
            return False
        # The target: a good header of the ball 7-14 m out, where the keeper can't come and claim it.
        central = [i for i in box if 7.0 <= L - tx(sim, t, sim.pos[i])[0] <= 14.0]
        j = max(central or box, key=lambda i: float(sim.aerial[i]))
        opp = _outfield(sim, 1 - t)
        if not opp:
            return False
        m = min(opp, key=lambda k: _dist(sim, k, j))
        screeners = [i for i in box if i != j]
        s = min(screeners, key=lambda i: _dist(sim, i, m))
        self.creator, self.receiver, self.passer, self.dragged = s, j, taker, m
        return True

    def start(self, sim: Simulator) -> None:
        t, s, j, m = self.team, self.creator, self.receiver, self.dragged
        # The routine: the ball is aimed at the open space a few strides from the target, on the far side of
        # the screen from his marker, inside the area headers come from.
        others = [k for k in sim.active_of(1 - t) if k != m]
        best, self.delivery = -1.0, sim.pos[j].copy()
        for ang in np.linspace(0.0, 2 * np.pi, 12, endpoint=False):
            pt = sim.pos[j] + self.RUN_M * np.array([np.cos(ang), np.sin(ang)])
            px, py = tx(sim, t, pt)
            if not (6.0 <= L - px <= 14.0 and abs(py - W / 2) <= 12.0):
                continue
            room = min((float(np.linalg.norm(sim.pos[k] - pt)) for k in others), default=99.0)
            away = float(np.linalg.norm(pt - sim.pos[m])) - _dist(sim, j, m)  # moving away from the marker
            score = min(room, 6.0) + 0.5 * away
            if score > best:
                best, self.delivery = score, np.clip(pt, [1.0, 1.0], [L - 1.0, W - 1.0])
        self.zone = rect(float(self.delivery[0]), float(self.delivery[1]), 4.0, 4.0)
        self.cells = zone_cells(self.zone)
        self.control_start = float(team_control(sim, t, self.cells).mean())
        self.sep_start: float | None = None
        self.sep_end: float | None = None
        self.pass_t: float | None = None
        self.pass_event: dict | None = None
        self.result.creator = sim.pid(s)
        self.result.receiver = sim.pid(j)
        self.result.dragged = [sim.pid(m)]
        self.result.gap_zone = self.zone
        sim.log_intent(s, "hold_position" if self.mode == "without" else "screen", 0.02)
        # The rest of the routine is the same in every mode, so the counterfactual changes only the screen: the
        # target stands with his marker until he times his run onto a whipped delivery (`_react`), and the
        # marker, man-marking him as most teams do at set pieces, goes with the run a beat late.
        self._hold(sim, j, 8.0)
        sim.restart["ready"] = max(sim.restart["ready"], sim.t + 3.0)  # the taker waits for the routine to be set
        goal_side = sim._own_goal(1 - t) - sim.pos[j]
        tight = sim.pos[j] + goal_side / (float(np.linalg.norm(goal_side)) or 1.0) * 1.0
        sim.set_intent(m, "keep", None, 0.5, until=sim.t + 8.0, data={"point": tight})  # tight, goal-side
        sim.lock_until[m] = sim.t + 8.0
        sim.log_intent(m, "man_mark", 0.0)
        self.run_at: float | None = None
        self.running = self.chasing = False
        sim.directives[self.passer] = {"action": "pass", "to": j, "aerial": True, "apex": self.APEX,
                                       "point_fn": lambda sm: self.delivery}

    def _screen(self, sim: Simulator) -> None:
        """The screener stands in the marker's path to the delivery point."""
        m = self.dragged
        to_ball = self.delivery - sim.pos[m]
        block = sim.pos[m] + to_ball / (float(np.linalg.norm(to_ball)) or 1.0) * 0.8  # tight on his line to the ball
        sim.set_intent(self.creator, "run", block, 0.85, until=sim.t + 1.0, data={"kind": "screen"})
        sim.lock_until[self.creator] = sim.t + 0.8

    APEX = 3.5  # a whipped delivery, m
    RUN_S = 1.5  # the target's run starts this long before the ball arrives
    RUN_M = 4.5  # and covers this far, into the space away from his marker
    reaction_s = 0.35  # how long a marker watching the ball takes to go with his man
    # The engine's bodies only push each other apart, so it has no block; the plan supplies one. A screener in
    # the marker's way when the run starts costs him this much more before he can follow.
    SCREEN_COST_S = 0.5

    @staticmethod
    def _hold(sim: Simulator, i: int, secs: float) -> None:
        sim.set_intent(i, "keep", None, 0.3, until=sim.t + secs, data={"point": sim.pos[i].copy()})
        sim.lock_until[i] = sim.t + secs

    def _react(self, sim: Simulator) -> None:
        if self.run_at is None or sim.t < self.run_at:
            return
        if not self.running:
            self.running = True
            sim.set_intent(self.receiver, "receive", self.delivery, 1.0, until=sim.t + 3.0)
            sim.lock_until[self.receiver] = sim.t + self.RUN_S + 0.5
            m, sc = sim.pos[self.dragged], sim.pos[self.creator]
            screened = float(np.linalg.norm(sc - m)) <= 1.5 and float((sc - m) @ (self.delivery - m)) > 0
            self.delay = self.reaction_s + (self.SCREEN_COST_S if screened else 0.0)
            self.result.signals["screened"] = 1.0 if screened else 0.0
        if not self.chasing and sim.t >= self.run_at + self.delay:
            self.chasing = True
            sim.set_intent(self.dragged, "track", None, 0.9, until=sim.t + 4.0,
                           data={"who": self.receiver, "since": sim.t, "decided": True})

    def step(self, sim: Simulator) -> bool:
        t, j = self.team, self.receiver
        elapsed = sim.t - self.t_start
        if self.mode != "without" and sim.frame % 5 == 0:
            self._screen(sim)
        self._react(sim)
        if self.pass_t is None:
            if sim.ball_state == "flight" and sim.flight_plan.get("passer") == self.passer:
                self.pass_t = sim.t
                self.pass_event = sim.flight_plan.get("event")
                self.sep_start = _separation(sim, t, j)
                flight_s = float(sim.flight_plan.get("end_time", 1.0))
                self.run_at = sim.t + max(0.0, flight_s - self.RUN_S)
                self._hold(sim, j, self.run_at - sim.t)  # not yet: he times his run
                self.timing["measure_at"] = elapsed + flight_s
            elif self.mode == "actual" and elapsed > 6.0:
                return self._end(sim, False, "the corner was never taken")
            if self.mode != "actual" and elapsed >= self.timing.get("measure_at", 3.0):
                self._measure(sim)
                return self._end(sim, True, "counterfactual measured")
            return False
        if self.mode != "actual":
            if elapsed >= self.timing.get("measure_at", 3.0):
                self._measure(sim)
                return self._end(sim, True, "counterfactual measured")
            return False
        if self.sep_end is None:
            if sim.ball_state != "flight" or sim.flight_plan.get("passer") != self.passer:
                self.sep_end = _separation(sim, t, j)
                self._measure(sim)
                self.result.outcome = "chance"
            return False
        return self._await_finish(sim, self.pass_t, j)

    def _measure(self, sim: Simulator) -> None:
        ctrl = team_control(sim, self.team, self.cells)
        values = np.array([location_value(*tx(sim, self.team, p)) for p in self.cells])
        self.result.area_m2 = float(ctrl.sum() * ZONE_STEP * ZONE_STEP)
        self.result.zone_value = float((ctrl * values).mean())
        self.result.control_gain = float(ctrl.mean()) - self.control_start
        self.result.ghost_track = [(sim.t, float(sim.pos[self.creator][0]), float(sim.pos[self.creator][1]))]

    def causal_check(self, space_created_m2: float, gap_opens_without: bool) -> tuple[bool, str]:
        return (True, "ok") if space_created_m2 >= 3.0 else (False, "the screen made too little difference")

    def verify(self, sim: Simulator) -> tuple[bool, str]:
        s = self.result.signals
        gain = (self.sep_end or 0.0) - (self.sep_start or 0.0)
        s["header_separation_gain_m"] = round(gain, 2)
        outcome = (self.pass_event or {}).get("outcome")
        if outcome != "complete":
            return False, f"the delivery didn't find him ({outcome})"
        if not s.get("screened"):
            return False, "the screen wasn't set in time"  # he got free, but not from a screen
        if gain < 2.0:
            return False, "the screen didn't free him"
        return self._check_outcome()


# ------------------------------------------------------------------------------------------------ team moments


def _match_minute(sim: Simulator) -> float:
    return (sim.period - 1) * sim.half_s / 60.0 + sim.t / 60.0


def _line_height(sim: Simulator, team: int, xy: np.ndarray) -> float:
    """Height of a team's back line in its own frame: the mean x' of its four deepest outfield players."""
    cols = [k for k in sim.team_slots[team] if sim.role[k] != "GK"]
    pts = xy[cols]
    pts = pts[~np.isnan(pts[:, 0])]
    if sim.teams[team].direction < 0:
        pts = np.column_stack([L - pts[:, 0], W - pts[:, 1]])
    return float(np.sort(pts[:, 0])[:4].mean()) if len(pts) >= 4 else float("nan")


def _possession_timeline(sim: Simulator, team: int):
    """Was `team` in possession at (period, t_ms)? From the events so far, as the observed data would say."""
    import bisect

    club = sim.teams[team].club.club_id
    times: dict[int, list[int]] = {}
    clubs: dict[int, list[str]] = {}
    for e in sim.events:
        if e["type"] in ("pass", "carry", "shot", "clearance") or (
                e["type"] in ("interception", "tackle") and e.get("outcome") == "won"):
            times.setdefault(e["period"], []).append(e["t_ms"])
            clubs.setdefault(e["period"], []).append(e["team_id"])

    def at(period: int, t_ms: int) -> bool:
        ts = times.get(period, [])
        k = bisect.bisect_right(ts, t_ms) - 1
        return k >= 0 and clubs[period][k] == club

    return at


class SpaceLost(_Finish, MomentPlan):
    """After a goal or a red card the team sits deeper for five minutes or more and concedes territory
    (PRD 12.7, Space lost). The moment belongs to the team that drops; its deepest centre-back stands for it."""

    kind = "space_lost"
    max_wait_s = 60.0
    max_run_s = 330.0
    cf_horizon_s = 60.0
    drop_m = 10.0  # soft constraint: how much deeper the block is told to sit

    def ready(self, sim: Simulator) -> bool:
        return sim.ball_state != "dead"

    def start(self, sim: Simulator) -> None:
        t = self.team
        cbs = [k for k in sim.active_of(t) if sim.role[k] == "CB"] or _outfield(sim, t)
        self.creator = min(cbs, key=lambda k: tx(sim, t, sim.pos[k])[0])
        self.passer = self.receiver = self.dragged = -1
        rec = sim.recorders.get(sim.period)
        f0 = max(sim.frame - 25 * 300, 0)
        theirs = _possession_timeline(sim, 1 - t)
        heights = ([_line_height(sim, t, rec.xy[f].astype(float)) for f in range(f0, sim.frame, 25)
                    if theirs(sim.period, f * 40)] if rec is not None and sim.recording else [])
        self.before = [h for h in heights if not np.isnan(h)]
        self.during: list[float] = []
        self.events_at = len(sim.events)
        self.tilt_before = self._tilt(sim, sim.events[max(0, self.events_at - 400): self.events_at])
        self.zone = self._own_third(sim)
        self.cells = zone_cells(self.zone)
        self.control_start = float(team_control(sim, 1 - t, self.cells).mean())
        self.result.creator = sim.pid(self.creator)
        self.result.dragged = []
        self.result.gap_zone = self.zone
        if self.mode != "without":
            sim.shape_shift[t] = -self.drop_m
            sim.shape_shift_until[t] = sim.t + self.max_run_s
            sim.log_intent(self.creator, "sit_deeper", 0.0)

    def _own_third(self, sim: Simulator) -> list[tuple[float, float]]:
        a, b = to_abs(sim, self.team, 17.0, 0.0), to_abs(sim, self.team, 45.0, W)
        return [(min(a[0], b[0]), 0.0), (max(a[0], b[0]), 0.0), (max(a[0], b[0]), W), (min(a[0], b[0]), W)]

    def _tilt(self, sim: Simulator, events: list[dict]) -> float:
        """The other team's share of touches in the final third, in points."""
        club = sim.teams[1 - self.team].club.club_id
        theirs = mine = 0
        for e in events:
            if e["type"] not in ("pass", "carry", "shot") or not e.get("start_xy"):
                continue
            x = e["start_xy"][0]
            if e["team_id"] == club:
                theirs += tx(sim, 1 - self.team, np.array(e["start_xy"]))[0] > 70
            else:
                mine += tx(sim, self.team, np.array([x, e["start_xy"][1]]))[0] > 70
        return 100.0 * theirs / max(theirs + mine, 1)

    def step(self, sim: Simulator) -> bool:
        elapsed = sim.t - self.t_start
        if sim.frame % 25 == 0 and sim.possession == 1 - self.team:
            h = _line_height(sim, self.team, sim.pos)
            if not np.isnan(h):
                self.during.append(h)
        if self.mode != "actual":
            if elapsed >= self.timing.get("measure_at", 60.0):
                self._measure(sim)
                return self._end(sim, True, "counterfactual measured")
            return False
        if elapsed >= 60.0 and "measure_at" not in self.timing:
            self.timing["measure_at"] = 60.0
            self._measure(sim)
        return False

    def release(self, sim: Simulator) -> None:
        super().release(sim)
        sim.shape_shift_until[self.team] = min(sim.shape_shift_until[self.team], sim.t)

    def _measure(self, sim: Simulator) -> None:
        ctrl = team_control(sim, 1 - self.team, self.cells)
        self.result.area_m2 = float(ctrl.sum() * ZONE_STEP * ZONE_STEP)
        self.result.zone_value = float(ctrl.mean())
        self.result.control_gain = float(ctrl.mean()) - self.control_start
        self.result.ghost_track = [(sim.t, float(sim.pos[self.creator][0]), float(sim.pos[self.creator][1]))]

    def causal_check(self, space_created_m2: float, gap_opens_without: bool) -> tuple[bool, str]:
        return (True, "ok") if space_created_m2 >= 30.0 else (False, "sitting deeper conceded too little")

    def verify(self, sim: Simulator) -> tuple[bool, str]:
        s = self.result.signals
        drop = float(np.mean(self.before) - np.mean(self.during)) if self.before and self.during else 0.0
        swing = self._tilt(sim, sim.events[self.events_at:]) - self.tilt_before
        minutes = (sim.t - self.t_start) / 60.0
        s["line_height_drop_m"] = round(drop, 1)
        s["drop_minutes"] = round(minutes, 1)
        s["field_tilt_swing_pts"] = round(swing, 1)
        if minutes < 5.0:
            return False, "the period ended before five minutes"
        if drop < 8.0:
            return False, f"the line dropped only {drop:.1f} m"
        if swing < 10.0:
            return False, f"territory barely moved ({swing:.0f} points)"
        return True, "ok"


class FatigueGap(_Finish, MomentPlan):
    """A tired full-back recovers more slowly late on, and the other team targets his flank (PRD 12.7, Fatigue
    gap). The moment belongs to the attacking team; the tired full-back is the one dragged."""

    kind = "fatigue_gap"
    max_wait_s = 600.0
    max_run_s = 330.0
    cf_horizon_s = 60.0
    tiredness = 0.8  # soft constraint: his top speed, as a share of fresh, once the gap opens

    def ready(self, sim: Simulator) -> bool:
        late = 70.0 if sim.half_s >= 40 * 60 else 0.7 * 2 * sim.half_s / 60.0
        return sim.ball_state != "dead" and _match_minute(sim) >= late

    def start(self, sim: Simulator) -> None:
        t = self.team
        fbs = [k for k in sim.active_of(1 - t) if sim.role[k] in FULL_BACK_ROLES] or _outfield(sim, 1 - t)
        d = self.slot(sim, self.spec.dragged_id, 1 - t)
        self.dragged = d if d >= 0 else min(fbs, key=lambda k: float(sim.energy[k]))
        _, dy = tx(sim, t, sim.pos[self.dragged])
        self.side = 1.0 if dy > W / 2 else -1.0  # his flank, in the attacking team's frame
        wide = [i for i in sim.active_of(t) if (tx(sim, t, sim.pos[i])[1] - W / 2) * self.side > 0 and sim.role[i] != "GK"]
        self.creator = max(wide, key=lambda i: tx(sim, t, sim.pos[i])[0]) if wide else self.dragged
        self.passer = self.receiver = -1
        self.vmax0 = float(sim.vmax[self.dragged])
        self.before_recovery = self._recovery_history(sim)
        self.during_recovery: list[float] = []
        self.open_windows: list[tuple[float, list[float]]] = []
        self.seen_events = len(sim.events)
        self.events_at = len(sim.events)
        self.share_before = self._flank_share(sim, sim.events[max(0, self.events_at - 500): self.events_at])
        centre = to_abs(sim, t, 75.0, W / 2 + self.side * 24.0)
        self.zone = rect(float(centre[0]), float(centre[1]), 15.0, 10.0)
        self.cells = zone_cells(self.zone)
        self.control_start = float(team_control(sim, t, self.cells).mean())
        self.result.creator = sim.pid(self.creator)
        self.result.dragged = [sim.pid(self.dragged)]
        self.result.gap_zone = self.zone
        if self.mode != "without":
            sim.vmax[self.dragged] = self.vmax0 * self.tiredness
            sim.flank_bias[t] = (self.side, 0.006, sim.t + self.max_run_s)
            sim.log_intent(self.creator, "target_tired_flank", 0.0)

    def _recovery_history(self, sim: Simulator) -> list[float]:
        """His speed in the 5 s after each ball his team lost, earlier in the match, from the recording."""
        rec = sim.recorders.get(sim.period)
        if rec is None or not sim.recording:
            return []
        club = sim.teams[self.team].club.club_id
        slot = self.dragged
        out = []
        for e in sim.events:
            if e["type"] in ("interception", "tackle") and e.get("outcome") == "won" and e["team_id"] == club \
                    and e["period"] == sim.period:
                f = int(e["t_ms"] / 40)
                seg = rec.xy[f: min(f + 125, sim.frame), slot].astype(float)
                if len(seg) > 10:
                    sp = np.linalg.norm(np.diff(seg, axis=0), axis=1) * 25
                    out.append(float(np.nanpercentile(sp, 90)))
        return out

    def _flank_share(self, sim: Simulator, events: list[dict]) -> float:
        """Share of the team's final-third actions that are on the target flank, in points."""
        club = sim.teams[self.team].club.club_id
        on = total = 0
        for e in events:
            if e["team_id"] != club or e["type"] not in ("pass", "carry", "shot") or not e.get("start_xy"):
                continue
            x, y = tx(sim, self.team, np.array(e["start_xy"]))
            if x > 70:
                total += 1
                on += (y - W / 2) * self.side > 8
        return 100.0 * on / max(total, 1)

    def step(self, sim: Simulator) -> bool:
        elapsed = sim.t - self.t_start
        # His speed in the 5 s after each ball his team loses, as the history was measured.
        club = sim.teams[self.team].club.club_id
        for e in sim.events[self.seen_events:]:
            if e["type"] in ("interception", "tackle") and e.get("outcome") == "won" and e["team_id"] == club:
                self.open_windows.append((sim.t + 5.0, []))
        self.seen_events = len(sim.events)
        speed = float(np.linalg.norm(sim.vel[self.dragged]))
        still_open = []
        for until, speeds in self.open_windows:
            speeds.append(speed)
            if sim.t < until:
                still_open.append((until, speeds))
            elif len(speeds) > 10:
                self.during_recovery.append(float(np.percentile(speeds, 90)))
        self.open_windows = still_open
        if self.mode != "actual":
            if elapsed >= self.timing.get("measure_at", 60.0):
                self._measure(sim)
                return self._end(sim, True, "counterfactual measured")
            return False
        if elapsed >= 60.0 and "measure_at" not in self.timing:
            self.timing["measure_at"] = 60.0
            self._measure(sim)
        return False

    def release(self, sim: Simulator) -> None:
        super().release(sim)
        if hasattr(self, "vmax0"):
            sim.vmax[self.dragged] = self.vmax0
        sim.flank_bias[self.team] = None

    def _measure(self, sim: Simulator) -> None:
        ctrl = team_control(sim, self.team, self.cells)
        self.result.area_m2 = float(ctrl.sum() * ZONE_STEP * ZONE_STEP)
        self.result.zone_value = float(ctrl.mean())
        self.result.control_gain = float(ctrl.mean()) - self.control_start
        self.result.ghost_track = [(sim.t, float(sim.pos[self.creator][0]), float(sim.pos[self.creator][1]))]

    def causal_check(self, space_created_m2: float, gap_opens_without: bool) -> tuple[bool, str]:
        return True, "ok"

    def verify(self, sim: Simulator) -> tuple[bool, str]:
        s = self.result.signals
        before = float(np.median(self.before_recovery)) if self.before_recovery else 0.0
        during = float(np.median(self.during_recovery)) if self.during_recovery else before
        drop = 100.0 * (before - during) / before if before > 0 else 0.0
        gain = self._flank_share(sim, sim.events[self.events_at:]) - self.share_before
        s["recovery_speed_drop_pct"] = round(drop, 1)
        s["flank_share_gain_pts"] = round(gain, 1)
        if drop < 15.0:
            return False, f"his recovery runs were only {drop:.0f}% slower"
        if gain < 20.0:
            return False, f"the flank's share of attacks rose only {gain:.0f} points"
        return True, "ok"


def _drift_into_space(sim: Simulator, t: int, i: int) -> None:
    """A player waiting for the ball eases away from the nearest opponent, as players make themselves available."""
    if sim.owner == i or sim.frame % 5:
        return
    opp = sim.active_of(1 - t)
    if not opp:
        return
    k = min(opp, key=lambda k: _dist(sim, k, i))
    away = sim.pos[i] - sim.pos[k]
    n = float(np.linalg.norm(away)) or 1.0
    spot = np.clip(sim.pos[i] + away / n * 2.5, [2.0, 2.0], [L - 2.0, W - 2.0])
    sim.set_intent(i, "support", spot, 0.4, until=sim.t + 0.6)
    sim.lock_until[i] = sim.t + 0.4


def _inside_rect(p: np.ndarray, zone: list[tuple[float, float]]) -> bool:
    xs = [q[0] for q in zone]
    ys = [q[1] for q in zone]
    return min(xs) <= p[0] <= max(xs) and min(ys) <= p[1] <= max(ys)


EXTRA_PLANS: dict[str, type[MomentPlan]] = {
    "switch_of_play": SwitchOfPlay,
    "press_broken": PressBroken,
    "pinning": Pinning,
    "rest_defence_exposed": RestDefenceExposed,
    "blind_side_run": BlindSideRun,
    "false_9_drop": FalseNineDrop,
    "cover_shadow": CoverShadow,
    "rotation": Rotation,
    "set_piece_screen": SetPieceScreen,
    "space_lost": SpaceLost,
    "fatigue_gap": FatigueGap,
}
PLANS.update(EXTRA_PLANS)
