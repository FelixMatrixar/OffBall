"""OffBall-Bench and the showcase matchday (PRD 12.11).

OffBall-Bench is 100 full matches with tracking: 70 with three to six planted moments, 20 with only null moments
planted, and 10 unscripted with oracle labels only, split into 40 dev and 60 test matches. The planted moments are
dealt so every type appears at least ten times. The showcase matchday is the ten fixtures of the showcase round,
played at the same time: Kestrel Bay v Ashmoor is the showcase match, and each other fixture plants one moment
around the hour, with oracle labels for the rest.
"""

from __future__ import annotations

import numpy as np

from offball.contracts.truth import NULL_TYPES
from offball.generator.moments import PLANS
from offball.generator.script import MatchScript, StoryMoment

# Team moments need room: space lost five minutes either side, fatigue gap late on.
LONG = {"space_lost": 7.0, "fatigue_gap": 8.0, "set_piece_screen": 3.0}


def _moment_minutes(kinds: list[str], rng: np.random.Generator) -> list[float]:
    """Kick-off times for a match's moments, spread over both halves, clear of half-time."""
    minutes, t = [], float(rng.uniform(3.0, 8.0))
    for kind in kinds:
        if kind == "fatigue_gap":
            minutes.append(max(t, 72.0))
            t = max(t, 72.0) + LONG[kind]
            continue
        if kind == "space_lost" and t < 6.0:
            t = 6.0
        if 37.0 < t < 51.0:
            t = 51.0  # second-half moments start after the break
        minutes.append(round(t, 1))
        t += LONG.get(kind, 4.0) + float(rng.uniform(2.0, 9.0))
    return minutes


def bench_scripts(league, matches: int = 100, seed: int = 2026) -> tuple[list[MatchScript], dict[str, list[str]]]:
    rng = np.random.default_rng(seed)
    planted_types = [k for k in PLANS if k not in NULL_TYPES]
    n_planted, n_null = round(matches * 0.7), round(matches * 0.2)
    deck: list[str] = []
    fixtures = list(league.fixtures)
    rng.shuffle(fixtures)
    scripts = []
    for k in range(matches):
        fx = fixtures[k % len(fixtures)]
        mid = f"b{k + 1:03d}"
        if k < n_planted:
            n = int(rng.integers(3, 7))
            kinds = []
            for _ in range(n):
                if not deck:  # deal every type in turn, so each appears at least ten times across the set
                    deck = list(rng.permutation(planted_types))
                kinds.append(deck.pop())
            kinds = sorted(set(kinds), key=lambda x: x == "fatigue_gap")  # the late one last
        elif k < n_planted + n_null:
            kinds = [str(rng.choice(sorted(NULL_TYPES))) for _ in range(int(rng.integers(3, 7)))]
        else:
            kinds = []
        minutes = _moment_minutes(kinds, rng)
        teams = [fx.home, fx.away]
        moments = [StoryMoment(key=f"k{n + 1:02d}", type=kind, team=teams[int(rng.integers(2))], minute=m,
                               window_minutes=8.0 if kind in LONG else 4.0)
                   for n, (kind, m) in enumerate(zip(kinds, minutes, strict=True)) if m <= 88.0]
        scripts.append(MatchScript(match_id=mid, home=fx.home, away=fx.away, seed=seed * 100 + k, round=fx.round,
                                   half_minutes=45.0, moments=moments))
    order = list(rng.permutation(len(scripts)))
    split = {"dev": sorted(scripts[i].match_id for i in order[:round(matches * 0.4)]),
             "test": sorted(scripts[i].match_id for i in order[round(matches * 0.4):])}
    return scripts, split


# The moment each matchday fixture plants: (type, team, minute it may start, the player who makes it).
MATCHDAY_MOMENTS: dict[tuple[str, str], tuple[str, str, float, str | None]] = {
    ("bra", "sal"): ("overlap", "bra", 56.5, None),
    ("mor", "qua"): ("press_broken", "mor", 63.0, None),
    ("nor", "oak"): ("third_man_run", "nor", 61.5, None),
    ("fen", "gle"): ("fatigue_gap", "fen", 72.0, None),
    ("cor", "wre"): ("switch_of_play", "cor", 58.5, None),
    ("dun", "lar"): ("cover_shadow", "lar", 57.0, None),
    ("har", "ive"): ("space_lost", "ive", 57.0, None),
    ("jun", "low"): ("blind_side_run", "low", 55.5, "low-11"),
    ("pel", "riv"): ("rotation", "pel", 60.5, None),
}


def matchday_scripts(league, round_: int = 27, seed: int = 2026) -> list[MatchScript]:
    """The round's fixtures, each planting its MATCHDAY_MOMENTS moment; a fixture without one plays unscripted.
    Kestrel Bay v Ashmoor is left out: it is the showcase match."""
    scripts = []
    for k, fx in enumerate(f for f in league.fixtures if f.round == round_):
        if (fx.home, fx.away) == ("kes", "ash"):
            continue
        moments = []
        if (fx.home, fx.away) in MATCHDAY_MOMENTS:
            kind, team, minute, creator = MATCHDAY_MOMENTS[(fx.home, fx.away)]
            moments = [StoryMoment(key="k01", type=kind, team=team, minute=minute, creator_id=creator,
                                   window_minutes=8.0 if kind in LONG else 4.0)]
        scripts.append(MatchScript(match_id=fx.match_id, home=fx.home, away=fx.away, seed=seed * 1000 + k,
                                   round=fx.round, half_minutes=45.0, moments=moments))
    return scripts
