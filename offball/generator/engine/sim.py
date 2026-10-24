"""The emergent engine: 22 player policies perceive, decide and move every tick; events emerge (PRD 12.4).

One `Simulator` plays one match at 25 Hz. It is seeded and deterministic: the same league, fixture and
seed produce the same match. The Match director steers it through `directives` and `plans` (soft
constraints), and `checkpoint()` / `restore()` let a directed moment be retried with new random draws, or
re-run with one decision changed to measure counterfactual credit.
"""

from __future__ import annotations

import copy
import math
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from offball.core import DT, HZ, frame_of
from offball.generator.engine import policies
from offball.generator.engine.geometry import L, W, pt_to_team
from offball.generator.engine.models import (
    BallFlight,
    PassAssessment,
    ShotContext,
    assess_cross,
    assess_pass,
    foul_prob,
    location_value,
    plan_aerial,
    plan_ground,
    plan_shot,
    pressure_on,
    tackle_win_prob,
    time_to_reach,
    xg_true,
)
from offball.generator.engine.params import EngineParams
from offball.generator.engine.tactics import compute_anchors, offside_line_team
from offball.generator.league import FORMATIONS, Club, ClubStyle, League, Player, Slot

ATTR_MAP = {
    "vmax": "top_speed", "accel": "accel", "decel": "decel", "turn": "turn_rate", "stamina": "stamina",
    "passing": "passing", "vision": "vision", "first_touch": "first_touch", "dribbling": "dribbling",
    "finishing": "finishing", "tackling": "tackling", "scanning": "scanning", "run_timing": "run_timing",
    "decoy": "decoy_tendency", "discipline": "discipline", "composure": "composure", "aerial": "aerial",
    "dspeed": "decision_speed", "work_rate": "work_rate", "handling": "handling",
}
DYNAMIC_INTENTS = frozenset({"anchor", "press", "mark", "track", "cover", "chase", "keep"})
MAX_PERIOD_S = 54 * 60


@dataclass
class TeamRT:
    club: Club
    side: int
    direction: int
    style: ClubStyle
    slots: tuple[Slot, ...]
    kit: dict
    score: int = 0
    subs: int = 0
    bench: list[Player] = field(default_factory=list)
    sub_windows: list[float] = field(default_factory=list)


class Recorder:
    """Frames for one period, one row per 25 Hz frame, with a slot -> player map for substitutions."""

    def __init__(self, max_frames: int) -> None:
        self.xy = np.full((max_frames, 22, 2), np.nan, dtype=np.float32)
        self.ori = np.full((max_frames, 22), np.nan, dtype=np.float32)
        self.ball = np.full((max_frames, 3), np.nan, dtype=np.float32)
        self.slot_player = np.full((max_frames, 22), -1, dtype=np.int16)
        self.n = 0

    def write(self, f: int, pos: np.ndarray, ori: np.ndarray, ball: np.ndarray, slot_player: np.ndarray,
              active: np.ndarray) -> None:
        self.xy[f] = pos
        self.ori[f] = ori
        self.xy[f, ~active] = np.nan
        self.ori[f, ~active] = np.nan
        self.ball[f] = ball
        sp = slot_player.copy()
        sp[~active] = -1
        self.slot_player[f] = sp
        self.n = f + 1


@dataclass
class MatchResult:
    match_id: str
    seed: int
    teams: list[TeamRT]
    players: list[Player]
    events: list[dict]
    intents: list[dict]
    probabilities: list[dict]
    recorders: dict[int, Recorder]
    period_lengths: dict[int, int]
    planted: list[dict]


class Simulator:
    def __init__(
        self,
        league: League,
        home_id: str,
        away_id: str,
        match_id: str,
        seed: int,
        kits: tuple[dict, dict] | None = None,
        half_minutes: float = 45.0,
        params: EngineParams | None = None,
    ) -> None:
        self.league = league
        self.params = params or EngineParams.load()
        self.match_id = match_id
        self.seed = seed
        self.rng = np.random.default_rng(seed)
        self.half_s = half_minutes * 60.0
        home, away = league.club(home_id), league.club(away_id)
        kits = kits or (home.kits.home, away.kits.away)
        self.teams: list[TeamRT] = []
        for side, club in enumerate((home, away)):
            style = club.style
            starters = club.starters()
            bench = [p for p in club.players if p not in starters]
            t = TeamRT(club, side, +1 if side == 0 else -1, style, FORMATIONS[style.formation], kits[side])
            t.bench = bench
            t.sub_windows = sorted(float(self.rng.uniform(lo, lo + 6)) * 60 for lo in (57, 67, 77))
            self.teams.append(t)
        self.match_players: list[Player] = list(home.players) + list(away.players)
        self.pidx = {p.player_id: k for k, p in enumerate(self.match_players)}
        self.team_slots = [list(range(0, 11)), list(range(11, 22))]
        self.player: list[Player] = [*home.starters(), *away.starters()]
        self.slot_player = np.array([self.pidx[p.player_id] for p in self.player], dtype=np.int16)
        self.team_of = np.array([0] * 11 + [1] * 11)
        self.role = [s.role for s in self.teams[0].slots] + [s.role for s in self.teams[1].slots]
        self.active = np.ones(22, dtype=bool)
        for name in ATTR_MAP:
            setattr(self, name, np.zeros(22))
        for i, p in enumerate(self.player):
            self._load_attributes(i, p)
        self.energy = np.ones(22)
        self.pos = np.zeros((22, 2))
        self.vel = np.zeros((22, 2))
        self.ori = np.zeros(22)
        self.anchor = np.zeros((22, 2))
        self.noise = np.zeros((22, 2))
        self.noise_goal = np.zeros((22, 2))
        self.target = np.zeros((22, 2))
        self.speed_frac = np.full(22, 0.5)
        self.intent: list[str] = ["anchor"] * 22
        self.intent_until = np.zeros(22)
        self.idata: list[dict] = [{} for _ in range(22)]
        self.next_decision = np.zeros(22)
        self.stun_until = np.zeros(22)
        self.lock_until = np.zeros(22)
        # Players who just knocked the ball loose can't play it again until it has left them.
        self.loose_skip: list[int] = []
        self.loose_skip_until = 0.0
        self.last_logged: list[str] = [""] * 22

        self.period = 1
        self.t = 0.0
        self.frame = 0
        self.ball_pos = np.array([L / 2, W / 2, 0.0])
        self.ball_vel = np.zeros(3)
        self.ball_state = "dead"
        self.owner = -1
        self.flight: BallFlight | None = None
        self.flight_t0 = 0.0
        self.flight_plan: dict[str, Any] = {}
        self.possession = -1
        self.possession_n = 0
        self.last_touch = -1
        self.carry_from: tuple[float, np.ndarray] | None = None
        self.transition_until = [0.0, 0.0]
        self.offside_cache = [L / 2, L / 2]
        self.pressers: list[list[int]] = [[], []]
        self.covers: list[list[int]] = [[], []]
        self.chasers: set[int] = set()
        self.restart: dict[str, Any] | None = None
        self.stoppage_s = {1: 0.0, 2: 0.0}
        self.period_over = False

        self.events: list[dict] = []
        self.intents: list[dict] = []
        self.probabilities: list[dict] = []
        self.serial = 0
        self.recorders: dict[int, Recorder] = {}
        self.period_lengths: dict[int, int] = {}

        # Steering hooks for the Match director (soft constraints).
        self.directives: dict[int, dict] = {}
        self.plans: list[Any] = []
        self.bias: dict[tuple[int, str], tuple[float, float]] = {}
        self.planted: list[dict] = []
        self.observers: list[Callable[[Simulator], None]] = []
        self.recording = True

    # ------------------------------------------------------------------------------------------ helpers

    def _load_attributes(self, i: int, p: Player) -> None:
        for name, attr in ATTR_MAP.items():
            getattr(self, name)[i] = getattr(p.attributes, attr)

    def pid(self, i: int) -> str:
        return self.player[i].player_id

    def slot_of(self, player_id: str) -> int:
        for i, p in enumerate(self.player):
            if p.player_id == player_id and self.active[i]:
                return i
        return -1

    def active_of(self, team: int) -> list[int]:
        return [i for i in self.team_slots[team] if self.active[i]]

    def keeper(self, team: int) -> int:
        for i in self.team_slots[team]:
            if self.role[i] == "GK" and self.active[i]:
                return i
        return -1

    def style_of(self, team: int) -> ClubStyle:
        return self.teams[team].style

    def attr(self, i: int, name: str) -> float:
        biased = self.bias.get((i, name))
        if biased is not None and self.t <= biased[1]:
            return biased[0]
        return float(getattr(self, name)[i])

    def marker_of(self, attacker: int) -> int:
        for j in self.team_slots[1 - self.team_of[attacker]]:
            if self.intent[j] in ("mark", "track") and self.idata[j].get("who") == attacker:
                return j
        return -1

    def team_frame(self, team: int, xy: np.ndarray) -> tuple[float, float]:
        return pt_to_team(float(xy[0]), float(xy[1]), self.teams[team].direction)

    @property
    def t_ms(self) -> int:
        return int(round(self.t * 1000))

    def set_intent(self, i: int, name: str, point: np.ndarray | None, speed: float, until: float | None = None,
                   data: dict | None = None) -> None:
        self.intent[i] = name
        self.speed_frac[i] = speed
        self.intent_until[i] = until if until is not None else self.t
        new = dict(data or {})
        if point is not None:
            new["point"] = np.asarray(point, dtype=float)
        self.idata[i] = new

    def log_intent(self, i: int, name: str, utility: float) -> None:
        if self.last_logged[i] == name:
            return
        self.last_logged[i] = name
        point = self.idata[i].get("point")
        self.intents.append(
            {
                "player_id": self.pid(i),
                "period": self.period,
                "t_ms": self.t_ms,
                "intent": name,
                "utility": round(float(utility), 5),
                "target_xy": None if point is None else [round(float(point[0]), 2), round(float(point[1]), 2)],
            }
        )

    def add_event(self, type_: str, team: int | None, i: int | None, *, start: np.ndarray | None = None,
                  end: np.ndarray | None = None, outcome: str | None = None, subtype: str | None = None,
                  t: float | None = None, **extra: Any) -> dict:
        self.serial += 1
        ev = {
            "_serial": self.serial,
            "period": self.period,
            "t_ms": int(round((t if t is not None else self.t) * 1000)),
            "team_id": None if team is None else self.teams[team].club.club_id,
            "player_id": None if i is None else self.pid(i),
            "type": type_,
            "subtype": subtype,
            "start_xy": None if start is None else [round(float(start[0]), 2), round(float(start[1]), 2)],
            "end_xy": None if end is None else [round(float(end[0]), 2), round(float(end[1]), 2)],
            "outcome": outcome,
            "possession_n": self.possession_n,
        }
        ev.update(extra)
        self.events.append(ev)
        return ev

    # ------------------------------------------------------------------------------------------ setup

    def _kickoff_positions(self, taking: int) -> None:
        for team in (0, 1):
            t = self.teams[team]
            for k, i in enumerate(self.team_slots[team]):
                slot = t.slots[k]
                if slot.role == "GK":
                    xt, yt = 4.0, W / 2
                else:
                    xt = 14.0 + slot.u * 32.0
                    yt = W / 2 + (slot.v - 0.5) * 52.0
                    xt = min(xt, L / 2 - 1.0)
                if team == taking and slot.role == "ST":
                    xt, yt = L / 2 - 0.6, W / 2 + (0.8 if slot.v >= 0.5 else -0.8)
                xy = np.array([xt, yt]) if t.direction > 0 else np.array([L - xt, W - yt])
                self.pos[i] = xy
                self.vel[i] = 0.0
                self.target[i] = xy
                self.ori[i] = 0.0 if t.direction > 0 else math.pi
        self.ball_pos[:] = (L / 2, W / 2, 0.0)
        self.anchor[:] = self.pos

    # ------------------------------------------------------------------------------------------ main loop

    def play(self) -> MatchResult:
        for period in (1, 2):
            self.start_period(period)
            while not self.period_over:
                self.step()
            self.end_period()
        return self.result()

    def start_period(self, period: int) -> None:
        self.period = period
        self.t = 0.0
        self.frame = 0
        self.period_over = False
        if period == 2:
            for t in self.teams:
                t.direction = -t.direction
        # Every timer is period-relative, so all of them restart with the clock.
        for arr in (self.intent_until, self.next_decision, self.stun_until, self.lock_until):
            arr[:] = 0.0
        self.transition_until = [0.0, 0.0]
        self.directives.clear()
        self.bias.clear()
        self.owner = -1
        self.flight = None
        self.flight_plan = {}
        self.stoppage_s[period] = float(self.rng.uniform(60, 180) if period == 1 else self.rng.uniform(150, 330))
        self.recorders[period] = Recorder(int(MAX_PERIOD_S * HZ) + 10)
        taking = 0 if period == 1 else 1
        self._kickoff_positions(taking)
        self.add_event("period_start", None, None, outcome=None)
        self.schedule_restart("kick_off", taking, np.array([L / 2, W / 2]), delay=1.0)
        self.record()

    def end_period(self) -> None:
        self._finalise_pending("incomplete")
        self.add_event("period_end", None, None)
        self.period_lengths[self.period] = self.frame + 1

    def step(self) -> None:
        self.t += DT
        self.frame += 1
        if self.frame % 5 == 0:
            for team in (0, 1):
                self.offside_cache[team] = offside_line_team(self, team)
            self._assign_roles()
        if self.frame % 2 == 0:
            raw = np.vstack([compute_anchors(self, 0), compute_anchors(self, 1)])
            # The block reacts to the ball with a short lag instead of jumping with every pass.
            self.anchor += (raw - self.anchor) * min(1.0, 2 * DT / self.params.anchor_lag)
        self._update_noise()
        for plan in list(self.plans):
            if plan.tick(self):
                self.plans.remove(plan)
        self._decisions()
        self._update_targets()
        self._move_players()
        self._update_ball()
        if self.ball_state == "owned":
            self._duels()
        if self.ball_state == "dead":
            self._run_restart()
        self._fatigue()
        self._substitutions()
        self._check_period_end()
        self.record()
        for obs in self.observers:
            obs(self)

    def record(self) -> None:
        if not self.recording:
            return
        if self.frame >= self.recorders[self.period].xy.shape[0]:
            self.period_over = True
            return
        self.recorders[self.period].write(self.frame, self.pos, self.ori, self.ball_pos, self.slot_player,
                                          self.active)

    def _check_period_end(self) -> None:
        end = self.half_s + self.stoppage_s[self.period]
        if self.t < end:
            return
        bx = self.ball_pos[0]
        calm = self.ball_state == "dead" or 30 < bx < L - 30
        if calm or self.t > end + 25:
            self.period_over = True

    # ------------------------------------------------------------------------------------------ roles

    def _assign_roles(self) -> None:
        self.pressers = [[], []]
        self.covers = [[], []]
        self.chasers = set()
        if self.ball_state == "loose" or (self.ball_state == "flight" and self.flight_plan.get("kind") == "clear"):
            b = self.ball_pos[:2]
            for team in (0, 1):
                act = [i for i in self.active_of(team) if self.role[i] != "GK"]
                act.sort(key=lambda i: float(np.linalg.norm(self.pos[i] - b)))
                self.chasers.update(act[:2])
            return
        if self.owner < 0:
            return
        att = self.team_of[self.owner]
        dfn = 1 - att
        style = self.style_of(dfn)
        bx_def = self.team_frame(dfn, self.ball_pos[:2])[0]
        press_zone = bx_def <= self.params.press_zone + 55.0 * style.press_height
        cands = [i for i in self.active_of(dfn) if self.role[i] != "GK" and self.t >= self.stun_until[i]]
        cands.sort(key=lambda i: float(np.linalg.norm(self.pos[i] - self.pos[self.owner])))
        if not cands:
            return
        nearest_d = float(np.linalg.norm(self.pos[cands[0]] - self.pos[self.owner]))
        trigger = self.params.press_trigger + 10.0 * style.press_intensity
        if bx_def < self.params.box_engage:
            # Defending our box: the two nearest step in to block and tackle, a third covers.
            self.pressers[dfn] = cands[:2]
            self.covers[dfn] = cands[2:3]
        elif press_zone and nearest_d < trigger + 6:
            n = 2 if style.press_intensity > 0.62 and nearest_d < trigger else 1
            self.pressers[dfn] = cands[:n]
            self.covers[dfn] = cands[n : n + 1]
        elif nearest_d < 7.0 or bx_def < 35:
            self.pressers[dfn] = cands[:1]

    # ------------------------------------------------------------------------------------------ decisions

    def _decisions(self) -> None:
        due = np.nonzero((self.next_decision <= self.t) & self.active)[0]
        for i in due:
            i = int(i)
            interval = (0.4 - 0.2 * self.dspeed[i]) * float(self.rng.uniform(0.9, 1.1))
            self.next_decision[i] = self.t + interval
            if self.lock_until[i] > self.t:
                continue
            self.decide(i)

    def decide(self, i: int) -> None:
        if self.ball_state == "dead":
            return  # restart positioning is managed by _run_restart
        team = self.team_of[i]
        if self.owner == i:
            if self.t < self.idata[i].get("touch_until", 0.0):
                return
            policies.on_ball(self, i)
            return
        if self.ball_state == "flight" and self.flight_plan.get("receiver") == i:
            return
        if self.t < self.stun_until[i]:
            self.set_intent(i, "anchor", None, 0.4)
            return
        if self.ball_state == "loose" or (self.ball_state == "flight" and self.flight_plan.get("kind") == "clear"):
            policies.loose_ball(self, i)
            return
        if self.possession == team:
            policies.attack_off_ball(self, i)
        elif self.possession == 1 - team:
            policies.defend(self, i)
        else:
            self.set_intent(i, "anchor", None, 0.5)

    def _pace(self, i: int, need: float, cap: float) -> float:
        """The share of top speed that covers `need` m/s, from a walk up to `cap`."""
        top = float(self.vmax[i]) * (0.8 + 0.2 * float(self.energy[i]))
        return float(np.clip(need / max(top, 1e-6), 0.07, cap))

    def _update_targets(self) -> None:
        P = self.params
        for i in range(22):
            if not self.active[i]:
                continue
            name = self.intent[i]
            data = self.idata[i]
            if name == "anchor":
                self.target[i] = self.anchor[i] + self.noise[i]
                # Close enough is in shape: walk. Further out, jog back in over a few seconds; sprint back only
                # in the transition after losing the ball, as real players do.
                gap = float(np.linalg.norm(self.target[i] - self.pos[i]))
                if gap < self.params.walk_gap:
                    self.speed_frac[i] = self._pace(i, gap / 1.2, P.pace_walk_cap)
                elif self.t < self.transition_until[self.team_of[i]] and gap > 15.0:
                    self.speed_frac[i] = self._pace(i, gap / 3.0, P.pace_transition_cap)
                else:
                    self.speed_frac[i] = self._pace(i, gap / P.pace_shape_horizon, P.pace_shape_cap)
            elif name == "press":
                if self.owner >= 0 and self.team_of[self.owner] != self.team_of[i]:
                    o = self.owner
                    to_goal = self._own_goal(self.team_of[i]) - self.pos[o]
                    n = float(np.linalg.norm(to_goal)) or 1.0
                    self.target[i] = self.pos[o] + self.vel[o] * 0.25 + to_goal / n * 0.7
                else:
                    self.target[i] = self.anchor[i]
            elif name in ("mark", "track"):
                who = data.get("who", -1)
                if who < 0 or not self.active[who]:
                    self.target[i] = self.anchor[i]
                    continue
                goal = self._own_goal(self.team_of[i])
                to_goal = goal - self.pos[who]
                n = float(np.linalg.norm(to_goal)) or 1.0
                gap = 1.8 if name == "mark" else 1.1
                ahead = 0.15 if name == "mark" else 0.45
                tgt = self.pos[who] + self.vel[who] * ahead + to_goal / n * gap
                tgt += (self.ball_pos[:2] - tgt) * 0.06
                self.target[i] = tgt
                # Keep pace with the attacker and close any gap gradually. A marker doesn't sprint to hold an
                # exact spot; a defender tracking a run does.
                err = float(np.linalg.norm(tgt - self.pos[i]))
                runner = float(np.linalg.norm(self.vel[who]))
                if name == "mark":
                    self.speed_frac[i] = self._pace(i, runner + max(0.0, err - 1.5) * P.pace_mark_gain, P.pace_mark_cap)
                else:
                    self.speed_frac[i] = self._pace(i, runner + max(0.0, err - 0.5) * 2.0, 0.97)
            elif name == "cover":
                who = data.get("who", -1)
                if who >= 0:
                    goal = self._own_goal(self.team_of[i])
                    v = goal - self.pos[who]
                    n = float(np.linalg.norm(v)) or 1.0
                    self.target[i] = self.pos[who] + v / n * 7.0
                    err = float(np.linalg.norm(self.target[i] - self.pos[i]))
                    self.speed_frac[i] = self._pace(i, float(np.linalg.norm(self.vel[who]))
                                                    + max(0.0, err - 2.0) * P.pace_mark_gain, P.pace_mark_cap)
                else:
                    self.target[i] = self.anchor[i]
            elif name == "chase":
                self.target[i] = self.ball_pos[:2] + self.ball_vel[:2] * 0.35
            elif name == "setpiece":
                # Waiting for a restart, players mill about their spot rather than stand still; the taker doesn't.
                taker = self.restart["taker"] if self.restart is not None else -1
                self.target[i] = data["point"] + (0.0 if i == taker else self.noise[i])
            elif name == "keep":
                self.target[i] = data.get("point", self.anchor[i])
            elif name == "receive":
                if data.get("follow_ball"):
                    self.target[i] = self.ball_pos[:2]
                else:
                    self.target[i] = data["point"]
                    if self.ball_state == "flight" and self.flight_plan.get("receiver") == i:
                        # Arrive with the ball, not long before it: nobody sprints to stand and wait.
                        left = max(self.flight_t0 + self.flight_plan["end_time"] - self.t, 0.25)
                        gap = float(np.linalg.norm(self.target[i] - self.pos[i]))
                        self.speed_frac[i] = self._pace(i, gap / left * 1.15 + 0.5, 1.0)
            elif "point" in data:
                self.target[i] = data["point"]
                if name == "support":
                    # Offering an angle is a jog to a spot a couple of seconds away, not a sprint.
                    gap = float(np.linalg.norm(self.target[i] - self.pos[i]))
                    self.speed_frac[i] = min(float(self.speed_frac[i]), self._pace(i, gap / 2.0, P.pace_support_cap))
                if name in ("run", "support", "carry") and self.t > self.intent_until[i] + 0.01:
                    if name == "carry" and self.owner == i:
                        self.next_decision[i] = min(self.next_decision[i], self.t)
                    self.set_intent(i, "anchor", None, 0.55)
            else:
                self.target[i] = self.anchor[i]
        # Nobody aims beyond the touchline or the goal line, so players brake before it instead of being
        # stopped dead at the edge.
        np.clip(self.target, [-1.0, -1.0], [L + 1.0, W + 1.0], out=self.target)

    def _own_goal(self, team: int) -> np.ndarray:
        return np.array([0.0 if self.teams[team].direction > 0 else L, W / 2])

    def _update_noise(self) -> None:
        # Each player drifts towards a personal offset from the anchor that changes every few seconds,
        # so shapes breathe smoothly instead of standing still or jittering.
        due = self.rng.random(22) < DT / self.params.drift_period
        if due.any():
            self.noise_goal[due] = self.rng.normal(0.0, self.params.drift_sd, (int(due.sum()), 2))
        self.noise += (self.noise_goal - self.noise) * (DT / 2.5)

    # ------------------------------------------------------------------------------------------ motion

    def _move_players(self) -> None:
        act = self.active
        to = self.target - self.pos
        dist = np.linalg.norm(to, axis=1)
        fatigue = 0.8 + 0.2 * self.energy
        top = self.vmax * fatigue
        owner_cap = np.ones(22)
        if self.owner >= 0:
            owner_cap[self.owner] = 0.85  # slower with the ball at your feet
            blocker = self._goal_side_blocker(self.owner)
            if blocker >= 0:
                owner_cap[self.owner] = 0.55  # can't run through a defender standing in the way
        # Real players seldom reach their true top speed: even an all-out run tops out a little below it.
        frac = np.minimum(self.speed_frac, self.params.pace_sprint_cap)
        desired = np.minimum(top * frac * owner_cap, np.sqrt(2 * self.decel * 0.6 * np.maximum(dist - 0.15, 0)))
        with np.errstate(invalid="ignore", divide="ignore"):
            unit = np.where(dist[:, None] > 1e-6, to / dist[:, None], 0.0)
        v_des = unit * desired[:, None]
        v_des += self._separation()
        dv = v_des - self.vel
        cur = np.linalg.norm(self.vel, axis=1)
        des = np.linalg.norm(v_des, axis=1)
        lim = np.where(des >= cur, self.accel, self.decel) * DT
        n = np.linalg.norm(dv, axis=1)
        scale = np.minimum(1.0, lim / np.maximum(n, 1e-9))
        self.vel += dv * scale[:, None]
        speed = np.linalg.norm(self.vel, axis=1)
        over = speed > top
        if over.any():
            self.vel[over] *= (top[over] / speed[over])[:, None]
        self.vel[~act] = 0.0
        self.pos += self.vel * DT
        self.pos[:, 0] = np.clip(self.pos[:, 0], -1.5, L + 1.5)
        self.pos[:, 1] = np.clip(self.pos[:, 1], -1.5, W + 1.5)
        # Body orientation: towards travel when moving, towards the ball when not, at a limited turn rate.
        moving = speed > 1.2
        to_ball = self.ball_pos[:2] - self.pos
        want = np.where(moving, np.arctan2(self.vel[:, 1], self.vel[:, 0]), np.arctan2(to_ball[:, 1], to_ball[:, 0]))
        diff = (want - self.ori + np.pi) % (2 * np.pi) - np.pi
        max_turn = np.minimum(self.turn, 14.0) * DT
        self.ori = (self.ori + np.clip(diff, -max_turn, max_turn) + np.pi) % (2 * np.pi) - np.pi

    def _separation(self) -> np.ndarray:
        act_idx = np.nonzero(self.active)[0]
        out = np.zeros((22, 2))
        p = self.pos[act_idx]
        diff = p[:, None, :] - p[None, :, :]
        d = np.linalg.norm(diff, axis=2)
        np.fill_diagonal(d, 99.0)
        same = self.team_of[act_idx][:, None] == self.team_of[act_idx][None, :]
        radius = np.where(same, 1.3, 0.85)
        close = d < radius
        if not close.any():
            return out
        push = np.where(close, (radius - d) / radius, 0.0) * 2.4
        # Bodies don't overlap: inside 0.6 m the push grows sharply.
        push += np.where(d < 0.6, (0.6 - d) / 0.6, 0.0) * 6.0
        with np.errstate(invalid="ignore", divide="ignore"):
            dirs = np.where(d[..., None] > 1e-6, diff / d[..., None], 0.0)
        out[act_idx] = (dirs * push[..., None]).sum(axis=1)
        return out

    def _fatigue(self) -> None:
        speed = np.linalg.norm(self.vel, axis=1)
        drain = np.maximum(0.0, speed - 4.0) ** 2 * self.params.fatigue_drain * (1.25 - self.stamina) * DT
        recover = np.where(speed < 2.0, 4e-5 * DT, 0.0)
        self.energy = np.clip(self.energy - drain + recover, 0.05, 1.0)
        for (i, name), (value, until) in list(self.bias.items()):
            if name == "energy" and self.t <= until:
                self.energy[i] = min(self.energy[i], value)

    # ------------------------------------------------------------------------------------------ the ball

    def give_ball(self, i: int, touch_delay: float | None = None) -> None:
        team = self.team_of[i]
        if self.possession != team:
            if self.possession >= 0:
                self.transition_until[1 - team] = self.t + 5.0
                self.transition_until[team] = self.t + 4.0
            self.possession = team
            self.possession_n += 1
        self.owner = i
        self.last_touch = i
        self.ball_state = "owned"
        self.flight = None
        self.flight_plan = {}
        self.carry_from = (self.t, self.pos[i].copy())
        delay = touch_delay if touch_delay is not None else 0.2 + 0.35 * (1 - self.first_touch[i]) + 0.1 * self.rng.random()
        self.set_intent(i, "hold", self.pos[i].copy(), 0.3, until=self.t + delay, data={"touch_until": self.t + delay})
        self.next_decision[i] = self.t + delay
        for j in range(22):
            if self.intent[j] == "receive":
                self.set_intent(j, "anchor", None, 0.5)

    def _log_carry(self, i: int) -> None:
        if self.carry_from is None:
            return
        t0, start = self.carry_from
        end = self.pos[i]
        if float(np.linalg.norm(end - start)) >= 1.5:
            self.add_event("carry", self.team_of[i], i, start=start, end=end, outcome="complete", t=t0)
        self.carry_from = None

    def assess(self, i: int, j: int, flight: BallFlight) -> PassAssessment:
        team = self.team_of[i]
        opp = self.active_of(1 - team)
        mates_pressure = pressure_on(self.pos[j], self.pos[opp])
        return assess_pass(
            flight,
            self.pos[j], self.vel[j], float(self.vmax[j] * (0.8 + 0.2 * self.energy[j])),
            self.pos[opp], self.vel[opp], self.vmax[opp] * (0.8 + 0.2 * self.energy[opp]),
            self.passing[i], self.first_touch[j],
            pressure_on(self.pos[i], self.pos[opp]), mates_pressure,
            p=self.params,
        )

    def release_pass(self, i: int, j: int, flight: BallFlight, assessment: PassAssessment | None = None,
                     subtype: str | None = None, restart: bool = False) -> None:
        team = self.team_of[i]
        a = assessment or self.assess(i, j, flight)
        p = float(a.p_success)
        cross = subtype in ("cross", "corner") or (flight.aerial and self._in_box_xy(team, flight.end))
        ca = None
        if cross:
            ca = self._assess_cross(i, j, flight)
            p = ca.p_success
            if subtype is None:
                subtype = "cross"
        if restart and subtype in ("kick_off", "goal_kick", "throw_in") and flight.distance < 30:
            p = max(p, 0.93)
        self._log_carry(i)
        start = flight.start.copy()
        tx, _ = self.team_frame(team, flight.end)
        sx, _ = self.team_frame(team, start)
        if subtype is None:
            lateral = abs(float(flight.end[1] - start[1]))
            if lateral > 30 and abs(tx - sx) < 25:
                subtype = "switch"
            elif tx > self.offside_cache[team] and self.intent[j] == "run":
                subtype = "through"
            else:
                subtype = "lofted" if flight.aerial else "ground"
        opp = self.active_of(1 - team)
        under_pressure = pressure_on(self.pos[i], self.pos[opp]) > 0.3
        offside = (not restart or subtype not in ("throw_in", "corner", "goal_kick")) and self._is_offside(j)
        ev = self.add_event(
            "pass", team, i, start=start, end=flight.end, outcome="pending", subtype=subtype,
            under_pressure=under_pressure, ball_speed_mps=round(flight.v0, 2),
            body_part="head" if self.ball_pos[2] > 1.2 else self._foot(i),
        )
        self.probabilities.append({"serial": ev["_serial"], "kind": "pass", "p_success": round(p, 4), "features": {
            "distance": round(flight.distance, 2), "aerial": flight.aerial, "p_no_intercept": round(a.p_no_intercept, 4),
            "p_reach": round(a.p_reach, 4), "p_exec": round(a.p_exec, 4), "p_control": round(a.p_control, 4)}})
        self.owner = -1
        self.last_touch = i
        self.ball_state = "flight"
        self.flight = flight
        self.flight_t0 = self.t
        plan: dict[str, Any] = {"kind": "pass", "passer": i, "event": ev, "intended": j, "offside": offside,
                                "subtype": subtype}
        u = float(self.rng.random())
        if ca is not None and u >= p:
            self._plan_cross_failure(plan, flight, ca, team)
        elif u < p:
            plan.update(outcome="complete", receiver=j, end_time=flight.duration, end_point=flight.end)
            self.set_intent(j, "receive", flight.end, 1.0, until=self.t + flight.duration + 2.0)
            self.lock_until[j] = self.t + flight.duration
        else:
            self._plan_failure(plan, flight, a, team)
        self.flight_plan = plan
        self.set_intent(i, "anchor", None, 0.55)
        self.next_decision[i] = self.t + 0.3

    def _in_box_xy(self, team: int, xy: np.ndarray) -> bool:
        xt, yt = self.team_frame(team, xy)
        return xt > L - 16.5 and abs(yt - W / 2) < 20.16

    def _assess_cross(self, i: int, j: int, flight: BallFlight):
        team = self.team_of[i]
        opp = self.active_of(1 - team)
        gk = self.keeper(1 - team)
        keeper_idx = opp.index(gk) if gk in opp else -1
        goal_x = L if self.teams[team].direction > 0 else 0.0
        return assess_cross(flight.end, float(self.aerial[j]), self.pos[opp], self.aerial[opp], keeper_idx, goal_x,
                            float(self.passing[i]), pressure_on(self.pos[i], self.pos[opp]), self.params)

    def _plan_cross_failure(self, plan: dict, flight: BallFlight, ca, team: int) -> None:
        """A failed cross: overhit, claimed by the keeper, or won in the air by a defender."""
        opp = self.active_of(1 - team)
        p_bad = 1 - ca.p_delivery
        p_claim = ca.p_delivery * ca.p_claim
        r = float(self.rng.random()) * max(1e-6, 1 - ca.p_success)
        gk = self.keeper(1 - team)
        if r < p_bad:
            # Overhit or underhit: it runs out of play or to a defender.
            end = flight.end + np.array([float(self.rng.normal(0, 7)), float(self.rng.normal(0, 7))])
            new = plan_aerial(flight.start, end)
            self.flight = new
            if not (0 <= end[0] <= L and 0 <= end[1] <= W):
                plan.update(outcome="out", receiver=-1, end_time=new.duration, end_point=end)
                return
            t_reach = time_to_reach(self.pos[opp], self.vel[opp], self.vmax[opp], end[None])[:, 0]
            d = opp[int(np.argmin(t_reach))]
            plan.update(outcome="intercepted", receiver=d, end_time=max(new.duration, float(t_reach.min())),
                        end_point=end)
            self.set_intent(d, "receive", end, 1.0, until=self.t + new.duration + 2.5)
            return
        if r < p_bad + p_claim and gk >= 0:
            plan.update(outcome="intercepted", receiver=gk, end_time=flight.duration, end_point=flight.end, claim=True)
            self.set_intent(gk, "receive", flight.end, 1.0, until=self.t + flight.duration + 2.0)
            self.lock_until[gk] = self.t + flight.duration
            return
        d = opp[ca.winner_defender] if ca.winner_defender >= 0 else min(
            opp, key=lambda k: float(np.linalg.norm(self.pos[k] - flight.end)))
        plan.update(outcome="intercepted", receiver=d, end_time=flight.duration, end_point=flight.end,
                    header_clear=True)
        self.set_intent(d, "receive", flight.end, 1.0, until=self.t + flight.duration + 2.0)
        self.lock_until[d] = self.t + flight.duration

    def _plan_failure(self, plan: dict, flight: BallFlight, a: PassAssessment, team: int) -> None:
        """A failed pass: cut out by the most likely defender, or misplaced to an opponent or out of play."""
        opp = self.active_of(1 - team)
        fail_int = 1 - a.p_no_intercept
        fail_other = max(1e-6, 1 - a.p_reach * a.p_exec * a.p_control)
        if a.interceptor >= 0 and self.rng.random() < fail_int / (fail_int + fail_other) and a.intercept_point is not None:
            d = opp[a.interceptor]
            t_end = max(float(a.intercept_time), 0.25)
            point = flight.position_at(t_end)[:2]
            if min(float(point[1]), W - float(point[1])) < 8.0 and self.rng.random() < self.params.deflect_out:
                # Got a touch to it, but only enough to turn it out of play.
                out = np.array([point[0] + float(self.rng.normal(0, 3)), -2.0 if point[1] < W / 2 else W + 2.0])
                new = plan_ground(flight.start, out, 3.0)
                self.flight = new
                plan.update(outcome="out", receiver=-1, end_time=new.duration, end_point=out, toucher=d)
                return
            plan.update(outcome="intercepted", receiver=d, end_time=t_end, end_point=point)
            self.set_intent(d, "receive", point, 1.0, until=self.t + t_end + 2.0)
            self.lock_until[d] = self.t + t_end
            return
        # Misplaced: the ball ends up somewhere the intended receiver can't get it.
        err = self.rng.normal(0, 1, 2)
        err = err / (np.linalg.norm(err) or 1.0) * float(self.rng.uniform(5, 13))
        end = flight.end + err
        edge = min(float(flight.end[1]), W - float(flight.end[1]))
        if edge < 10.0 and self.rng.random() < self.params.touch_out:
            # Overhit, or a heavy touch: near the line a loose ball usually runs out.
            end[1] = -float(self.rng.uniform(1, 4)) if flight.end[1] < W / 2 else W + float(self.rng.uniform(1, 4))
        if not (0 <= end[0] <= L and 0 <= end[1] <= W):
            new = plan_aerial(flight.start, end) if flight.aerial else plan_ground(flight.start, end, 3.0)
            self.flight = new
            plan.update(outcome="out", receiver=-1, end_time=new.duration, end_point=end)
            return
        new = plan_aerial(flight.start, end) if flight.aerial else plan_ground(flight.start, end, 3.0)
        self.flight = new
        if len(opp):
            t_reach = time_to_reach(self.pos[opp], self.vel[opp], self.vmax[opp], end[None])[:, 0]
            d = opp[int(np.argmin(t_reach))]
            plan.update(outcome="intercepted", receiver=d, end_time=max(new.duration, float(t_reach.min())),
                        end_point=end)
            self.set_intent(d, "receive", end, 1.0, until=self.t + new.duration + 2.5)
            self.lock_until[d] = self.t + new.duration * 0.5
        else:
            plan.update(outcome="out", receiver=-1, end_time=new.duration, end_point=end)

    def _foot(self, i: int) -> str:
        f = self.player[i].foot
        if f == "both":
            return "right_foot" if self.rng.random() < 0.5 else "left_foot"
        return f"{f}_foot" if self.rng.random() < 0.85 else ("left_foot" if f == "right" else "right_foot")

    def _is_offside(self, j: int) -> bool:
        team = self.team_of[j]
        xj, _ = self.team_frame(team, self.pos[j])
        bx, _ = self.team_frame(team, self.ball_pos[:2])
        line = self.offside_cache[team]
        return xj > L / 2 and xj > bx + 0.3 and xj > line + 0.3

    def shoot(self, i: int, penalty: bool = False, header: bool = False, free_kick: bool = False) -> None:
        team = self.team_of[i]
        d = self.teams[team].direction
        self._log_carry(i)
        xt, yt = self.team_frame(team, self.pos[i])
        opp = self.active_of(1 - team)
        pressure = pressure_on(self.pos[i], self.pos[opp]) if not penalty else 0.0
        cover = policies.keeper_cover(self, i) if not penalty else 1.0
        ctx = ShotContext(xt, yt, pressure, header, float(self.finishing[i]), float(self.composure[i]), cover, penalty)
        xg = xg_true(ctx, self.params)
        goal_x = L if d > 0 else 0.0
        start = self.ball_pos.copy()
        gk = self.keeper(1 - team)
        # Who might block: outfield defenders near the shot line.
        blockers = []
        if not penalty:
            for k in opp:
                if self.role[k] == "GK":
                    continue
                seg = np.array([goal_x, W / 2]) - self.pos[i]
                rel = self.pos[k] - self.pos[i]
                s = float(np.clip((rel @ seg) / max(seg @ seg, 1e-6), 0, 1))
                if 0.05 < s < 0.6 and float(np.linalg.norm(rel - s * seg)) < 1.1:
                    blockers.append(k)
        u = float(self.rng.random())
        if u < xg:
            outcome = "goal"
        elif blockers and self.rng.random() < 1 - 0.65 ** len(blockers):
            outcome = "blocked"
        else:
            on_target = 0.42 + 0.25 * self.finishing[i] - 0.15 * pressure
            outcome = "saved" if (gk >= 0 and self.rng.random() < on_target) else "off_target"
        speed = float(np.clip(self.rng.normal(24 + 6 * self.finishing[i], 3), 14, 36)) * (0.6 if header else 1.0)
        if outcome == "goal":
            gy = W / 2 + float(self.rng.choice([-1, 1])) * float(self.rng.uniform(1.2, 3.4))
            end = np.array([goal_x + (0.4 if d > 0 else -0.4), gy])
        elif outcome == "saved":
            gy = W / 2 + float(self.rng.uniform(-3.0, 3.0))
            end = np.array([goal_x - 0.6 * d, gy])
        elif outcome == "blocked":
            k = blockers[0]
            end = self.pos[k].copy()
        else:
            side = float(self.rng.choice([-1, 1]))
            end = np.array([goal_x + 1.5 * d, W / 2 + side * float(self.rng.uniform(4.0, 9.0))])
        flight = plan_shot(start[:2], end, speed)
        ev = self.add_event("shot", team, i, start=start[:2], end=end, outcome=outcome,
                            subtype="penalty" if penalty else ("header" if header else
                                                               ("free_kick" if free_kick else "open_play")),
                            body_part="head" if header else self._foot(i), ball_speed_mps=round(speed, 2),
                            under_pressure=pressure > 0.3)
        self.probabilities.append({"serial": ev["_serial"], "kind": "shot", "p_success": round(xg, 4), "features": {
            "distance": round(math.hypot(L - xt, W / 2 - yt), 2), "pressure": round(pressure, 3),
            "keeper_cover": round(cover, 3), "header": header, "penalty": penalty}})
        self.owner = -1
        self.last_touch = i
        self.ball_state = "flight"
        self.flight = flight
        self.flight_t0 = self.t
        self.flight_plan = {"kind": "shot", "shooter": i, "outcome": outcome, "end_time": flight.duration,
                            "end_point": end, "event": ev, "receiver": -1,
                            "blocker": blockers[0] if outcome == "blocked" else -1, "gk": gk}
        if outcome == "saved" and gk >= 0:
            self.set_intent(gk, "keep", end, 1.0)
            self.lock_until[gk] = self.t + flight.duration
        self.directives.pop(i, None)
        self.set_intent(i, "anchor", None, 0.5)

    def clear(self, i: int) -> None:
        team = self.team_of[i]
        self._log_carry(i)
        xt, yt = self.team_frame(team, self.pos[i])
        tx = xt + float(self.rng.uniform(28, 48))
        ty = float(np.clip(yt + self.rng.normal(0, 14), -6, W + 6))
        if min(yt, W - yt) < 24.0 and self.rng.random() < self.params.clear_to_touch:
            # From a wide area, the safe clearance is into the stand.
            tx = xt + float(self.rng.uniform(8, 30))
            ty = -4.0 if yt < W / 2 else W + 4.0
        d = self.teams[team].direction
        end = np.array([tx, ty]) if d > 0 else np.array([L - tx, W - ty])
        flight = plan_aerial(self.pos[i].copy(), end, apex=float(self.rng.uniform(8, 15)))
        self.add_event("clearance", team, i, start=self.pos[i], end=end, outcome=None, body_part=self._foot(i))
        self.owner = -1
        self.last_touch = i
        self.ball_state = "flight"
        self.flight = flight
        self.flight_t0 = self.t
        self.flight_plan = {"kind": "clear", "end_time": flight.duration, "end_point": end, "receiver": -1}
        self.set_intent(i, "anchor", None, 0.5)

    def _update_ball(self) -> None:
        if self.ball_state == "owned":
            o = self.owner
            sp = float(np.linalg.norm(self.vel[o]))
            heading = self.vel[o] / sp if sp > 0.6 else np.array([math.cos(self.ori[o]), math.sin(self.ori[o])])
            new = self.pos[o] + heading * 0.45
            self.ball_vel[:2] = (new - self.ball_pos[:2]) / DT
            self.ball_vel[2] = 0.0
            self.ball_pos[:2] = new
            self.ball_pos[2] = 0.0
        elif self.ball_state == "flight":
            tf = self.t - self.flight_t0
            plan = self.flight_plan
            if tf >= plan["end_time"]:
                self._resolve_flight()
                return
            new = self.flight.position_at(tf)
            self.ball_vel = (new - self.ball_pos) / DT
            self.ball_pos = new
            if plan.get("outcome") == "out" and not (0 <= new[0] <= L and 0 <= new[1] <= W):
                self._ball_out(plan)
        elif self.ball_state == "loose":
            self._roll_loose()
        elif self.ball_state == "seek":
            self._seek()

    def _seek(self) -> None:
        """The ball keeps rolling until the designated receiver gets to it."""
        plan = self.flight_plan
        self._roll(friction=1.7)
        r = plan["receiver"]
        if r >= 0 and float(np.linalg.norm(self.pos[r] - self.ball_pos[:2])) < 1.2:
            self._complete_reception(plan)
            return
        if self.t - plan["seek_from"] > 2.5 or not (0 <= self.ball_pos[0] <= L and 0 <= self.ball_pos[1] <= W):
            if not (0 <= self.ball_pos[0] <= L and 0 <= self.ball_pos[1] <= W):
                self._ball_out(plan)
                return
            self._finalise_pass(plan, outcome="incomplete", recipient=None)
            self.ball_state = "loose"

    def _roll(self, friction: float) -> None:
        if self.ball_pos[2] > 0.0 or self.ball_vel[2] > 0:
            self.ball_vel[2] -= 9.81 * DT
            self.ball_pos += self.ball_vel * DT
            if self.ball_pos[2] <= 0:
                self.ball_pos[2] = 0.0
                self.ball_vel[2] = -0.35 * self.ball_vel[2] if abs(self.ball_vel[2]) > 2 else 0.0
                self.ball_vel[:2] *= 0.7
        else:
            v = self.ball_vel[:2]
            sp = float(np.linalg.norm(v))
            if sp > 0:
                new_sp = max(0.0, sp - friction * DT)
                self.ball_vel[:2] = v / sp * new_sp
            self.ball_pos[:2] += self.ball_vel[:2] * DT

    def _roll_loose(self) -> None:
        self._roll(friction=2.0)
        if not (0 <= self.ball_pos[0] <= L and 0 <= self.ball_pos[1] <= W):
            self._ball_out({"kind": "loose"})
            return
        if self.ball_pos[2] > 1.7:
            return
        d = np.linalg.norm(self.pos - self.ball_pos[:2], axis=1)
        d[~self.active] = 99.0
        if self.t < self.loose_skip_until:
            d[self.loose_skip] = 99.0
        k = int(np.argmin(d))
        if d[k] < 1.0:
            # A fast ball is hard to stop: the faster it comes at a player, the likelier it runs past him.
            rel = float(np.linalg.norm(self.ball_vel[:2] - self.vel[k]))
            if rel > self.params.loose_control and self.rng.random() > (self.params.loose_control / rel) ** 2:
                return
            regained = self.possession != self.team_of[k]
            self.give_ball(k)
            if regained:
                self.add_event("interception", self.team_of[k], k, start=self.pos[k], outcome="won",
                               subtype="loose_ball")

    def _resolve_flight(self) -> None:
        plan = self.flight_plan
        kind = plan["kind"]
        if kind == "shot":
            self._resolve_shot(plan)
            return
        if kind == "clear":
            # The clearance lands and bounces on; the nearest players contest it.
            self.ball_state = "loose"
            f = self.flight
            direction = (f.end - f.start) / (f.distance or 1.0)
            self.ball_vel = np.array([direction[0] * 6.0, direction[1] * 6.0, 2.0])
            self.ball_pos = np.array([f.end[0], f.end[1], 0.01])
            self._assign_roles()
            if not (0 <= self.ball_pos[0] <= L and 0 <= self.ball_pos[1] <= W):
                self._ball_out({"kind": "clear"})
            return
        outcome = plan["outcome"]
        if outcome == "out":
            self._ball_out(plan)
            return
        r = plan["receiver"]
        if r >= 0 and float(np.linalg.norm(self.pos[r] - self.ball_pos[:2])) <= 1.5:
            self._complete_reception(plan)
            return
        # Not there yet: the ball rolls on and the receiver chases it.
        self.ball_state = "seek"
        plan["seek_from"] = self.t
        f = self.flight
        speed = max(f.speed_at(f.duration), 2.0)
        direction = (f.end - f.start) / (f.distance or 1.0)
        self.ball_vel = np.array([direction[0] * speed, direction[1] * speed, 0.0])
        self.ball_pos[2] = 0.0
        if r >= 0:
            self.set_intent(r, "receive", None, 1.0, until=self.t + 3.0, data={"follow_ball": True})

    def _complete_reception(self, plan: dict) -> None:
        r = plan["receiver"]
        passer = plan["passer"]
        if plan["outcome"] == "complete" and plan.get("offside") and r == plan.get("intended"):
            self._finalise_pass(plan, outcome="offside", recipient=r)
            team = self.team_of[r]
            self.add_event("offside", team, r, start=self.pos[r])
            self.schedule_restart("free_kick", 1 - team, self.pos[r].copy(), delay=float(self.rng.uniform(14, 26)))
            return
        if self.team_of[r] == self.team_of[passer]:
            self._finalise_pass(plan, outcome="complete", recipient=r)
            # A won header in the box is mostly a shot, sometimes a knock-down.
            header_finish = (plan.get("subtype") in ("cross", "corner") and self._in_box(r)
                             and self.rng.random() < self.params.header_shot)
            self.give_ball(r, touch_delay=0.05 if header_finish else None)
            if header_finish:
                self.ball_pos[2] = 1.6
                self.shoot(r, header=True)
            elif r in self.directives and self.directives[r].get("action") == "shoot_on_receive":
                self.directives[r] = {"action": "shoot"}
        else:
            self._finalise_pass(plan, outcome="incomplete", recipient=None)
            # Defenders who cut out a cross in their own box often head it behind.
            behind = self.rng.random() < self.params.header_behind
            if plan.get("header_clear") and not behind:
                # Won in the air and cleared upfield.
                self.give_ball(r, touch_delay=0.0)
                self.clear(r)
                return
            if behind and (plan.get("header_clear") or (self._in_own_box(r)
                                                        and plan.get("subtype") in ("cross", "corner", "lofted"))):
                self.last_touch = r
                self.add_event("clearance", self.team_of[r], r, start=self.pos[r], subtype="header",
                               body_part="head")
                self.ball_pos[0] = -0.5 if self.ball_pos[0] < L / 2 else L + 0.5
                self._ball_out({"kind": "clear"})
                return
            self.give_ball(r)
            self.add_event("interception", self.team_of[r], r, start=self.pos[r], outcome="won",
                           related_serial=plan["event"]["_serial"])

    def _in_own_box(self, i: int) -> bool:
        xt, yt = self.team_frame(self.team_of[i], self.pos[i])
        return xt < 16.5 and abs(yt - W / 2) < 20.16

    def _finalise_pending(self, outcome: str) -> None:
        plan = self.flight_plan
        ev = plan.get("event") if plan else None
        if ev is not None and ev.get("type") == "pass" and ev.get("outcome") == "pending":
            self._finalise_pass(plan, outcome=outcome, recipient=None)

    def _in_box(self, i: int) -> bool:
        xt, yt = self.team_frame(self.team_of[i], self.pos[i])
        return xt > L - 16.5 and abs(yt - W / 2) < 20.16

    def _finalise_pass(self, plan: dict, outcome: str, recipient: int | None) -> None:
        ev = plan["event"]
        ev["outcome"] = outcome
        ev["end_xy"] = [round(float(self.ball_pos[0]), 2), round(float(self.ball_pos[1]), 2)]
        ev["recipient_id"] = None if recipient is None else self.pid(recipient)

    def _resolve_shot(self, plan: dict) -> None:
        shooter = plan["shooter"]
        team = self.team_of[shooter]
        outcome = plan["outcome"]
        if outcome == "goal":
            self.teams[team].score += 1
            self.ball_vel[:] = 0.0
            self.owner = -1
            self.ball_state = "dead"
            self.restart = None
            self.schedule_restart("kick_off", 1 - team, np.array([L / 2, W / 2]), delay=float(self.rng.uniform(55, 85)))
            # Celebrate near the scorer before walking back.
            for k in self.active_of(team):
                self.set_intent(k, "setpiece", self.pos[shooter] + self.rng.normal(0, 3, 2), 0.6)
            self.restart["celebrate_until"] = self.t + 18.0
            self.restart["placed"] = False
            return
        if outcome == "saved":
            gk = plan["gk"]
            self.add_event("save", 1 - team, gk, start=self.ball_pos[:2], outcome="saved",
                           related_serial=plan["event"]["_serial"])
            r = self.rng.random()
            if r < 0.4:
                self.give_ball(gk, touch_delay=float(self.rng.uniform(4.0, 9.0)))
            elif r < 0.75:
                # Tipped behind for a corner.
                self.last_touch = gk
                self.ball_pos[0] = -0.5 if self.ball_pos[0] < L / 2 else L + 0.5
                self._ball_out({"kind": "shot"})
            else:
                # Parried: the ball spills away from goal.
                self.ball_state = "loose"
                out_x = 1.0 if self.teams[1 - team].direction > 0 else -1.0
                self.ball_vel = np.array([out_x * float(self.rng.uniform(4, 8)), float(self.rng.normal(0, 4)), 1.5])
                self.ball_pos[2] = 0.3
                self.last_touch = gk
                self._assign_roles()
            return
        if outcome == "blocked":
            k = plan["blocker"]
            if self.rng.random() < 0.4:
                self.last_touch = k
                self.ball_pos[0] = -0.5 if self.ball_pos[0] < L / 2 else L + 0.5
                self._ball_out({"kind": "shot"})
                return
            self.ball_state = "loose"
            self.last_touch = k
            v = self.rng.normal(0, 1, 2)
            self.ball_vel = np.array([v[0] * 5.0, v[1] * 5.0, 0.8])
            self._assign_roles()
            return
        self._ball_out({"kind": "shot", "shooter": shooter})

    def _ball_out(self, plan: dict) -> None:
        if plan.get("toucher", -1) >= 0:
            self.last_touch = plan["toucher"]
        bx, by = float(self.ball_pos[0]), float(self.ball_pos[1])
        last = self.last_touch if self.last_touch >= 0 else 0
        last_team = self.team_of[last]
        self._finalise_pending("out")
        self.owner = -1
        spot = np.array([min(max(bx, 0.0), L), min(max(by, 0.0), W)])
        if 0 <= by <= W and (bx < 0 or bx > L):
            # Over a goal line: corner or goal kick.
            defending = 0 if (bx < 0) == (self.teams[0].direction > 0) else 1
            self.add_event("ball_out", last_team, last, start=spot, subtype="goal_line")
            if last_team == defending:
                corner = np.array([0.0 if bx < 0 else L, 0.0 if by < W / 2 else W])
                self.schedule_restart("corner", 1 - defending, corner, delay=float(self.rng.uniform(24, 42)))
            else:
                gx = 5.5 if bx < 0 else L - 5.5
                self.schedule_restart("goal_kick", defending, np.array([gx, W / 2 + float(self.rng.uniform(-8, 8))]),
                                      delay=float(self.rng.uniform(16, 30)))
        else:
            self.add_event("ball_out", last_team, last, start=spot, subtype="touchline")
            spot[1] = 0.0 if by < W / 2 else W
            spot[0] = min(max(spot[0], 1.0), L - 1.0)
            self.schedule_restart("throw_in", 1 - last_team, spot, delay=float(self.rng.uniform(9, 19)))

    # ------------------------------------------------------------------------------------------ duels

    def _duels(self) -> None:
        o = self.owner
        team = self.team_of[o]
        for k in self.active_of(1 - team):
            if self.t < self.stun_until[k] or self.role[k] == "GK":
                continue
            d = float(np.linalg.norm(self.pos[k] - self.pos[o]))
            engaged = self.intent[k] == "press"
            if d > (1.6 if engaged else 0.9):
                continue
            heading = self.vel[o] / (np.linalg.norm(self.vel[o]) or 1.0)
            from_behind = float((self.pos[k] - self.pos[o]) @ heading) < -0.4
            hazard = self.params.tackle_hazard * (0.5 + self.tackling[k]) * (1.0 if engaged else 0.4)
            if not from_behind and self._is_goal_side(k, o):
                hazard *= self.params.goal_side_boost  # a defender standing in the way gets a proper go at the ball
            if self.rng.random() > hazard:
                continue
            in_box = self._in_box(o)
            if self.rng.random() < foul_prob(self.tackling[k], from_behind, in_box, self.params):
                self._foul(k, o, in_box)
                return
            won = self.rng.random() < tackle_win_prob(self.tackling[k], self.dribbling[o], from_behind)
            self._log_carry(o)
            self.add_event("tackle", 1 - team, k, start=self.pos[k], outcome="won" if won else "lost",
                           related_player_id=self.pid(o))
            if won:
                edge = min(float(self.pos[o][1]), W - float(self.pos[o][1]))
                if edge < 10.0 and self.rng.random() < self.params.wide_tackle_out * (1.2 - edge / 10.0):
                    # Near the touchline the ball usually goes out: knocked off the attacker, or put out for safety.
                    out = -1.0 if self.pos[o][1] < W / 2 else 1.0
                    self.owner = -1
                    self.ball_state = "loose"
                    self.ball_vel = np.array([float(self.rng.normal(0, 2.0)), out * float(self.rng.uniform(5, 8)), 0.0])
                    self.last_touch = k
                    self.loose_skip, self.loose_skip_until = [k, o], self.t + 0.6
                    self._assign_roles()
                elif self.rng.random() < 0.65:
                    self.give_ball(k)
                else:
                    self.owner = -1
                    self.ball_state = "loose"
                    v = self.rng.normal(0, 1, 2)
                    self.ball_vel = np.array([v[0] * 4.0, v[1] * 4.0, 0.0])
                    self.last_touch = k
                    self.loose_skip, self.loose_skip_until = [k, o], self.t + 0.25
                    self._assign_roles()
            else:
                self.stun_until[k] = self.t + 0.9
                self.set_intent(k, "anchor", None, 0.4)
            return

    def _is_goal_side(self, k: int, o: int) -> bool:
        """Is defender k between attacker o and the goal o attacks?"""
        goal = self._own_goal(self.team_of[k])
        to_goal = goal - self.pos[o]
        return float((self.pos[k] - self.pos[o]) @ to_goal) > 0.0

    def _goal_side_blocker(self, o: int) -> int:
        for k in self.active_of(1 - self.team_of[o]):
            if self.role[k] == "GK" or self.t < self.stun_until[k]:
                continue
            if float(np.linalg.norm(self.pos[k] - self.pos[o])) < 1.6 and self._is_goal_side(k, o):
                return k
        return -1

    def _foul(self, k: int, o: int, in_box: bool) -> None:
        team = self.team_of[o]
        self.add_event("foul", 1 - team, k, start=self.pos[o], related_player_id=self.pid(o))
        r = self.rng.random()
        if r < 0.006:
            self.add_event("card", 1 - team, k, subtype="red")
            self._send_off(k)
        elif r < 0.13:
            self.add_event("card", 1 - team, k, subtype="yellow")
        self._log_carry(o)
        if in_box:
            d = self.teams[team].direction
            spot = np.array([L - 11.0 if d > 0 else 11.0, W / 2])
            self.schedule_restart("penalty", team, spot, delay=float(self.rng.uniform(70, 110)))
        else:
            self.schedule_restart("free_kick", team, self.pos[o].copy(), delay=float(self.rng.uniform(18, 40)))

    def _send_off(self, k: int) -> None:
        self.active[k] = False
        self.pos[k] = (L / 2, -1.0)
        self.vel[k] = 0.0

    # ------------------------------------------------------------------------------------------ restarts

    def schedule_restart(self, kind: str, team: int, spot: np.ndarray, delay: float) -> None:
        self._finalise_pending("incomplete")
        self.ball_state = "dead"
        self.owner = -1
        self.flight = None
        self.flight_plan = {}
        self.ball_vel[:] = 0.0
        if self.possession != team:
            self.possession = team
            self.possession_n += 1
        delay *= self.params.restart_delay_scale
        self.restart = {"kind": kind, "team": team, "spot": np.asarray(spot, dtype=float), "ready": self.t + delay,
                        "taker": -1, "placed": True}
        self._restart_positions()

    def _restart_positions(self) -> None:
        r = self.restart
        assert r is not None
        team, kind, spot = r["team"], r["kind"], r["spot"]
        cands = [i for i in self.active_of(team) if self.role[i] != "GK" or kind == "goal_kick"]
        if kind == "goal_kick":
            taker = self.keeper(team)
        elif kind == "penalty":
            taker = max(cands, key=lambda i: self.finishing[i])
        elif kind == "corner":
            pref = [i for i in cands if self.role[i] in ("RW", "LW", "AM", "CM", "RM", "LM")]
            taker = min(pref or cands, key=lambda i: float(np.linalg.norm(self.pos[i] - spot)))
        elif kind == "kick_off":
            st = [i for i in cands if self.role[i] == "ST"] or cands
            taker = st[0]
        else:
            taker = min(cands, key=lambda i: float(np.linalg.norm(self.pos[i] - spot)))
        r["taker"] = taker
        for i in range(22):
            if not self.active[i]:
                continue
            # Players walk or jog into position for a restart; only the taker and anyone far away hurry.
            if i == taker:
                self.set_intent(i, "setpiece", spot, 0.45)
                continue
            target = self._setpiece_spot(i, kind, team, spot)
            far = float(np.linalg.norm(target - self.pos[i])) > 25.0
            pace = self.params.setpiece_pace
            self.set_intent(i, "setpiece", target, pace * 1.8 if far else pace)

    def _setpiece_spot(self, i: int, kind: str, team: int, spot: np.ndarray) -> np.ndarray:
        my = self.team_of[i]
        k = self.team_slots[my].index(i)
        slot = self.teams[my].slots[k]
        if kind == "kick_off":
            d = self.teams[my].direction
            if slot.role == "GK":
                xt, yt = 4.0, W / 2
            else:
                xt = min(14.0 + slot.u * 32.0, L / 2 - 1.5)
                yt = W / 2 + (slot.v - 0.5) * 50.0
                if my != team and math.hypot(xt - L / 2, yt - W / 2) < 9.5:
                    xt = L / 2 - 10.0
            return np.array([xt, yt]) if d > 0 else np.array([L - xt, W - yt])

        att = self.teams[team].direction

        def a(xt: float, yt: float) -> np.ndarray:  # attacking team's frame -> absolute
            return np.array([xt, yt]) if att > 0 else np.array([L - xt, W - yt])

        rng = self.rng
        if kind == "penalty":
            if slot.role == "GK":
                return a(L - 0.3, W / 2) if my != team else a(L / 2 - 10.0, W / 2)
            return a(L - 19.0 - float(rng.uniform(0, 6)), W / 2 + (slot.v - 0.5) * 34.0)
        if kind == "corner" or (kind == "free_kick" and self._dangerous_fk(team, spot)):
            if slot.role == "GK":
                return a(L - 0.6, W / 2) if my != team else a(L / 2 - 8.0, W / 2)
            if my == team:
                if slot.role in ("RB", "LB", "RWB", "LWB", "DM"):
                    return a(L / 2 + 10.0, W / 2 + (slot.v - 0.5) * 30.0)
                return a(L - float(rng.uniform(5, 13)), W / 2 + float(rng.uniform(-9, 9)))
            if slot.role == "ST":
                return a(L / 2 + 6.0, W / 2 + (slot.v - 0.5) * 10.0)
            return a(L - float(rng.uniform(3, 12)), W / 2 + float(rng.uniform(-10, 10)))
        # Throw-ins, goal kicks and ordinary free kicks: shape up around the ball.
        return compute_anchors(self, my)[k]

    def _dangerous_fk(self, team: int, spot: np.ndarray) -> bool:
        xt, yt = self.team_frame(team, spot)
        return xt > L - 32 and abs(yt - W / 2) < 22

    def _run_restart(self) -> None:
        r = self.restart
        if r is None:
            return
        if r.get("celebrate_until", 0) > self.t:
            return
        if not r["placed"]:
            r["placed"] = True
            self._restart_positions()
        taker = r["taker"]
        if taker < 0 or not self.active[taker]:
            self._restart_positions()
            return
        spot = r["spot"]
        self.ball_pos[:2] = spot
        self.ball_pos[2] = 0.0
        if float(np.linalg.norm(self.pos[taker] - spot)) > 1.0 or self.t < r["ready"]:
            return
        kind, team = r["kind"], r["team"]
        self.restart = None
        self.give_ball(taker, touch_delay=0.0)
        if kind == "penalty":
            self.shoot(taker, penalty=True)
            return
        if kind == "free_kick" and self._dangerous_fk(team, spot):
            xt, yt = self.team_frame(team, spot)
            if math.hypot(L - xt, W / 2 - yt) < 28 and self.rng.random() < 0.45:
                self.shoot(taker, free_kick=True)
                return
        self._restart_pass(taker, kind, team)

    def _restart_pass(self, taker: int, kind: str, team: int) -> None:
        mates = [j for j in self.active_of(team) if j != taker]
        p = self.pos[taker].copy()
        best, best_u, best_flight = -1, -1e9, None
        for j in mates:
            dist = float(np.linalg.norm(self.pos[j] - p))
            if dist < 3:
                continue
            target = self.pos[j].copy()
            if kind == "throw_in":
                if dist > 24:
                    continue
                flight = plan_aerial(p, target, apex=2.2)
            elif kind == "corner":
                if not self._in_box(j):
                    continue
                flight = plan_aerial(p, target, apex=float(self.rng.uniform(6, 9)))
            elif kind == "kick_off":
                xt, _ = self.team_frame(team, target)
                if xt > L / 2 - 2 or dist > 25:
                    continue
                flight = plan_ground(p, target, 5.0)
            elif kind == "goal_kick":
                long = self.style_of(team).build_up == "keeper_long" or self.rng.random() < 0.35
                if long and dist < 35:
                    continue
                if not long and dist > 30:
                    continue
                flight = plan_aerial(p, target) if long else plan_ground(p, target, 5.0)
            else:
                flight = plan_aerial(p, target) if dist > 30 else plan_ground(p, target, self.params.pass_arrival)
            a = self.assess(taker, j, flight)
            tx, ty = self.team_frame(team, target)
            u = a.p_success * location_value(tx, ty, self.params) + float(self.rng.gumbel(0, 0.004))
            if kind == "corner":
                u = self.aerial[j] + float(self.rng.normal(0, 0.15))
            if u > best_u:
                best, best_u, best_flight = j, u, flight
        if best < 0 or best_flight is None:
            # Nobody suitable: play it to the nearest teammate.
            best = min(mates, key=lambda j: float(np.linalg.norm(self.pos[j] - p)))
            best_flight = plan_ground(p, self.pos[best].copy(), 5.0)
        sub = {"throw_in": "throw_in", "corner": "corner", "kick_off": "kick_off", "goal_kick": "goal_kick",
               "free_kick": "free_kick"}[kind]
        self.release_pass(taker, best, best_flight, subtype=sub, restart=True)

    # ------------------------------------------------------------------------------------------ substitutions

    def _substitutions(self) -> None:
        if self.period != 2 or self.ball_state != "dead" or self.frame % 25:
            return
        for team in (0, 1):
            t = self.teams[team]
            if t.subs >= 3 or not t.sub_windows:
                continue
            if (self.t + self.half_s) < t.sub_windows[0]:
                continue
            t.sub_windows.pop(0)
            outfield = [i for i in self.active_of(team) if self.role[i] != "GK"]
            locked = set(self.directives) | {i for i in range(22) if self.lock_until[i] > self.t}
            locked |= {i for (i, _name) in self.bias}
            outfield = [i for i in outfield if i not in locked]
            if not outfield:
                continue
            off = min(outfield, key=lambda i: self.energy[i])
            group = _group(self.role[off])
            options = [p for p in t.bench if _group(p.role) == group] or [p for p in t.bench if p.role != "GK"]
            if not options:
                continue
            on = options[0]
            t.bench.remove(on)
            t.subs += 1
            self.add_event("substitution", team, off, related_player_id=on.player_id, subtype="tactical")
            self.player[off] = on
            self.slot_player[off] = self.pidx[on.player_id]
            self._load_attributes(off, on)
            self.energy[off] = 1.0
            self.pos[off] = (L / 2 + float(self.rng.uniform(-3, 3)), 0.0 if self.pos[off][1] < W / 2 else W)
            self.vel[off] = 0.0
            self.last_logged[off] = ""

    # ------------------------------------------------------------------------------------------ checkpoints

    def checkpoint(self) -> dict:
        state = {k: v for k, v in self.__dict__.items()
                 if k not in ("league", "events", "intents", "probabilities", "recorders", "plans", "observers",
                              "match_players", "pidx", "planted")}
        snap = copy.deepcopy(state)
        snap["_events"] = copy.deepcopy(self.events[-60:])
        snap["_n_events"] = len(self.events)
        snap["_n_intents"] = len(self.intents)
        snap["_n_probs"] = len(self.probabilities)
        return snap

    def restore(self, snap: dict) -> None:
        snap = copy.deepcopy(snap)
        n_events = snap.pop("_n_events")
        tail = snap.pop("_events")
        n_intents = snap.pop("_n_intents")
        n_probs = snap.pop("_n_probs")
        self.__dict__.update(snap)
        del self.events[n_events:]
        # Pending events (passes in flight) may have been finalised since: restore their saved copies.
        k = len(tail)
        self.events[n_events - k : n_events] = tail
        if self.flight_plan.get("event") is not None:
            serial = self.flight_plan["event"]["_serial"]
            for ev in self.events:
                if ev["_serial"] == serial:
                    self.flight_plan["event"] = ev
                    break
        del self.intents[n_intents:]
        del self.probabilities[n_probs:]

    def reseed(self, seed: int) -> None:
        self.rng = np.random.default_rng(seed)

    def fork(self, snap: dict) -> Simulator:
        """A non-recording copy of the match at a checkpoint, for counterfactual re-runs.

        The fork has its own logs and no recorder, so nothing it plays can leak into the real match.
        """
        clone = Simulator.__new__(Simulator)
        clone.league = self.league
        clone.match_players = self.match_players
        clone.pidx = self.pidx
        clone.events, clone.intents, clone.probabilities = [], [], []
        clone.recorders, clone.plans, clone.observers, clone.planted = {}, [], [], []
        state = copy.deepcopy({k: v for k, v in snap.items() if not k.startswith("_")})
        clone.__dict__.update(state)
        clone.events = list(copy.deepcopy(snap.get("_events", [])))
        if clone.flight_plan.get("event") is not None:
            serial = clone.flight_plan["event"]["_serial"]
            match = [e for e in clone.events if e["_serial"] == serial]
            clone.flight_plan["event"] = match[0] if match else dict(clone.flight_plan["event"])
        clone.recording = False
        return clone

    # ------------------------------------------------------------------------------------------ result

    def result(self) -> MatchResult:
        return MatchResult(
            match_id=self.match_id,
            seed=self.seed,
            teams=self.teams,
            players=self.match_players,
            events=self.events,
            intents=self.intents,
            probabilities=self.probabilities,
            recorders=self.recorders,
            period_lengths=self.period_lengths,
            planted=self.planted,
        )


def _group(role: str) -> str:
    return {"GK": "GK", "CB": "D", "RB": "D", "LB": "D", "RWB": "D", "LWB": "D", "DM": "M", "CM": "M",
            "AM": "M", "RM": "M", "LM": "M", "RW": "F", "LW": "F", "ST": "F"}[role]


def frame_now(sim: Simulator) -> int:
    return frame_of(sim.t_ms)
