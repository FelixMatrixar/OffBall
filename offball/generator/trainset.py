"""The credit training split (PRD 12.9, 13): short directed matches that plant each moment type several times, with
true counterfactual credit, for the model that learns off-ball credit.

The same pairings and lengths as the smoke set, which are known to plant each type, with new seeds, so no match
repeats a smoke match. The smoke, matchday and showcase moments stay for development and testing.
"""

from __future__ import annotations

from offball.contracts import NULL_TYPES
from offball.generator.script import MatchScript, StoryMoment
from offball.generator.smoke import FIXTURES

PER_TYPE = 5
SEED_BASE = 20_000


def credit_scripts(per_type: int = PER_TYPE, first: int = 1) -> list[MatchScript]:
    """`per_type` matches for each smoke pairing, numbered and seeded from `first`, so a later batch starting
    after the last one adds matches without repeating any."""
    scripts, n = [], first - 1
    for _mid, home, away, _seed, half, moments in FIXTURES:
        if any(kind in NULL_TYPES for kind, _, _ in moments):
            continue
        for _ in range(per_type):
            n += 1
            scripts.append(MatchScript(
                match_id=f"crd{n:03d}", home=home, away=away, seed=SEED_BASE + n, half_minutes=half,
                moments=[StoryMoment(key=f"k{k:02d}", type=kind, team=home, minute=minute, outcome=outcome,
                                     window_minutes=8.0 if kind in ("space_lost", "fatigue_gap") else 4.0)
                         for k, (kind, minute, outcome) in enumerate(moments, start=1)]))
    return scripts
