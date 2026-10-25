"""The fast engine (PRD 12.4): events first, no tracking, a whole season in minutes.

It samples what the ball does from a ball-flow model fitted to real matches (`calibration/fast_engine.json`,
written by `offball fit`): in each of 24 zones of the pitch, how often the team on the ball passes or shoots, how
often a pass is completed, where completed passes go, and how often a shot scores. Club quality and players'
passing and finishing nudge those rates; roles decide who is on the ball where. The output is a match file and an
event stream in the same contracts as the emergent engine, without tracking. It backs the season: leaderboards,
season context and the Fabric dashboards (PRD 12.11, Season backdrop).
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from offball.contracts import Event, Kit, LineupEntry, MatchInfo, PeriodInfo, TeamSheet
from offball.core import event_id, possession_id
from offball.generator.league import Club, League, Player, kit_for_fixture

MODEL_PATH = Path(__file__).resolve().parents[2] / "calibration" / "fast_engine.json"
L, W = 105.0, 68.0
GENERATOR_VERSION = "fast-1"
GROUP = {"GK": "GK", "CB": "D", "RB": "D", "LB": "D", "RWB": "D", "LWB": "D", "DM": "M", "CM": "M", "RM": "M",
         "LM": "M", "AM": "A", "RW": "A", "LW": "A", "ST": "F"}
# How likely each role group is to be on the ball in each of the six bands of the pitch, from own goal to theirs.
ON_BALL_BY_BAND = {
    "GK": [3.0, 0.05, 0.0, 0.0, 0.0, 0.0],
    "D": [5.0, 4.0, 2.0, 1.0, 0.4, 0.2],
    "M": [1.5, 3.0, 4.0, 3.0, 1.5, 0.8],
    "A": [0.3, 1.0, 2.0, 3.5, 4.0, 3.0],
    "F": [0.1, 0.4, 1.0, 2.0, 4.0, 6.0],
}
FOULS_PER_ACTION = 21.1 / 983.0  # real rates per on-ball action (Wyscout means)
OFFSIDES_PER_FORWARD_PASS = 0.012
OUT_OF_PLAY_SHARE = 0.25  # share of failed passes that go out for a throw-in
RESTART_S, RESTARTS_PER_MATCH = 12.0, 140  # time a restart takes, and roughly how many a match has
SHOT_SCALE, GOAL_SCALE = 0.72, 0.78  # calibrated so the season's shots and goals match the fitted targets
CLEARANCE_RATE, CLEARANCE_KEPT = 0.16, 0.4  # clearances per action in our own two bands; share we win back
CORNER_FROM_SHOT, CORNER_FROM_CROSS = 0.6, 0.15
TACKLES_PER_ACTION = 0.08  # duels that win the ball (real matches have about 35 tackles and many loose-ball duels)


@dataclass
class _State:
    period: int = 1
    t: float = 0.0
    team: int = 0
    zone: int = 9
    serial: int = 0
    possession_n: int = 0
    events: list[dict] = field(default_factory=list)
    score: list[int] = field(default_factory=lambda: [0, 0])


class FastEngine:
    def __init__(self, league: League, model_path: Path = MODEL_PATH) -> None:
        self.league = league
        m = json.loads(model_path.read_text(encoding="utf-8"))
        self.zx, self.zy = m["zones"]
        self.shot_share = np.array(m["shot_share"])
        self.completion = np.array(m["pass_completion"])
        moves = np.array(m["pass_to"])
        self.pass_to = moves / np.maximum(moves.sum(axis=1, keepdims=True), 1e-12)  # stored rounded
        self.goal_rate = np.array(m["goal_rate"])
        # The clock: real matches fit about this many on-ball actions into 95 minutes, restarts included.
        self.gap_s = (95 * 60 - RESTART_S * RESTARTS_PER_MATCH) / float(m["actions_per_match"])

    # ------------------------------------------------------------------ helpers
    def _band(self, zone: int) -> int:
        return zone // self.zy

    def _mirror(self, zone: int) -> int:
        """The same spot from the other team's point of view."""
        return (self.zx - 1 - zone // self.zy) * self.zy + (self.zy - 1 - zone % self.zy)

    def _point(self, rng: np.random.Generator, zone: int, team: int, period: int) -> list[float]:
        """A random point in a zone (team frame) as absolute pitch coordinates for that period."""
        bx, by = zone // self.zy, zone % self.zy
        x = (bx + rng.random()) * L / self.zx
        y = (by + rng.random()) * W / self.zy
        attacks_right = (team == 0) == (period == 1)
        return [round(x if attacks_right else L - x, 2), round(y if attacks_right else W - y, 2)]

    def _actor(self, rng: np.random.Generator, squad: list[Player], zone: int, exclude: str | None = None) -> Player:
        band = self._band(zone)
        cands = [p for p in squad if p.player_id != exclude]
        w = np.array([ON_BALL_BY_BAND[GROUP[p.role]][band] + 1e-3 for p in cands])
        return cands[int(rng.choice(len(cands), p=w / w.sum()))]

    def _event(self, s: _State, type_: str, team_id: str | None, player: Player | None, **fields) -> dict:
        s.serial += 1
        ev = {"serial": s.serial, "period": s.period, "t_ms": int(round(s.t * 1000)), "team_id": team_id,
              "player_id": player.player_id if player else None, "type": type_,
              "possession_n": s.possession_n, **fields}
        s.events.append(ev)
        return ev

    # ------------------------------------------------------------------ the match
    def play(self, home_id: str, away_id: str, match_id: str, seed: int, half_minutes: float = 45.0,
             round_: int | None = None) -> tuple[MatchInfo, list[Event]]:
        rng = np.random.default_rng(seed)
        clubs: list[Club] = [self.league.club(home_id), self.league.club(away_id)]
        squads = [c.starters() for c in clubs]
        strength = [0.5 + c.quality for c in clubs]
        s = _State()
        durations = []
        for period in (1, 2):
            s.period, s.t = period, 0.0
            s.team = 0 if period == 1 else 1
            s.zone = (self.zx // 2 - 1) * self.zy + self.zy // 2
            s.possession_n += 1
            self._event(s, "period_start", None, None)
            end = half_minutes * 60 + float(rng.uniform(60, 240))
            restart = "kick_off"
            while s.t < end:
                restart = self._action(rng, s, clubs, squads, strength, restart)
                s.t += float(np.clip(rng.exponential(self.gap_s), 0.6, 30.0)) + (RESTART_S if restart else 0.0)
            durations.append(int(s.t * 1000))
            self._event(s, "period_end", None, None)
        return self._finish(match_id, seed, round_, clubs, durations, s)

    def _action(self, rng, s: _State, clubs, squads, strength, restart: str | None) -> str | None:
        t, z = s.team, s.zone
        club, squad = clubs[t].club_id, squads[t]
        other = 1 - t
        actor = self._actor(rng, squad, z)
        start = self._point(rng, z, t, s.period)
        if restart is None and rng.random() < FOULS_PER_ACTION:
            fouler = self._actor(rng, squads[other], self._mirror(z))
            self._event(s, "foul", clubs[other].club_id, fouler, start_xy=start, opponent_id=actor.player_id)
            return "free_kick"
        if restart is None and rng.random() < TACKLES_PER_ACTION:
            tackler = self._actor(rng, squads[other], self._mirror(z))
            self._event(s, "tackle", clubs[other].club_id, tackler, start_xy=start, outcome="won",
                        opponent_id=actor.player_id)
            s.team, s.zone = other, self._mirror(z)
            s.possession_n += 1
            return None
        if restart is None and self._band(z) <= 1 and rng.random() < CLEARANCE_RATE:
            land = int(rng.integers(2, self.zx)) * self.zy + int(rng.integers(self.zy))
            self._event(s, "clearance", club, actor, start_xy=start, end_xy=self._point(rng, land, t, s.period))
            if rng.random() >= CLEARANCE_KEPT:
                s.team, s.zone = other, self._mirror(land)
                s.possession_n += 1
            else:
                s.zone = land
            return None
        shoot = restart is None and rng.random() < SHOT_SCALE * self.shot_share[z] * (0.8 + 0.4 * strength[t] / sum(strength))
        if shoot:
            p_goal = GOAL_SCALE * self.goal_rate[z] * (0.6 + 0.8 * actor.attributes.finishing)
            goal_x = L if (t == 0) == (s.period == 1) else 0.0
            r = rng.random()
            outcome = "goal" if r < p_goal else "saved" if r < p_goal + 0.3 else "blocked" if r < p_goal + 0.55 else "off_target"
            self._event(s, "shot", club, actor, subtype="open_play", start_xy=start, end_xy=[goal_x, 34.0],
                        outcome=outcome, body_part="head" if rng.random() < 0.16 else "right_foot")
            if outcome == "goal":
                s.score[t] += 1
                s.team, s.zone = other, (self.zx // 2 - 1) * self.zy + self.zy // 2
                s.possession_n += 1
                return "kick_off"
            if outcome in ("saved", "blocked") and rng.random() < CORNER_FROM_SHOT:
                s.zone = (self.zx - 1) * self.zy + (0 if rng.random() < 0.5 else self.zy - 1)
                return "corner"
            s.team, s.zone = other, self.zy + self.zy // 2  # goal kick or the keeper's ball
            s.possession_n += 1
            return "goal_kick"
        # A pass: completed into a zone drawn from where real passes from here go, or lost.
        quality = 0.6 * actor.attributes.passing + 0.4 * strength[t] / sum(strength)
        logit = math.log(self.completion[z] / max(1 - self.completion[z], 1e-6)) + 1.5 * (quality - 0.6)
        if restart in ("throw_in", "kick_off", "goal_kick", "free_kick", "corner"):
            logit += 1.0
        done = rng.random() < 1.0 / (1.0 + math.exp(-logit))
        z2 = int(rng.choice(len(self.pass_to[z]), p=self.pass_to[z])) if self.pass_to[z].sum() > 0 else z
        end = self._point(rng, z2, t, s.period)
        sub = restart if restart else ("cross" if z2 // self.zy == self.zx - 1 and z // self.zy >= self.zx - 2
                                       and z % self.zy in (0, self.zy - 1) else "ground")
        if done and self._band(z2) > self._band(z) + 1 and rng.random() < OFFSIDES_PER_FORWARD_PASS * 4:
            receiver = self._actor(rng, squad, z2, exclude=actor.player_id)
            self._event(s, "pass", club, actor, subtype=sub, start_xy=start, end_xy=end, outcome="offside",
                        recipient_id=receiver.player_id)
            self._event(s, "offside", club, receiver, start_xy=end)
            s.team, s.zone = other, self._mirror(z2)
            s.possession_n += 1
            return "free_kick"
        if done:
            receiver = self._actor(rng, squad, z2, exclude=actor.player_id)
            self._event(s, "pass", club, actor, subtype=sub, start_xy=start, end_xy=end, outcome="complete",
                        recipient_id=receiver.player_id)
            s.zone = z2
            return None
        self._event(s, "pass", club, actor, subtype=sub, start_xy=start, end_xy=end, outcome="incomplete")
        if sub == "cross" and rng.random() < CORNER_FROM_CROSS:
            self._event(s, "ball_out", clubs[other].club_id, None, subtype="goal_line", start_xy=end)
            s.zone = (self.zx - 1) * self.zy + (0 if z % self.zy < self.zy / 2 else self.zy - 1)
            return "corner"
        s.team, s.zone = other, self._mirror(z2)
        s.possession_n += 1
        if rng.random() < OUT_OF_PLAY_SHARE:
            self._event(s, "ball_out", club, actor, subtype="touchline", start_xy=end)
            return "throw_in"
        winner = self._actor(rng, squads[other], s.zone)
        self._event(s, "interception", clubs[other].club_id, winner, start_xy=end, outcome="won")
        return None

    def _finish(self, match_id: str, seed: int, round_: int | None, clubs: list[Club], durations: list[int],
                s: _State) -> tuple[MatchInfo, list[Event]]:
        home_kit, away_kit = kit_for_fixture(clubs[0], clubs[1])
        sheets = []
        for club, kit in zip(clubs, (home_kit, away_kit), strict=True):
            starters = {p.player_id for p in club.starters()}
            lineup = [LineupEntry(player_id=p.player_id, name=p.display, number=p.number, role=p.role,
                                  starter=p.player_id in starters) for p in club.players]
            sheets.append(TeamSheet(club_id=club.club_id, name=club.name, short_name=club.short_name, kit=Kit(**kit),
                                    formation=club.style.formation, lineup=lineup))
        periods = [PeriodInfo(period=p, duration_ms=d, attacks_left_to_right=clubs[0 if p == 1 else 1].club_id)
                   for p, d in zip((1, 2), durations, strict=True)]
        info = MatchInfo(match_id=match_id, seed=seed, engine="fast", generator_version=GENERATOR_VERSION,
                         round=round_, home=sheets[0], away=sheets[1], periods=periods,
                         final_score={clubs[0].club_id: s.score[0], clubs[1].club_id: s.score[1]})
        poss: dict[int, str] = {}
        events = []
        for k, e in enumerate(s.events, start=1):
            n = e.pop("possession_n")
            e.pop("serial")
            pid = None
            if e["type"] not in ("period_start", "period_end"):
                pid = poss.setdefault(n, possession_id(match_id, len(poss) + 1))
            events.append(Event(event_id=event_id(match_id, k), possession_id=pid, **e))
        return info, events


def write_fast_match(info: MatchInfo, events: list[Event], data_dir: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "match.json").write_text(info.model_dump_json(indent=2), encoding="utf-8", newline="\n")
    with (data_dir / "events.jsonl").open("w", encoding="utf-8", newline="\n") as fh:
        for ev in events:
            fh.write(ev.model_dump_json(exclude_none=False) + "\n")


def play_season(league: League, out: Path, seed: int = 2026) -> dict[str, list[int]]:
    """Every fixture of the season through the fast engine; returns the league table (P, W, D, L, GF, GA, Pts)."""
    engine = FastEngine(league)
    table: dict[str, list[int]] = {c.club_id: [0] * 7 for c in league.clubs}
    for k, fx in enumerate(league.fixtures):
        info, events = engine.play(fx.home, fx.away, fx.match_id, seed=seed * 1000 + k, round_=fx.round)
        write_fast_match(info, events, out / fx.match_id)
        gh, ga = info.final_score[fx.home], info.final_score[fx.away]
        for club, gf, gag in ((fx.home, gh, ga), (fx.away, ga, gh)):
            row = table[club]
            row[0] += 1
            row[1 if gf > gag else 2 if gf == gag else 3] += 1
            row[4] += gf
            row[5] += gag
            row[6] += 3 if gf > gag else 1 if gf == gag else 0
    (out / "table.json").write_text(json.dumps(dict(sorted(table.items(), key=lambda kv: (-kv[1][6], kv[1][5] - kv[1][4]))),
                                               indent=1) + "\n", encoding="utf-8", newline="\n")
    return table
