"""League and season builder (PRD 12.3, 12.5 layer 1).

A fictional 20-club league with 25-player squads, player attributes, club styles, generated kits and a
380-match fixture list. Everything is derived from one seed, so the same seed builds the same league.

Public league data (names, numbers, roles, kits, fixtures) goes to `league.json`. Player attributes and
club styles are generator internals: they go to the held-out truth store, so the live pipeline has to
estimate them from what it observes, exactly as it would on real data (PRD 12.9).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

from offball.core import player_id
from offball.generator.colour import kits_distinguishable, oklch_to_hex
from offball.generator.names import FAMILIES, NameGenerator, is_blocked

CLUB_NAMES: tuple[tuple[str, str, str], ...] = (
    ("kes", "Kestrel Bay", "KES"),
    ("ash", "Ashmoor", "ASH"),
    ("bra", "Brackenford", "BRA"),
    ("sal", "Saltmere", "SAL"),
    ("mor", "Morrowdale", "MOR"),
    ("qua", "Quarrystone", "QUA"),
    ("nor", "Northcairn", "NOR"),
    ("oak", "Oakhallow", "OAK"),
    ("fen", "Fenwyck", "FEN"),
    ("gle", "Glenhollow", "GLE"),
    ("cor", "Corvenna", "COR"),
    ("wre", "Wrenhallow", "WRE"),
    ("dun", "Duncliffe", "DUN"),
    ("lar", "Larkhaven", "LAR"),
    ("har", "Harbourne", "HAR"),
    ("ive", "Ivelmouth", "IVE"),
    ("jun", "Juniper Vale", "JUN"),
    ("low", "Lowmarsh", "LOW"),
    ("pel", "Pellston", "PEL"),
    ("riv", "Rivenmoor", "RIV"),
)


@dataclass(frozen=True)
class Slot:
    """A formation position: role, depth u (0 back line, 1 front line), width v (0 right, 1 left), line."""

    role: str
    u: float
    v: float
    line: int
    number: int


FORMATIONS: dict[str, tuple[Slot, ...]] = {
    "4-3-3": (
        Slot("GK", 0, 0.5, -1, 1),
        Slot("RB", 0.06, 0.08, 0, 2),
        Slot("CB", 0.0, 0.36, 0, 4),
        Slot("CB", 0.0, 0.64, 0, 5),
        Slot("LB", 0.06, 0.92, 0, 3),
        Slot("DM", 0.3, 0.5, 1, 6),
        Slot("CM", 0.52, 0.3, 1, 8),
        Slot("CM", 0.52, 0.7, 1, 10),
        Slot("RW", 0.95, 0.1, 2, 7),
        Slot("ST", 1.0, 0.5, 2, 9),
        Slot("LW", 0.95, 0.9, 2, 11),
    ),
    "4-2-3-1": (
        Slot("GK", 0, 0.5, -1, 1),
        Slot("RB", 0.06, 0.08, 0, 2),
        Slot("CB", 0.0, 0.36, 0, 5),
        Slot("CB", 0.0, 0.64, 0, 4),
        Slot("LB", 0.06, 0.92, 0, 3),
        Slot("DM", 0.3, 0.38, 1, 6),
        Slot("DM", 0.3, 0.62, 1, 8),
        Slot("RW", 0.7, 0.12, 2, 11),
        Slot("AM", 0.72, 0.5, 2, 10),
        Slot("LW", 0.7, 0.88, 2, 7),
        Slot("ST", 1.0, 0.5, 2, 9),
    ),
    "4-4-2": (
        Slot("GK", 0, 0.5, -1, 1),
        Slot("RB", 0.05, 0.08, 0, 2),
        Slot("CB", 0.0, 0.36, 0, 5),
        Slot("CB", 0.0, 0.64, 0, 6),
        Slot("LB", 0.05, 0.92, 0, 3),
        Slot("RM", 0.48, 0.1, 1, 7),
        Slot("CM", 0.44, 0.38, 1, 4),
        Slot("CM", 0.44, 0.62, 1, 8),
        Slot("LM", 0.48, 0.9, 1, 11),
        Slot("ST", 1.0, 0.4, 2, 9),
        Slot("ST", 0.95, 0.6, 2, 10),
    ),
    "3-4-3": (
        Slot("GK", 0, 0.5, -1, 1),
        Slot("CB", 0.0, 0.25, 0, 4),
        Slot("CB", 0.0, 0.5, 0, 5),
        Slot("CB", 0.0, 0.75, 0, 6),
        Slot("RWB", 0.4, 0.05, 1, 2),
        Slot("CM", 0.42, 0.38, 1, 8),
        Slot("CM", 0.42, 0.62, 1, 10),
        Slot("LWB", 0.4, 0.95, 1, 3),
        Slot("RW", 0.95, 0.18, 2, 7),
        Slot("ST", 1.0, 0.5, 2, 9),
        Slot("LW", 0.95, 0.82, 2, 11),
    ),
    "3-5-2": (
        Slot("GK", 0, 0.5, -1, 1),
        Slot("CB", 0.0, 0.25, 0, 4),
        Slot("CB", 0.0, 0.5, 0, 5),
        Slot("CB", 0.0, 0.75, 0, 6),
        Slot("RWB", 0.42, 0.05, 1, 2),
        Slot("CM", 0.45, 0.3, 1, 8),
        Slot("DM", 0.3, 0.5, 1, 14),
        Slot("CM", 0.45, 0.7, 1, 10),
        Slot("LWB", 0.42, 0.95, 1, 3),
        Slot("ST", 1.0, 0.4, 2, 9),
        Slot("ST", 0.95, 0.6, 2, 11),
    ),
    # Kestrel Bay's 4-3-3 with an attacking 10, and Ashmoor's 4-2-3-1 with wide midfielders and a central
    # midfielder beside the holder.
    "4-1-2-3": (
        Slot("GK", 0, 0.5, -1, 1),
        Slot("RB", 0.06, 0.08, 0, 2),
        Slot("CB", 0.0, 0.36, 0, 4),
        Slot("CB", 0.0, 0.64, 0, 5),
        Slot("LB", 0.06, 0.92, 0, 3),
        Slot("DM", 0.3, 0.5, 1, 6),
        Slot("CM", 0.5, 0.36, 1, 8),
        Slot("AM", 0.64, 0.64, 1, 10),
        Slot("RW", 0.95, 0.1, 2, 7),
        Slot("ST", 1.0, 0.5, 2, 9),
        Slot("LW", 0.95, 0.9, 2, 11),
    ),
    "4-4-1-1": (
        Slot("GK", 0, 0.5, -1, 1),
        Slot("RB", 0.06, 0.08, 0, 2),
        Slot("CB", 0.0, 0.36, 0, 5),
        Slot("CB", 0.0, 0.64, 0, 4),
        Slot("LB", 0.06, 0.92, 0, 3),
        Slot("DM", 0.3, 0.38, 1, 6),
        Slot("CM", 0.32, 0.62, 1, 8),
        Slot("RM", 0.55, 0.1, 1, 11),
        Slot("AM", 0.72, 0.5, 2, 10),
        Slot("LM", 0.55, 0.9, 1, 7),
        Slot("ST", 1.0, 0.5, 2, 9),
    ),
}
# The shapes other clubs draw from, in a fixed order so the league stays the same.
RANDOM_FORMATIONS = ("4-3-3", "4-2-3-1", "4-4-2", "3-4-3", "3-5-2")

# Role -> (top speed m/s, acceleration m/s^2) means.
PHYSICAL = {
    "GK": (7.0, 4.6),
    "CB": (8.3, 5.3),
    "RB": (8.9, 5.9),
    "LB": (8.9, 5.9),
    "RWB": (9.0, 6.0),
    "LWB": (9.0, 6.0),
    "DM": (8.3, 5.4),
    "CM": (8.5, 5.6),
    "AM": (8.6, 5.8),
    "RM": (8.9, 5.9),
    "LM": (8.9, 5.9),
    "RW": (9.2, 6.2),
    "LW": (9.2, 6.2),
    "ST": (8.9, 6.0),
}

# Role -> technical attribute means, before club quality.
TECHNICAL: dict[str, dict[str, float]] = {
    "GK": dict(passing=0.5, vision=0.4, first_touch=0.45, dribbling=0.2, finishing=0.05, tackling=0.2,
               scanning=0.6, run_timing=0.1, decoy_tendency=0.0, discipline=0.75, composure=0.6, aerial=0.8,
               handling=0.7),
    "CB": dict(passing=0.55, vision=0.45, first_touch=0.5, dribbling=0.35, finishing=0.25, tackling=0.75,
               scanning=0.55, run_timing=0.25, decoy_tendency=0.05, discipline=0.62, composure=0.55, aerial=0.75),
    "FB": dict(passing=0.6, vision=0.5, first_touch=0.58, dribbling=0.56, finishing=0.3, tackling=0.62,
               scanning=0.5, run_timing=0.5, decoy_tendency=0.25, discipline=0.55, composure=0.5, aerial=0.5),
    "DM": dict(passing=0.72, vision=0.65, first_touch=0.65, dribbling=0.5, finishing=0.35, tackling=0.7,
               scanning=0.7, run_timing=0.35, decoy_tendency=0.1, discipline=0.66, composure=0.65, aerial=0.6),
    "CM": dict(passing=0.74, vision=0.68, first_touch=0.68, dribbling=0.6, finishing=0.45, tackling=0.55,
               scanning=0.65, run_timing=0.55, decoy_tendency=0.25, discipline=0.55, composure=0.62, aerial=0.5),
    "AM": dict(passing=0.75, vision=0.75, first_touch=0.72, dribbling=0.7, finishing=0.58, tackling=0.35,
               scanning=0.62, run_timing=0.62, decoy_tendency=0.3, discipline=0.4, composure=0.66, aerial=0.4),
    "W": dict(passing=0.64, vision=0.6, first_touch=0.68, dribbling=0.75, finishing=0.58, tackling=0.3,
              scanning=0.5, run_timing=0.62, decoy_tendency=0.38, discipline=0.38, composure=0.58, aerial=0.4),
    "ST": dict(passing=0.6, vision=0.55, first_touch=0.68, dribbling=0.62, finishing=0.75, tackling=0.3,
               scanning=0.5, run_timing=0.7, decoy_tendency=0.5, discipline=0.35, composure=0.66, aerial=0.62),
}
ROLE_GROUP = {
    "GK": "GK", "CB": "CB", "RB": "FB", "LB": "FB", "RWB": "FB", "LWB": "FB", "DM": "DM", "CM": "CM",
    "AM": "AM", "RM": "W", "LM": "W", "RW": "W", "LW": "W", "ST": "ST",
}


@dataclass
class Attributes:
    top_speed: float
    accel: float
    decel: float
    turn_rate: float
    stamina: float
    passing: float
    vision: float
    first_touch: float
    dribbling: float
    finishing: float
    tackling: float
    scanning: float
    run_timing: float
    decoy_tendency: float
    discipline: float
    composure: float
    aerial: float
    decision_speed: float
    work_rate: float
    handling: float = 0.0

    @property
    def decision_interval_s(self) -> float:
        """Players decide every 200 to 400 ms, depending on decision speed (PRD 12.4)."""
        return 0.4 - 0.2 * self.decision_speed


@dataclass
class Player:
    player_id: str
    club_id: str
    number: int
    first_name: str
    surname: str
    role: str
    foot: str
    age: int
    height_cm: int
    attributes: Attributes

    @property
    def display(self) -> str:
        return f"{self.first_name[0]}. {self.surname}"

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.surname}"


@dataclass
class ClubStyle:
    """Club tactical style (PRD 12.3). All values 0..1 except rest_defence and formation."""

    formation: str
    press_height: float
    press_intensity: float
    tempo: float
    directness: float
    width: float
    line_height: float
    rest_defence: int
    build_up: str
    rotation: float
    archetype: str


@dataclass
class KitSet:
    home: dict
    away: dict
    third: dict


@dataclass
class Club:
    club_id: str
    name: str
    short_name: str
    quality: float
    style: ClubStyle
    kits: KitSet
    badge: dict
    players: list[Player] = field(default_factory=list)

    def starters(self) -> list[Player]:
        """The first-choice XI in formation order."""
        by_number = {p.number: p for p in self.players}
        return [by_number[s.number] for s in FORMATIONS[self.style.formation]]

    def player(self, pid: str) -> Player:
        for p in self.players:
            if p.player_id == pid:
                return p
        raise KeyError(pid)


@dataclass
class Fixture:
    round: int
    home: str
    away: str
    match_id: str


@dataclass
class League:
    seed: int
    clubs: list[Club]
    fixtures: list[Fixture]

    def club(self, club_id: str) -> Club:
        for c in self.clubs:
            if c.club_id == club_id:
                return c
        raise KeyError(club_id)

    def player(self, pid: str) -> Player:
        return self.club(pid.split("-")[0]).player(pid)

    def public_json(self) -> dict:
        """League data any component may read: no attributes, no styles."""
        return {
            "schema_version": "2.0",
            "seed": self.seed,
            "synthetic": True,
            "clubs": [
                {
                    "club_id": c.club_id,
                    "name": c.name,
                    "short_name": c.short_name,
                    "formation": c.style.formation,
                    "kits": asdict(c.kits),
                    "badge": c.badge,
                    "squad": [
                        {
                            "player_id": p.player_id,
                            "number": p.number,
                            "name": p.full_name,
                            "display": p.display,
                            "role": p.role,
                            "foot": p.foot,
                            "age": p.age,
                            "height_cm": p.height_cm,
                        }
                        for p in c.players
                    ],
                }
                for c in self.clubs
            ],
            "fixtures": [asdict(f) for f in self.fixtures],
        }

    def truth_json(self) -> dict:
        """Hidden generator parameters, for the truth store only."""
        return {
            "seed": self.seed,
            "clubs": {
                c.club_id: {"quality": c.quality, "style": asdict(c.style)} for c in self.clubs
            },
            "players": {p.player_id: asdict(p.attributes) for c in self.clubs for p in c.players},
        }

    def save(self, public_dir: Path, truth_dir: Path) -> None:
        public_dir.mkdir(parents=True, exist_ok=True)
        truth_dir.mkdir(parents=True, exist_ok=True)
        (public_dir / "league.json").write_text(json.dumps(self.public_json(), indent=1, ensure_ascii=False),
                                                encoding="utf-8", newline="\n")
        (truth_dir / "league_truth.json").write_text(json.dumps(self.truth_json(), indent=1), encoding="utf-8",
                                                     newline="\n")


ARCHETYPES: dict[str, dict[str, float | str | int]] = {
    "high_press": dict(press_height=0.82, press_intensity=0.82, tempo=0.72, directness=0.45, width=0.62,
                       line_height=0.78, rest_defence=2, build_up="back_two", rotation=0.55),
    "possession": dict(press_height=0.62, press_intensity=0.6, tempo=0.38, directness=0.18, width=0.75,
                       line_height=0.62, rest_defence=3, build_up="back_three", rotation=0.7),
    "low_block": dict(press_height=0.22, press_intensity=0.3, tempo=0.66, directness=0.78, width=0.45,
                      line_height=0.25, rest_defence=4, build_up="keeper_long", rotation=0.2),
    "direct": dict(press_height=0.48, press_intensity=0.55, tempo=0.7, directness=0.86, width=0.58,
                   line_height=0.45, rest_defence=3, build_up="keeper_long", rotation=0.25),
    "balanced": dict(press_height=0.5, press_intensity=0.5, tempo=0.55, directness=0.45, width=0.6,
                     line_height=0.5, rest_defence=3, build_up="back_two", rotation=0.4),
    "wing_play": dict(press_height=0.55, press_intensity=0.55, tempo=0.6, directness=0.5, width=0.9,
                      line_height=0.52, rest_defence=3, build_up="back_two", rotation=0.35),
}

# Designed clubs for the showcase; the others are drawn from the seed.
FIXED_CLUBS: dict[str, dict] = {
    "kes": dict(archetype="high_press", formation="4-3-3", quality=0.66, hue=255.0, away_hue=95.0),
    "ash": dict(archetype="balanced", formation="4-2-3-1", quality=0.62, hue=50.0, away_hue=200.0),
}

# Showcase players, pinned so the demo, PRD and UI agree on who did what.
FIXED_PLAYERS: dict[tuple[str, int], dict] = {
    ("kes", 9): dict(first="Joren", last="Velmar", decoy_tendency=0.88, run_timing=0.8, top_speed=9.3),
    ("kes", 7): dict(first="Piet", last="Quillan"),
    ("kes", 10): dict(first="Tobin", last="Arkwell", run_timing=0.82, finishing=0.78),
    ("kes", 8): dict(first="Rowan", last="Delacorte", passing=0.84, vision=0.84),
    ("ash", 5): dict(first="Lars", last="Hendricx", discipline=0.22),
    ("ash", 10): dict(first="Sander", last="Moravec"),
}


# Kestrel Bay's and Ashmoor's shapes and starting XIs. Both are pinned after the league is built, so every other
# club's draws stay the same.
SHOWCASE_FORMATIONS = {"kes": "4-1-2-3", "ash": "4-4-1-1"}
SHOWCASE_NAMES: dict[str, dict[int, tuple[str, str]]] = {
    "kes": {1: ("Edric", "Thorncastle"), 2: ("Dorian", "Ferrow"), 3: ("Kasimir", "Ambrose"), 4: ("Soren", "Brannagh"),
            5: ("Lowen", "Marrow"), 6: ("Orrin", "Castellane"), 7: ("Piet", "Quillan"), 8: ("Rowan", "Delacorte"),
            9: ("Joren", "Velmar"), 10: ("Tobin", "Arkwell"), 11: ("Nevin", "Penhallow")},
    "ash": {1: ("Bram", "Aldwyn"), 2: ("Caspar", "Fennimore"), 3: ("Hollis", "Strand"), 4: ("Garrick", "Tallow"),
            5: ("Lars", "Hendricx"), 6: ("Valen", "Pryor"), 7: ("Alden", "Kettering"), 8: ("Ivor", "Rowntree"),
            9: ("Emrys", "Wyndham"), 10: ("Sander", "Moravec"), 11: ("Florin", "Danvers")},
}


def _pin_showcase(clubs: list[Club], names: NameGenerator) -> None:
    for club in clubs:
        shape = SHOWCASE_FORMATIONS.get(club.club_id)
        if shape is not None:
            club.style.formation = shape
            roles = {s.number: s.role for s in FORMATIONS[shape]}
            for p in club.players:
                p.role = roles.get(p.number, p.role)
        for p in club.players:
            pinned = SHOWCASE_NAMES.get(club.club_id, {}).get(p.number)
            if pinned is None:
                continue
            first, last = pinned
            if is_blocked(f"{first} {last}", last, names.blocklist):
                raise ValueError(f"{first} {last} is on the real-name blocklist (gate 7)")
            p.first_name, p.surname = first, last


def _clip(x: float, lo: float = 0.05, hi: float = 0.98) -> float:
    return float(min(hi, max(lo, x)))


def _attributes(role: str, quality: float, rng: np.random.Generator) -> Attributes:
    group = ROLE_GROUP[role]
    base = TECHNICAL[group]
    lift = (quality - 0.6) * 0.6

    def tech(name: str, sd: float = 0.09) -> float:
        return _clip(base.get(name, 0.0) + lift + rng.normal(0, sd))

    speed_mean, accel_mean = PHYSICAL[role]
    top_speed = float(np.clip(rng.normal(speed_mean, 0.32), 6.6, 9.9))
    accel = float(np.clip(rng.normal(accel_mean, 0.35), 4.2, 6.9))
    return Attributes(
        top_speed=round(top_speed, 3),
        accel=round(accel, 3),
        decel=round(float(np.clip(accel * 1.25 + rng.normal(0, 0.2), 5.0, 8.8)), 3),
        turn_rate=round(float(np.clip(rng.normal(9.0, 1.2), 6.0, 13.0)), 3),
        stamina=tech("stamina") if "stamina" in base else _clip(rng.normal(0.68 + lift, 0.1)),
        passing=tech("passing"),
        vision=tech("vision"),
        first_touch=tech("first_touch"),
        dribbling=tech("dribbling"),
        finishing=tech("finishing"),
        tackling=tech("tackling"),
        scanning=tech("scanning"),
        run_timing=tech("run_timing"),
        decoy_tendency=_clip(base["decoy_tendency"] + rng.normal(0, 0.1), 0.0, 0.95),
        discipline=tech("discipline", 0.12),
        composure=tech("composure"),
        aerial=tech("aerial"),
        decision_speed=_clip(rng.normal(0.5 + lift, 0.15)),
        work_rate=_clip(rng.normal(0.62, 0.12)),
        handling=tech("handling") if role == "GK" else 0.0,
    )


def _style(archetype: str, formation: str, rng: np.random.Generator) -> ClubStyle:
    a = ARCHETYPES[archetype]

    def jitter(name: str) -> float:
        return round(_clip(float(a[name]) + rng.normal(0, 0.05)), 3)

    return ClubStyle(
        formation=formation,
        press_height=jitter("press_height"),
        press_intensity=jitter("press_intensity"),
        tempo=jitter("tempo"),
        directness=jitter("directness"),
        width=jitter("width"),
        line_height=jitter("line_height"),
        rest_defence=int(a["rest_defence"]),
        build_up=str(a["build_up"]),
        rotation=jitter("rotation"),
        archetype=archetype,
    )


def _kit(hue: float, rng: np.random.Generator, light: float | None = None) -> dict:
    lightness = light if light is not None else float(rng.uniform(0.42, 0.72))
    primary = oklch_to_hex(lightness, float(rng.uniform(0.11, 0.17)), hue)
    secondary = oklch_to_hex(0.95 if lightness < 0.6 else 0.22, 0.02, hue)
    pattern = ["plain", "plain", "hoops", "stripes", "halves", "sash"][int(rng.integers(6))]
    return {"primary": primary, "secondary": secondary, "pattern": pattern}


def _badge(club_id: str, kits: KitSet, rng: np.random.Generator) -> dict:
    shapes = ("shield", "circle", "diamond", "hexagon", "pennant")
    glyphs = ("wing", "wave", "tower", "star", "oak", "chevron", "ring", "bars", "key", "arch")
    return {
        "shape": shapes[int(rng.integers(len(shapes)))],
        "glyph": glyphs[int(rng.integers(len(glyphs)))],
        "field": kits.home["primary"],
        "accent": kits.home["secondary"],
        "initials": club_id.upper(),
    }


def _squad(club: Club, rng: np.random.Generator, names: NameGenerator, family_bias: int) -> list[Player]:
    slots = FORMATIONS[club.style.formation]
    roles = [s.role for s in slots]
    numbers = [s.number for s in slots]
    # Fourteen more: two keepers, then cover for every line.
    bench_roles = ["GK", "GK", "CB", "CB", roles[1], roles[4], "DM", "CM", "CM", "AM", "RW", "LW", "ST", "ST"]
    free = [n for n in range(12, 40) if n not in numbers]
    rng.shuffle(free)
    roles += bench_roles
    numbers += sorted(free[: len(bench_roles)])
    players = []
    for role, number in zip(roles, numbers, strict=True):
        fixed = FIXED_PLAYERS.get((club.club_id, number))
        # Most of a squad shares the club's naming style; a third come from elsewhere.
        family = FAMILIES[family_bias] if rng.random() < 0.65 else None
        if fixed:
            first, last = fixed["first"], fixed["last"]
            names.reserve(last)
        else:
            first, last = names.person(family)
        attrs = _attributes(role, club.quality, rng)
        if fixed:
            for key, value in fixed.items():
                if key not in ("first", "last"):
                    setattr(attrs, key, value)
        foot_draw = rng.random()
        foot = "right" if foot_draw < 0.74 else "left" if foot_draw < 0.97 else "both"
        if role in ("LB", "LWB", "LM") and rng.random() < 0.6:
            foot = "left"
        players.append(
            Player(
                player_id=player_id(club.club_id, number),
                club_id=club.club_id,
                number=number,
                first_name=first,
                surname=last,
                role=role,
                foot=foot,
                age=int(rng.integers(18, 35)),
                height_cm=int(np.clip(rng.normal(188 if role in ("GK", "CB") else 179, 6), 165, 201)),
                attributes=attrs,
            )
        )
    return players


def _round_robin(first: tuple[tuple[str, str], ...]) -> list[list[tuple[str, str]]]:
    """Double round robin by the circle method, home and away balanced, whose first round is `first`."""
    ids = [h for h, _ in first] + [a for _, a in reversed(first)]
    n = len(ids)
    rounds: list[list[tuple[str, str]]] = []
    fixed, rest = ids[0], ids[1:]
    for r in range(n - 1):
        order = [fixed] + rest
        pairs = []
        for i in range(n // 2):
            a, b = order[i], order[n - 1 - i]
            pairs.append((a, b) if (r + i) % 2 == 0 else (b, a))
        rounds.append(pairs if r else list(first))
        rest = rest[-1:] + rest[:-1]
    second = [[(b, a) for a, b in rnd] for rnd in rounds]
    return rounds + second


SHOWCASE_ROUND = 27
# The showcase round's ten fixtures, home side first.
SHOWCASE_FIXTURES = (("kes", "ash"), ("bra", "sal"), ("mor", "qua"), ("nor", "oak"), ("fen", "gle"), ("cor", "wre"),
                     ("dun", "lar"), ("har", "ive"), ("jun", "low"), ("pel", "riv"))


def build_league(seed: int = 2026) -> League:
    rng = np.random.default_rng(seed)
    names = NameGenerator(np.random.default_rng(seed + 1))
    archetypes = list(ARCHETYPES)
    formations = list(RANDOM_FORMATIONS)
    used_hues: list[float] = []
    clubs: list[Club] = []
    for idx, (cid, name, short) in enumerate(CLUB_NAMES):
        fixed = FIXED_CLUBS.get(cid)
        if fixed:
            archetype, formation, quality = fixed["archetype"], fixed["formation"], fixed["quality"]
            hue, away_hue = fixed["hue"], fixed["away_hue"]
            home = _kit(hue, rng, light=0.5)
            away = _kit(away_hue, rng, light=0.86)
        else:
            archetype = archetypes[idx % len(archetypes)]
            formation = formations[int(rng.integers(len(formations)))]
            quality = float(np.clip(rng.normal(0.6, 0.05), 0.48, 0.72))
            # Spread home hues around the wheel so the league stays visually varied.
            hue = float((idx * 137.508 + rng.uniform(-12, 12)) % 360)
            away_hue = (hue + 150 + rng.uniform(-30, 30)) % 360
            home = _kit(hue, rng)
            away = _kit(away_hue, rng, light=float(rng.uniform(0.8, 0.92)))
        used_hues.append(hue)
        third = {"primary": "#1c1f24", "secondary": "#f2f2f2", "pattern": "plain"}
        kits = KitSet(home=home, away=away, third=third)
        club = Club(
            club_id=cid,
            name=name,
            short_name=short,
            quality=round(quality, 3),
            style=_style(archetype, formation, rng),
            kits=kits,
            badge={},
        )
        club.badge = _badge(cid, kits, rng)
        club.players = _squad(club, rng, names, family_bias=idx % len(FAMILIES))
        clubs.append(club)

    _pin_showcase(clubs, names)
    rounds = _round_robin(SHOWCASE_FIXTURES)
    rounds[0], rounds[SHOWCASE_ROUND - 1] = rounds[SHOWCASE_ROUND - 1], rounds[0]
    fixtures = []
    for r, rnd in enumerate(rounds, start=1):
        for i, (h, a) in enumerate(rnd, start=1):
            fixtures.append(Fixture(round=r, home=h, away=a, match_id=f"s{r:02d}-{i:02d}"))
    return League(seed=seed, clubs=clubs, fixtures=fixtures)


def kit_for_fixture(home: Club, away: Club) -> tuple[dict, dict]:
    """Kits for a match: home wears home; away switches kit until both pass the colour checks (PRD 16.3)."""
    for away_kit in (away.kits.home, away.kits.away, away.kits.third):
        if kits_distinguishable(home.kits.home["primary"], away_kit["primary"]):
            return home.kits.home, away_kit
    # Nothing passes on colour alone: add a pattern so shape carries the difference.
    patterned = dict(away.kits.away)
    patterned["pattern"] = "hoops" if home.kits.home["pattern"] != "hoops" else "stripes"
    return home.kits.home, patterned
