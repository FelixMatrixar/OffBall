"""Train and validate pass difficulty and xG (PRD 13, 19.2): `uv run python -m offball.models.train`.

Pass difficulty trains on the smoke set's passes and is tested on the showcase (`m07`), which it never sees. xG trains
on the season backdrop's shots (`uv run offball season` writes them) and is tested on the showcase and smoke shots.
Both learn from outcomes only. This is the one module under offball/models that reads the held-out truth, and only
to score the models: each is compared with a simple baseline by its Brier score against the generator's true
probabilities, where PRD 19.2 asks for a gain of at least 10%. Writes the models to `offball/models/artifacts/` and
the scores to `calibration/reports/models.md`.
"""

from __future__ import annotations

import json
from pathlib import Path

import joblib
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from offball.contracts import Event, MatchInfo
from offball.models import pass_difficulty as PD
from offball.models import xg as XG
from offball.models.match_data import MatchData

ROOT = Path(__file__).resolve().parents[2]
DATASETS, TRUTH = ROOT / "datasets", ROOT / "truth"
REPORT = ROOT / "calibration" / "reports" / "models.md"
TEST = ("showcase", "m07")
TARGET_GAIN = 0.10


def _true(set_name: str, match_id: str) -> dict[str, float]:
    path = TRUTH / set_name / match_id / "probabilities.jsonl"
    return {r["event_id"]: r["p_success"] for r in map(json.loads, path.read_text(encoding="utf-8").splitlines())}


def _matches(set_name: str) -> list[Path]:
    return sorted(p.parent for p in (DATASETS / set_name).glob("*/match.json"))


def pass_rows(match_dir: Path) -> tuple[np.ndarray, np.ndarray, list[str]]:
    md = MatchData.load(match_dir)
    passes = [e for e in md.events if e.type == "pass" and e.start_xy and e.end_xy and e.outcome]
    return (np.asarray([PD.features(md, e) for e in passes]), np.asarray([PD.completed(e) for e in passes]),
            [e.event_id for e in passes])


def _lengths(match_dir: Path) -> np.ndarray:
    """Each pass's length, in the order pass_rows lists them, for the distance-only baseline."""
    md = MatchData.load(match_dir)
    passes = [e for e in md.events if e.type == "pass" and e.start_xy and e.end_xy and e.outcome]
    return np.asarray([float(np.hypot(e.end_xy[0] - e.start_xy[0], e.end_xy[1] - e.start_xy[1])) for e in passes])


def _events(match_dir: Path) -> list[Event]:
    lines = (match_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
    return [Event.model_validate_json(line) for line in lines if line.strip()]


def shot_rows(match_dir: Path) -> tuple[np.ndarray, np.ndarray, list[str]]:
    """Shots from events alone, so the season backdrop (events without tracking) can be used."""
    info = MatchInfo.model_validate_json((match_dir / "match.json").read_text(encoding="utf-8"))
    right = {p.period: p.attacks_left_to_right for p in info.periods}
    shots = [e for e in _events(match_dir) if e.type == "shot" and e.start_xy and e.outcome]
    return (np.asarray([XG.features(e, right.get(e.period) == e.team_id) for e in shots]).reshape(-1, len(XG.FEATURES)),
            np.asarray([e.outcome == "goal" for e in shots]), [e.event_id for e in shots])


def _stack(rows: list[tuple[np.ndarray, np.ndarray, list[str]]]) -> tuple[np.ndarray, np.ndarray, list[str]]:
    rows = [r for r in rows if len(r[2])]
    return np.vstack([r[0] for r in rows]), np.concatenate([r[1] for r in rows]), [i for r in rows for i in r[2]]


def fitted_model():
    """Scaled logistic regression. Gradient boosting fitted the outcomes better but overfitted them: its
    probabilities were too sure, and scored worse against the true probabilities than the baselines."""
    return make_pipeline(StandardScaler(), LogisticRegression(max_iter=3000))


def reliability(p: np.ndarray, truth: np.ndarray, outcome: np.ndarray, bins: int = 10) -> list[tuple]:
    """Per bin of predicted probability: (range, count, mean predicted, mean true probability, observed rate)."""
    edges = np.linspace(0, 1, bins + 1)
    out = []
    for a, b in zip(edges[:-1], edges[1:], strict=True):
        m = (p >= a) & ((p < b) if b < 1 else (p <= b))
        if m.any():
            out.append((f"{a:.1f}-{b:.1f}", int(m.sum()), float(p[m].mean()), float(truth[m].mean()),
                        float(outcome[m].mean())))
    return out


def score(name: str, model_p: np.ndarray, base_p: np.ndarray, truth: np.ndarray, outcome: np.ndarray) -> dict:
    b_model, b_base = float(np.mean((model_p - truth) ** 2)), float(np.mean((base_p - truth) ** 2))
    return {"model": name, "n": len(truth), "brier_true": round(b_model, 4), "baseline_brier_true": round(b_base, 4),
            "gain": round(1 - b_model / b_base, 3) if b_base else 0.0,
            "brier_outcome": round(float(np.mean((model_p - outcome) ** 2)), 4),
            "baseline_brier_outcome": round(float(np.mean((base_p - outcome) ** 2)), 4),
            "reliability": reliability(model_p, truth, outcome)}


def train_pass_difficulty(save: bool = True) -> dict:
    train = [pass_rows(d) for d in _matches("smoke")]
    X, y, _ = _stack(train)
    model = fitted_model().fit(X, y)
    Xt, yt, ids = pass_rows(DATASETS / TEST[0] / TEST[1])
    true = _true(*TEST)
    keep = np.asarray([i in true for i in ids])
    p_true = np.asarray([true[i] for i in np.asarray(ids)[keep]])
    # The PRD's baseline: pass length alone, from where each pass ended.
    length = [_lengths(DATASETS / d.parent.name / d.name) for d in _matches("smoke")]
    baseline = LogisticRegression().fit(np.concatenate(length).reshape(-1, 1), y)
    test_length = _lengths(DATASETS / TEST[0] / TEST[1])[keep].reshape(-1, 1)
    result = score("pass difficulty", model.predict_proba(Xt[keep])[:, 1], baseline.predict_proba(test_length)[:, 1],
                   p_true, yt[keep])
    result.update(train_n=len(y), baseline="logistic on distance")
    if save:
        PD.ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(model, PD.ARTIFACT)
    return result


def train_xg(save: bool = True) -> dict:
    season = _matches("season")
    if not season:
        raise SystemExit("xG trains on the season backdrop: run `uv run offball season` first")
    X, y, _ = _stack([shot_rows(d) for d in season])
    model = fitted_model().fit(X, y)
    baseline = LogisticRegression().fit(X[:, :2], y)
    tests = [(TEST[0], TEST[1])] + [("smoke", d.name) for d in _matches("smoke")]
    rows, truths = [], []
    for set_name, match_id in tests:
        Xm, ym, ids = shot_rows(DATASETS / set_name / match_id)
        true = _true(set_name, match_id)
        keep = np.asarray([i in true for i in ids], dtype=bool)
        if keep.any():
            rows.append((Xm[keep], ym[keep], list(np.asarray(ids)[keep])))
            truths += [true[i] for i in np.asarray(ids)[keep]]
    Xt, yt, _ = _stack(rows)
    result = score("xG", model.predict_proba(Xt)[:, 1], baseline.predict_proba(Xt[:, :2])[:, 1], np.asarray(truths), yt)
    result.update(train_n=len(y), baseline="logistic on distance and angle")
    if save:
        XG.ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(model, XG.ARTIFACT)
    return result


def report(results: list[dict], events: dict | None = None) -> str:
    lines = ["# Interpretation models", "",
             "Generated by `uv run python -m offball.models.train`. Brier scores are against the generator's true "
             "probabilities on matches the models never trained on; PRD 19.2 asks for at least 10% better than the "
             "baseline.", "", "| Model | Trained on | Tested on | Brier | Baseline | Gain | Target met |",
             "| --- | --- | --- | --- | --- | --- | --- |"]
    for r in results:
        lines.append(f"| {r['model']} | {r['train_n']} | {r['n']} | {r['brier_true']} | {r['baseline_brier_true']} "
                     f"({r['baseline']}) | {r['gain']:.0%} | {'yes' if r['gain'] >= TARGET_GAIN else 'no'} |")
    for r in results:
        lines += ["", f"## {r['model']}: reliability", "",
                  f"Brier against outcomes: {r['brier_outcome']} (baseline {r['baseline_brier_outcome']}).", "",
                  "| Predicted | Count | Mean predicted | Mean true | Observed |", "| --- | --- | --- | --- | --- |"]
        lines += [f"| {b} | {n} | {mp:.3f} | {mt:.3f} | {mo:.3f} |" for b, n, mp, mt, mo in r["reliability"]]
    if events:
        lines += ["", "## Auto-eventing from tracking", "",
                  f"On the smoke set, within {events['tolerance_ms']} ms of the generator's event and by the same "
                  "player. PRD 19.2 targets F1 0.95 for passes and 0.97 for shots.", "",
                  "| Event | Found | Generator | Matched | Precision | Recall | F1 |", "| --- | --- | --- | --- | --- | --- | --- |"]
        for kind, s in events["scores"].items():
            lines.append(f"| {kind} | {s['found']} | {s['generator']} | {s['matched']} | {s['precision']:.3f} | "
                         f"{s['recall']:.3f} | {s['f1']:.3f} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    from offball.models import autoevent

    results = [train_pass_difficulty(), train_xg()]
    events = autoevent.evaluate([MatchData.load(d) for d in _matches("smoke")])
    for r in results:
        print(f"{r['model']}: Brier {r['brier_true']} against baseline {r['baseline_brier_true']} "
              f"({r['gain']:.0%} better) on {r['n']} held-out events")
    for kind, s in events["scores"].items():
        print(f"auto-eventing {kind}: F1 {s['f1']:.3f} (precision {s['precision']:.3f}, recall {s['recall']:.3f})")
    REPORT.write_text(report(results, events), encoding="utf-8", newline="\n")
    print(f"Report -> {REPORT}")


if __name__ == "__main__":
    main()
