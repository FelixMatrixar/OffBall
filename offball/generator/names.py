"""Fictional player names from multilingual syllable sets (PRD 12.1).

Names are checked against a blocklist built from the calibration rosters and lists of professional
players. The blocklist is stored as salted SHA-256 hashes of normalised names, so the repository never
contains real names in plain text (submission checklist, rule 4.3). `calibration/build_blocklist.py`
builds it at run time from downloaded rosters.
"""

from __future__ import annotations

import hashlib
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import numpy as np

BLOCKLIST_SALT = "offball-blocklist-v1"
VOWELS = frozenset("aeiouy")
BLOCKLIST_PATH = Path(__file__).resolve().parents[2] / "calibration" / "blocklist.sha256.txt"


@dataclass(frozen=True)
class Family:
    """A naming style: syllables, endings and first names that sound like one part of the world."""

    name: str
    onsets: tuple[str, ...]
    vowels: tuple[str, ...]
    middles: tuple[str, ...]
    endings: tuple[str, ...]
    first_names: tuple[str, ...]


FAMILIES: tuple[Family, ...] = (
    Family(
        "atlantic",
        ("Ark", "Brack", "Cal", "Dun", "Fen", "Hal", "Kest", "Lor", "Mar", "Quill", "Rad", "Tam", "Wex", "Yar"),
        ("a", "e", "i", "o"),
        ("ber", "den", "ley", "mor", "ran", "wen"),
        ("well", "by", "ford", "wick", "more", "ton", "ridge", "an", "cott", "ham"),
        ("Tobin", "Piet", "Corin", "Ellis", "Rowan", "Alder", "Brannoc", "Mylo", "Ewan", "Jory"),
    ),
    Family(
        "iberian",
        ("Al", "Bel", "Cer", "Dav", "Esqu", "Gar", "Lur", "Mend", "Orr", "Qu", "Ruv", "Tel", "Val", "Zar"),
        ("a", "e", "i", "o", "u"),
        ("ad", "ar", "ell", "ir", "or", "um"),
        ("ez", "eiro", "ado", "illo", "ano", "eda", "ales", "ira", "ozo", "ente"),
        ("Iker", "Joaquim", "Rui", "Tiago", "Mateus", "Unai", "Eloy", "Bento", "Caio", "Nuno"),
    ),
    Family(
        "central",
        ("Brz", "Dvor", "Hol", "Jan", "Kral", "Mor", "Nov", "Pav", "Rad", "Stav", "Vel", "Zel"),
        ("a", "e", "i", "o"),
        ("an", "ec", "ik", "om", "ov"),
        ("ec", "ak", "ik", "ovic", "an", "ar", "isz", "enko", "ar"),
        ("Matej", "Lukas", "Tomek", "Ondrej", "Kuba", "Radim", "Stepan", "Milos", "Dusan", "Viktor"),
    ),
    Family(
        "lowlands",
        ("Ber", "Dek", "Gr", "Hend", "Jans", "Kl", "Ma", "Ost", "Rijk", "Sm", "Vos", "Wil"),
        ("a", "e", "i", "oe", "o"),
        ("er", "el", "en", "ric"),
        ("x", "ens", "ijk", "dt", "ema", "stra", "huis", "oord", "kamp"),
        ("Lars", "Sander", "Joost", "Wout", "Teun", "Daan", "Ruben", "Mees", "Sem", "Jens"),
    ),
    Family(
        "west_african",
        ("Ad", "Ak", "Ba", "Dem", "Ek", "Ib", "Kw", "Ob", "Ol", "Os", "Tem", "Yaw"),
        ("a", "e", "i", "o", "u"),
        ("ad", "em", "ik", "un", "ow"),
        ("ola", "ade", "emi", "uwa", "oko", "aba", "ele", "osu", "anke"),
        ("Kwame", "Tunde", "Kofi", "Emeka", "Seyi", "Ayo", "Kobina", "Femi", "Yaw", "Chidi"),
    ),
    Family(
        "nordic",
        ("Ask", "Bj", "Dal", "Eld", "Fj", "Hag", "Lund", "Ny", "Sk", "Stor", "Tor", "Vik"),
        ("a", "e", "i", "o", "y"),
        ("ar", "el", "er", "or"),
        ("sen", "rud", "dal", "strom", "lund", "vik", "heim", "berg", "nes"),
        ("Eskil", "Torvald", "Halvar", "Sigurd", "Arne", "Leif", "Odd", "Vemund", "Brede", "Kjell"),
    ),
    Family(
        "maghreb",
        ("Ab", "Bel", "Dj", "Fad", "Ham", "Kad", "Mah", "Nas", "Rah", "Sal", "Tah", "Zah"),
        ("a", "i", "ou"),
        ("ad", "am", "ir", "un"),
        ("ani", "ari", "idi", "oun", "ami", "ira", "aoui", "ach"),
        ("Yanis", "Amine", "Riyad", "Nabil", "Karim", "Ilyes", "Walid", "Samir", "Adel", "Hakim"),
    ),
    Family(
        "pacific",
        ("Ka", "Ki", "Ma", "Na", "Ri", "Sa", "Ta", "To", "Ha", "Yo", "Mi", "Ku"),
        ("",),
        ("ra", "ki", "no", "to", "mi", "se"),
        ("mura", "kawa", "naga", "zaki", "moto", "hara", "shiro", "ta"),
        ("Haruto", "Ren", "Sota", "Yuto", "Kaito", "Riku", "Daichi", "Kenta", "Shun", "Taiga"),
    ),
)


def normalise(name: str) -> str:
    """Lower-case ASCII with single spaces, for blocklist comparison."""
    folded = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    return " ".join(folded.lower().replace("-", " ").replace(".", " ").split())


def name_hash(name: str) -> str:
    return hashlib.sha256(f"{BLOCKLIST_SALT}:{normalise(name)}".encode()).hexdigest()


def load_blocklist(path: Path = BLOCKLIST_PATH) -> frozenset[str]:
    """Hashes of real names. Empty when the blocklist hasn't been built yet."""
    if not path.exists():
        return frozenset()
    lines = path.read_text(encoding="utf-8").splitlines()
    return frozenset(line.strip() for line in lines if line.strip() and not line.startswith("#"))


def is_blocked(full_name: str, surname: str, blocklist: frozenset[str]) -> bool:
    return name_hash(full_name) in blocklist or name_hash(surname) in blocklist


class NameGenerator:
    def __init__(self, rng: np.random.Generator, blocklist: frozenset[str] | None = None) -> None:
        self.rng = rng
        self.blocklist = load_blocklist() if blocklist is None else blocklist
        self.used: set[str] = set()

    def _pick(self, options: tuple[str, ...]) -> str:
        return options[int(self.rng.integers(len(options)))]

    def surname(self, family: Family) -> str:
        parts = [self._pick(family.onsets), self._pick(family.vowels)]
        if self.rng.random() < 0.2:
            parts.append(self._pick(family.middles))
        parts.append(self._pick(family.endings))
        word = ""
        for part in parts:
            # Join syllables without vowel pile-ups: drop a vowel where two would meet.
            if word and part and word[-1] in VOWELS and part[0] in VOWELS:
                part = part[1:]
            word += part
        return word[0].upper() + word[1:].lower()

    def person(self, family: Family | None = None) -> tuple[str, str]:
        """(first name, surname), unique within this generator and not on the blocklist."""
        for _ in range(400):
            fam = family or FAMILIES[int(self.rng.integers(len(FAMILIES)))]
            first = self._pick(fam.first_names)
            last = self.surname(fam)
            full = f"{first} {last}"
            if not 4 <= len(last) <= 10 or last in self.used or is_blocked(full, last, self.blocklist):
                continue
            self.used.add(last)
            return first, last
        raise RuntimeError("Could not generate a unique, unblocked name")

    def reserve(self, surname: str) -> None:
        self.used.add(surname)
