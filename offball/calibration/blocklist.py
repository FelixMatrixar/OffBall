"""Building the real-name blocklist (PRD 12.1, gate 7).

Reads player, club, coach, referee and stadium names from the downloaded calibration sources and writes them
only as salted SHA-256 hashes, so no real name is ever stored in the repository. The name generator refuses
any name on the list, and gate 7 checks every generated name against it.

    uv run offball blocklist
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from offball.generator.names import BLOCKLIST_PATH, name_hash, normalise

RAW = Path(__file__).resolve().parents[2] / "calibration" / "raw"


def _person(first: str | None, last: str | None) -> list[str]:
    first, last = (first or "").strip(), (last or "").strip()
    out = [f"{first} {last}".strip(), last]
    if last:
        out.append(last.split()[-1])  # the surname alone, as a generated "E. Surname" would show it
    return [n for n in out if n]


def real_names(raw: Path = RAW) -> set[str]:
    names: set[str] = set()
    agg = raw / "skillcorner" / "aggregates"
    for path in agg.glob("*.csv"):
        with path.open(encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                for key in ("player_name", "team_name"):
                    if row.get(key):
                        names.add(row[key])
                short = row.get("player_short_name") or ""
                if "." in short:
                    names.add(short.split(".", 1)[1])
    for path in (raw / "skillcorner" / "matches").glob("*/*_match.json"):
        m = json.loads(path.read_text(encoding="utf-8"))
        for p in m.get("players", []) + m.get("referees", []):
            names.update(_person(p.get("first_name"), p.get("last_name")))
        for side in ("home_team", "away_team"):
            team = m.get(side) or {}
            names.update(v for k, v in team.items() if k in ("name", "short_name") and v)
            coach = m.get(f"{side}_coach") or {}
            names.update(_person(coach.get("first_name"), coach.get("last_name")))
        stadium = m.get("stadium") or {}
        if stadium.get("name"):
            names.add(stadium["name"])
    return {n for n in names if len(normalise(n)) >= 3}


def build(raw: Path = RAW, path: Path = BLOCKLIST_PATH) -> int:
    hashes = sorted({name_hash(n) for n in real_names(raw)})
    header = "# Salted SHA-256 hashes of real names from the calibration sources (PRD 12.1). No names in plain text.\n"
    path.write_text(header + "\n".join(hashes) + "\n", encoding="utf-8")
    return len(hashes)


if __name__ == "__main__":
    print(f"{build()} hashes -> {BLOCKLIST_PATH}")
