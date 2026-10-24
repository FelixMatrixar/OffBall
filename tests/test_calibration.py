"""Calibration against real data: fitted targets, realism metrics, the blocklist and the quality gates
(PRD 12.1, 12.6, 12.10)."""

from __future__ import annotations

import json

import numpy as np
import pytest

from offball.calibration.gates import (
    gate_consistency,
    gate_detectability,
    gate_determinism,
    ks_against,
    load_set,
)
from offball.calibration.metrics import (
    TARGETS_PATH,
    Target,
    dead_seconds,
    deviation,
    fitted,
    loss,
    robust_peak,
    targets,
)
from offball.core import HZ
from offball.generator.names import BLOCKLIST_PATH, is_blocked, load_blocklist, normalise

from .conftest import ROOT


def test_targets_come_from_the_fit() -> None:
    fit = fitted()
    assert fit["matches"] >= 300
    bands = targets()
    for name in ("passes", "shots", "possessions", "km_per_outfield", "hsr_share", "running_share", "sprint_share",
                 "in_play_share"):
        assert bands[name].lo < bands[name].hi
        assert bands[name].source != "norm", f"{name} should be fitted, not a norm"
    # A shot's true xG should average out to the league's conversion rate.
    conversion = fit["match"]["goals_per_shot"]["mean"]
    assert bands["xg_per_shot"].lo < conversion < bands["xg_per_shot"].hi


def test_the_fit_keeps_numbers_only() -> None:
    """Raw calibration data never enters the repository: the targets file holds numbers and source labels."""
    fit = json.loads(TARGETS_PATH.read_text(encoding="utf-8"))
    strings: set[str] = set()

    def walk(node: object) -> None:
        if isinstance(node, dict):
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
        elif isinstance(node, str):
            strings.add(node)

    walk(fit)
    sources = {s for s in strings if "Wyscout" in s or "SkillCorner" in s}
    assert strings - sources == {fit["fitted"]}


def test_deviation_and_loss() -> None:
    band = Target(10, 20, 2.0, "test")
    assert deviation(15, band) == 0
    assert deviation(25, band) == pytest.approx(0.5)
    assert deviation(5, band) == pytest.approx(0.5)
    assert loss({"x": 25}, {"x": band}) == pytest.approx(0.5)


def test_peak_speed_ignores_a_tracking_glitch() -> None:
    speeds = np.full(HZ * 60, 5.0)
    speeds[100] = 40.0
    assert robust_peak(speeds) == pytest.approx(5.0)
    speeds[200 : 200 + HZ] = 8.0  # held for a second: a real peak
    assert robust_peak(speeds) == pytest.approx(8.0)


def test_dead_time_runs_from_the_stoppage_to_the_restart() -> None:
    events = [
        {"period": 1, "t_ms": 1_000, "type": "pass", "subtype": "kick_off"},
        {"period": 1, "t_ms": 10_000, "type": "ball_out", "subtype": "touchline"},
        {"period": 1, "t_ms": 12_000, "type": "card", "subtype": "yellow"},
        {"period": 1, "t_ms": 22_000, "type": "pass", "subtype": "throw_in"},
        {"period": 1, "t_ms": 30_000, "type": "shot", "subtype": "open_play", "outcome": "goal"},
        {"period": 1, "t_ms": 90_000, "type": "pass", "subtype": "kick_off"},
        {"period": 2, "t_ms": 5_000, "type": "foul", "subtype": None},  # never restarted: not counted
    ]
    assert dead_seconds(events) == pytest.approx(12 + 60)


def test_ks_against_quantiles() -> None:
    uniform = list(np.linspace(0, 100, 101))
    rng = np.random.default_rng(0)
    assert ks_against(rng.uniform(0, 100, 4000), uniform) < 0.05
    assert ks_against(rng.uniform(30, 130, 4000), uniform) > 0.25


def test_blocklist_is_hashed_and_no_generated_name_is_on_it() -> None:
    blocklist = load_blocklist()
    assert len(blocklist) > 500
    assert all(len(h) == 64 for h in blocklist)
    text = BLOCKLIST_PATH.read_text(encoding="utf-8")
    league = json.loads((ROOT / "datasets" / "league" / "league.json").read_text(encoding="utf-8"))
    for club in league["clubs"]:
        assert not is_blocked(club["name"], club["name"], blocklist)
        for p in club["squad"]:
            assert not is_blocked(p["name"], p["name"].split()[-1], blocklist)
            assert normalise(p["name"]) not in text  # hashes only, never names in plain text


def test_showcase_files_are_consistent_and_unchanged() -> None:
    matches = load_set("showcase")
    assert gate_consistency(matches).status == "pass"
    assert gate_determinism(matches).status == "pass"


def test_every_planted_smoke_moment_is_found_and_no_null_is_credited() -> None:
    gate = gate_detectability(load_set("smoke"))
    assert gate.status == "pass", gate.summary
    assert gate.numbers["invented"] == 0
