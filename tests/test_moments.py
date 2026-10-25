"""The moment library and the engine underneath it (PRD 12.4, 12.7)."""

from __future__ import annotations

from offball.calibration.metrics import match_metrics
from offball.generator.director import EXPECTED
from offball.generator.engine.params import EngineParams
from offball.generator.engine.sim import Simulator
from offball.generator.league import build_league
from offball.generator.moments import PLANS
from offball.models.candidates import DETECTORS


def test_every_planted_type_has_signals_and_a_detector() -> None:
    from offball.contracts.truth import MOMENT_TYPES

    assert set(PLANS) == set(MOMENT_TYPES), "every moment type in the contracts has a plan"
    for kind, plan in PLANS.items():
        assert kind in EXPECTED, f"{kind} has no expected signals for the answer key"
        base = kind.removeprefix("null_")
        base = "decoy_run" if base == "run" else base
        assert base in DETECTORS, f"nothing can find {kind} from the data alone"
        assert plan.is_null == kind.startswith("null_")


def test_a_short_match_has_stoppages_and_a_sane_speed_profile() -> None:
    sim = Simulator(build_league(2026), "kes", "ash", "t-short", seed=3, half_minutes=3, params=EngineParams.load())
    m = match_metrics(sim.play())
    assert m["passes"] > 0
    assert 0.3 < m["in_play_share"] < 0.95
    assert 0.0 <= m["sprint_share"] <= m["hsr_share"] < 0.5
    assert m["running_share"] > 0.0


def test_the_engine_is_deterministic() -> None:
    league = build_league(2026)

    def events() -> list[tuple]:
        sim = Simulator(league, "nor", "oak", "t-det", seed=11, half_minutes=1, params=EngineParams.load())
        return [(e["type"], e["t_ms"], e["player_id"]) for e in sim.play().events]

    assert events() == events()


def test_the_fast_engine_plays_a_realistic_match_quickly() -> None:
    import time

    from offball.generator.fast import FastEngine

    league = build_league(2026)
    engine = FastEngine(league)
    t0 = time.time()
    info, events = engine.play("kes", "ash", "fast-test", seed=5)
    assert time.time() - t0 < 5.0
    passes = [e for e in events if e.type == "pass"]
    shots = [e for e in events if e.type == "shot"]
    assert info.engine == "fast"
    assert 600 < len(passes) < 1300
    assert 8 < len(shots) < 45
    assert sum(e.outcome == "goal" for e in shots) == sum(info.final_score.values())
    assert engine.play("kes", "ash", "fast-test", seed=5)[1] == events  # deterministic
