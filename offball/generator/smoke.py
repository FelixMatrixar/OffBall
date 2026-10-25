"""The CI smoke set (PRD 12.11): every one of the 18 moment types planted at least once, in short matches.

One moment a match, each pairing and seed checked to verify on the calibrated engine, so a change that breaks a
moment shows up as that one match failing. The decoy run is planted twice. The set-piece screen gets a longer
match because corners are rare, and space lost and fatigue gap share one long enough for five minutes before and
after each.
"""

from __future__ import annotations

from offball.generator.script import MatchScript, StoryMoment

# match id, home, away, seed, half minutes, [(moment type, minute, intended outcome)]
FIXTURES: list[tuple[str, str, str, int, float, list[tuple[str, float, str]]]] = [
    ("smk1", "har", "ive", 502, 5, [("decoy_run", 2.0, "chance")]),
    ("smk2", "kes", "ash", 502, 5, [("decoy_run", 2.0, "chance")]),
    ("smk3", "bra", "sal", 102, 5, [("null_run", 6.0, "chance")]),
    ("smk4", "kes", "ash", 104, 5, [("overlap", 1.5, "chance")]),
    ("smk5", "kes", "ash", 125, 5, [("null_overlap", 1.5, "chance")]),
    ("smk6", "kes", "ash", 611, 5, [("timed_run_in_behind", 1.5, "chance")]),
    ("smk7", "kes", "ash", 107, 5, [("underlap", 1.5, "chance")]),
    ("smk8", "kes", "ash", 107, 5, [("third_man_run", 6.0, "chance")]),
    ("smk9", "nor", "oak", 320, 5, [("switch_of_play", 1.5, "chance")]),
    ("smk10", "dun", "lar", 328, 5, [("press_broken", 1.5, "chance")]),
    ("smk11", "dun", "lar", 334, 5, [("pinning", 1.5, "chance")]),
    ("smk12", "kes", "ash", 337, 5, [("rest_defence_exposed", 1.5, "chance")]),
    ("smk13", "kes", "ash", 110, 5, [("blind_side_run", 1.5, "chance")]),
    ("smk14", "dun", "lar", 310, 5, [("false_9_drop", 1.5, "chance")]),
    ("smk15", "nor", "oak", 314, 5, [("cover_shadow", 1.5, "chance")]),
    ("smk16", "nor", "oak", 111, 5, [("rotation", 6.0, "chance")]),
    ("smk17", "kes", "ash", 528, 15, [("set_piece_screen", 1.0, "chance")]),
    ("smk18", "kes", "ash", 114, 12, [("space_lost", 5.5, "chance"), ("fatigue_gap", 17.5, "chance")]),
]


def smoke_scripts() -> list[MatchScript]:
    scripts = []
    for mid, home, away, seed, half, moments in FIXTURES:
        scripts.append(MatchScript(
            match_id=mid, home=home, away=away, seed=seed, half_minutes=half,
            moments=[StoryMoment(key=f"k{n:02d}", type=kind, team=home, minute=minute, outcome=outcome,
                                 window_minutes=8.0 if kind in ("space_lost", "fatigue_gap") else 4.0)
                     for n, (kind, minute, outcome) in enumerate(moments, start=1)]))
    return scripts
