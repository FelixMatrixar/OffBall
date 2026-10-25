"""The generated showcase and the UI it plays in agree (PRD 11.9): the same match, clubs, roster, roles and attacking
direction, and the decoy-run goal on the UI's clock and beats. The UI's side is read from its own source,
`web/src/lib/match.ts`, by Node, so neither side keeps a copy of the other's numbers."""

from __future__ import annotations

import json
import shutil
import subprocess

import numpy as np
import pytest

from offball.generator.director import SHOWCASE_BEATS, SHOWCASE_T0_S
from offball.models.match_data import MatchData
from offball.models.metrics import moment_beats

from .conftest import M07, ROOT

MATCH_TS = ROOT / "web" / "src" / "lib" / "match.ts"
ANSWER_KEY = ROOT / "truth" / "showcase" / "m07" / "answer_key.json"
TOLERANCE_S = 0.3
READ_UI = (
    "import(process.argv[1]).then(m => console.log(JSON.stringify({id: m.MATCH_ID, period: m.PERIOD, base: m.BASE_MS,"
    " end: m.T_END, steps: m.STEP_TIMES, goal: m.T_GOAL, clubs: m.CLUBS,"
    " players: m.PLAYERS.map(p => ({id: p.id, team: p.team, num: p.num, name: p.name, role: p.role}))})))"
)


@pytest.fixture(scope="module")
def ui() -> dict:
    node = shutil.which("node")
    assert node, "the parity check reads the UI's match.ts with Node 22.6 or later"
    out = subprocess.run([node, "--experimental-strip-types", "--no-warnings", "-e", READ_UI, MATCH_TS.as_uri()],
                         capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


@pytest.fixture(scope="module")
def md() -> MatchData:
    return MatchData.load(M07)


@pytest.fixture(scope="module")
def goal(ui: dict) -> dict:
    """The answer key's decoy-run goal in the UI's period."""
    rows = [r for r in json.loads(ANSWER_KEY.read_text(encoding="utf-8"))
            if r["type"] == "decoy_run" and r["period"] == ui["period"] and r.get("outcome") == "goal"]
    assert len(rows) == 1, f"expected one decoy-run goal in period {ui['period']}, found {len(rows)}"
    return rows[0]


def beats(ui: dict) -> dict[str, float]:
    """The UI's beats by name (INTEGRATION.md section 2): STEP_TIMES after the build-up, then the goal."""
    run, follow, gap, pass_, shot = ui["steps"][1:]
    return {"run": run, "follow": follow, "gap": gap, "pass": pass_, "shot": shot, "goal": ui["goal"]}


def test_the_generator_aims_at_the_uis_moment(ui: dict) -> None:
    assert ui["base"] == SHOWCASE_T0_S * 1000
    assert beats(ui) == SHOWCASE_BEATS


def test_the_match_and_clubs_are_the_uis(md: MatchData, ui: dict) -> None:
    assert md.match_id == ui["id"]
    assert {md.home: md.club_name(md.home), md.away: md.club_name(md.away)} == {
        club: c["name"] for club, c in ui["clubs"].items()}


def test_every_ui_player_starts_with_the_uis_number_name_and_role(md: MatchData, ui: dict) -> None:
    lineup = {e.player_id: e for sheet in (md.info.home, md.info.away) for e in sheet.lineup}
    for p in ui["players"]:
        e = lineup.get(p["id"])
        assert e is not None, f"{p['id']} is not in the generated lineup"
        assert (e.number, e.name, e.role, e.starter) == (p["num"], p["name"], p["role"], True), p["id"]


def test_kestrel_bay_attack_left_to_right_in_the_moments_period(md: MatchData, ui: dict) -> None:
    assert md.direction(ui["period"], "kes") == 1


def test_the_goal_is_velmars_run_hendricxs_follow_and_arkwells_finish(goal: dict) -> None:
    assert (goal["team_id"], goal["creator_id"], goal["dragged_ids"], goal["receiver_id"]) == (
        "kes", "kes-09", ["ash-05"], "kes-10")


def test_the_goal_lands_on_the_uis_beats(md: MatchData, ui: dict, goal: dict) -> None:
    """Every beat, read from the data the UI is sent."""
    got = moment_beats(md, goal["period"], goal["team_id"], goal["t_start_ms"], goal["dragged_ids"][0],
                       goal["receiver_id"], goal["gap_zone"])
    for beat, want in beats(ui).items():
        at = got[beat]
        assert at is not None, f"no {beat} beat in the data"
        seconds = (at - ui["base"]) / 1000
        assert abs(seconds - want) <= TOLERANCE_S, f"{beat}: {seconds} s, the UI has {want} s"


def test_the_score_is_level_until_the_goal(md: MatchData, ui: dict) -> None:
    before = [e for e in md.events if e.type == "shot" and e.outcome == "goal"
              and (e.period < ui["period"] or (e.period == ui["period"] and e.t_ms < ui["base"]))]
    assert not before, "the UI shows 0-0 at 63:00"


def test_everyone_on_the_pitch_during_the_moment_is_a_ui_player(md: MatchData, ui: dict) -> None:
    pf = md.periods[ui["period"]]
    span = slice(pf.index_of(ui["base"]), pf.index_of(ui["base"] + int(ui["end"] * 1000)) + 1)
    on_pitch = {md.players[k] for k in np.nonzero(np.isfinite(pf.xy[span, :, 0]).any(axis=0))[0]}
    assert on_pitch == {p["id"] for p in ui["players"]}
