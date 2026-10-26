"""Pass difficulty, xG and auto-eventing (PRD 13): in range, deterministic, served through the metric registry, and
scored against their baselines on matches they never trained on (PRD 19.2)."""

from __future__ import annotations

from pathlib import Path

import pytest

from offball.mcp import tools as T
from offball.models import autoevent, metrics, train
from offball.models import xg as XG
from offball.models.match_data import MatchData

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def md() -> MatchData:
    return T.REGISTRY.data("m07")


def test_both_models_are_metrics_in_range(md) -> None:
    shot = next(e for e in md.events if e.type == "shot" and e.outcome == "goal")
    passes = [e for e in md.events if e.type == "pass" and e.start_xy and e.end_xy][:50]
    xg = metrics.compute(md, "xg", event_id=shot.event_id)
    assert 0 < xg.value < 1 and xg.unit == "xG" and xg.evidence_ids == [shot.event_id]
    for e in passes:
        r = metrics.compute(md, "pass_difficulty", event_id=e.event_id)
        assert 0 <= r.value <= 10 and 0 <= r.details["p_complete"] <= 1
    assert {"xg", "pass_difficulty"} <= {m["name"] for m in metrics.catalogue()}


def test_closer_and_more_central_shots_are_likelier(md) -> None:
    near, far, wide = XG.geometry(99, 34), XG.geometry(80, 34), XG.geometry(99, 60)
    assert near[1] > far[1] > 0 and near[1] > wide[1]
    model = XG.model()
    p = model.predict_proba([[*near, 0, 0, 0, 0], [*far, 0, 0, 0, 0]])[:, 1]
    assert p[0] > p[1]


def test_pass_difficulty_beats_its_baseline_on_held_out_passes() -> None:
    result = train.train_pass_difficulty(save=False)
    assert result["n"] > 800 and result["gain"] >= train.TARGET_GAIN, result
    assert result["brier_true"] < result["baseline_brier_true"]


def test_auto_eventing_finds_most_passes_and_shots() -> None:
    matches = [MatchData.load(ROOT / "datasets" / "smoke" / m) for m in ("smk1", "smk2", "smk3")]
    scores = autoevent.evaluate(matches)["scores"]
    assert scores["pass"]["recall"] > 0.8 and scores["pass"]["precision"] > 0.7
    assert scores["shot"]["f1"] > 0.6
    found = autoevent.detect_events(matches[0])
    assert found == autoevent.detect_events(matches[0]), "deterministic"


def test_training_is_deterministic() -> None:
    X, y, _ = train._stack([train.pass_rows(d) for d in train._matches("smoke")[:3]])
    a = train.fitted_model().fit(X, y).predict_proba(X[:20])[:, 1]
    b = train.fitted_model().fit(X, y).predict_proba(X[:20])[:, 1]
    assert (a == b).all()
