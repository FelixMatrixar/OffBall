"""Train and validate the interpretation models (PRD 13, 19.2): `uv run python -m offball.models.train`.

Pass difficulty trains on the smoke set's passes and is tested on the showcase (`m07`), which it never sees. xG trains
on the season backdrop's shots (`uv run offball season` writes them) and is tested on the showcase and smoke shots.
Both learn from outcomes only, and each is compared with a simple baseline by its Brier score against the
generator's true probabilities, where PRD 19.2 asks for a gain of at least 10%.

The M5 models train on the calibration matches (`uv run offball calib` writes them) and are tested on the matchday,
smoke and showcase matches, which they never see. Space value learns from events and is scored by its calibration
against realized possession outcomes; off-ball scoring opportunity fits its transition kernel to passes and is
scored on whether shots follow; the run classifier learns the calibration matches' oracle intents (the training
split, PRD 12.9) and is scored by macro-F1 on the others' intents; off-ball credit learns nothing and is scored
against the true counterfactual credit of every planted moment.

This is the one module under offball/models that reads the held-out truth, and only to train on the training split
and to score. Writes the models to `offball/models/artifacts/` and the scores to `calibration/reports/models.md`.
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
from offball.models import credit as CR
from offball.models import epv as EPV
from offball.models import obso as OBSO
from offball.models import pass_difficulty as PD
from offball.models import runclass as RC
from offball.models import xg as XG
from offball.models.match_data import MatchData
from offball.models.runs import Possession, detect_runs

ROOT = Path(__file__).resolve().parents[2]
DATASETS, TRUTH = ROOT / "datasets", ROOT / "truth"
REPORT = ROOT / "calibration" / "reports" / "models.md"
TEST = ("showcase", "m07")
TARGET_GAIN = 0.10
M5_TRAIN = "calib"
M5_TEST = (("matchday", None), ("smoke", None), ("showcase", "m07"))
ECE_TARGET = 0.02
F1_TARGET = 0.80
CREDIT_TOLERANCE, CREDIT_SHARE, CREDIT_RANK = 0.25, 0.80, 0.80
OBSO_STEP_MS, OBSO_HORIZON_MS, OBSO_LEAD_MS = 4000, 10000, 2000
# The moment types whose creator's decision is an off-ball run: what the observed-tracking credit estimates. The
# others (a switch, a broken press, a pin, a fatigue gap) change something else, which the engine re-runs measure.
OFF_BALL_RUNS = {"decoy_run", "overlap", "underlap", "third_man_run", "blind_side_run", "timed_run_in_behind",
                 "false_9_drop"}


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


# ------------------------------------------------------------------------------------------------ M5 models


def _m5_test_dirs() -> list[tuple[str, Path]]:
    dirs = []
    for set_name, only in M5_TEST:
        dirs += [(set_name, d) for d in _matches(set_name) if only is None or d.name == only]
    return dirs


def ece(pred: np.ndarray, outcome: np.ndarray, bins: int = 10) -> tuple[float, list[tuple]]:
    """Expected calibration error over bins of equal count: the count-weighted gap between mean prediction and
    the observed rate. Returns it with the bins (count, mean predicted, observed)."""
    order = np.argsort(pred, kind="stable")
    out, err = [], 0.0
    for part in np.array_split(order, bins):
        if len(part):
            mp, mo = float(pred[part].mean()), float(outcome[part].mean())
            err += len(part) / len(pred) * abs(mp - mo)
            out.append((len(part), mp, mo))
    return err, out


def possession_rows(md: MatchData, surface: EPV.Surface) -> tuple[np.ndarray, np.ndarray]:
    """Each on-ball action's space value, and whether its possession ended in a goal for the club that had it."""
    owner: dict[str, str] = {}
    for e in md.events:
        if e.possession_id and e.team_id and e.type in ("pass", "carry", "shot") and e.possession_id not in owner:
            owner[e.possession_id] = e.team_id
    scored = {e.possession_id for e in md.events if e.type == "shot" and e.outcome == "goal" and e.possession_id
              and owner.get(e.possession_id) == e.team_id}
    pred, outcome = [], []
    for e in md.events:
        if e.type in ("pass", "carry", "shot") and e.start_xy and e.possession_id and owner.get(e.possession_id) == e.team_id:
            x, y = EPV.team_xy(md, e, e.start_xy)
            pred.append(float(surface.at(x, y)))
            outcome.append(e.possession_id in scored)
    return np.asarray(pred), np.asarray(outcome, dtype=float)


def train_epv(train: list[MatchData], tests: list[MatchData], save: bool = True) -> dict:
    counts = EPV.Counts.empty()
    for md in train:
        counts.add(md, XG.probability)
    centres = EPV.zone_centres()
    centre_xg = XG.model().predict_proba(np.asarray([[*XG.geometry(float(x), float(y)), 0.0, 0.0, 0.0, 0.0]
                                                     for x, y in centres]))[:, 1]
    surface = EPV.solve(counts, centre_xg)
    rows = [possession_rows(md, surface) for md in tests]
    pred, outcome = np.concatenate([r[0] for r in rows]), np.concatenate([r[1] for r in rows])
    err, bins = ece(pred, outcome)
    base = np.full_like(pred, outcome.mean())
    if save:
        EPV.save(surface)
    return {"model": "space value", "train_actions": int(counts.shots.sum() + sum(m.sum() for m in counts.moves.values())),
            "n": len(pred), "ece": round(err, 4), "brier": round(float(np.mean((pred - outcome) ** 2)), 5),
            "baseline_brier": round(float(np.mean((base - outcome) ** 2)), 5), "goal_rate": round(float(outcome.mean()), 4),
            "bins": bins, "value_range": (round(float(surface.value.min()), 4), round(float(surface.value.max()), 4))}


def _goal_distance(md: MatchData, period: int, club: str, xy: np.ndarray) -> float:
    t = md.to_team(period, club, xy)
    return float(np.hypot(105.0 - t[0], 34.0 - t[1]))


def eval_obso(train: list[MatchData], tests: list[MatchData], save: bool = True) -> dict:
    from sklearn.metrics import roc_auc_score

    sigma = OBSO.fit_sigma(train)
    if save:
        OBSO.ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
        OBSO.ARTIFACT.write_text(json.dumps({"sigma_m": round(sigma, 2), "trained_on": M5_TRAIN}) + "\n", encoding="utf-8")
    OBSO.transition_sigma.cache_clear()
    totals, baseline, follows = [], [], []
    shooters = top_hits = near_hits = 0
    for md in tests:
        poss = Possession(md)
        for period, pf in md.periods.items():
            shots = [e for e in md.events if e.period == period and e.type == "shot" and e.team_id]
            for t in range(int(pf.t_ms[0]), int(pf.t_ms[-1]) - OBSO_HORIZON_MS, OBSO_STEP_MS):
                club, i = poss.at(period, t), pf.index_of(t)
                if club is None or np.isnan(pf.ball[i, :2]).any():
                    continue
                totals.append(sum(OBSO.by_player(md, period, i, club).values()))
                baseline.append(-_goal_distance(md, period, club, pf.ball[i, :2].astype(float)))
                follows.append(any(s.team_id == club and t < s.t_ms <= t + OBSO_HORIZON_MS for s in shots))
            # Was each shooter the attacker the model rated highest just before the shot?
            for s in shots:
                i = pf.index_of(s.t_ms - OBSO_LEAD_MS)
                if np.isnan(pf.ball[i, :2]).any() or s.player_id is None:
                    continue
                values = OBSO.by_player(md, period, i, s.team_id)
                if s.player_id not in values:
                    continue
                shooters += 1
                top_hits += max(values, key=values.get) == s.player_id
                cols = [c for c in md.columns_of(s.team_id) if not np.isnan(pf.xy[i, c, 0])]
                nearest = min(cols, key=lambda c: _goal_distance(md, period, s.team_id, pf.xy[i, c].astype(float)))
                near_hits += md.players[nearest] == s.player_id
    y = np.asarray(follows)
    return {"model": "off-ball scoring opportunity", "sigma_m": round(sigma, 2), "frames": len(y),
            "shot_rate": round(float(y.mean()), 3), "auc": round(float(roc_auc_score(y, totals)), 3),
            "baseline_auc": round(float(roc_auc_score(y, baseline)), 3), "shots": shooters,
            "top_is_shooter": round(top_hits / max(shooters, 1), 3),
            "baseline_top_is_shooter": round(near_hits / max(shooters, 1), 3)}


def eval_credit() -> dict:
    from scipy.stats import spearmanr

    rows, cache, seen = [], {}, set()
    for set_name in ("smoke", "matchday", "showcase", "golden"):
        for key in sorted((TRUTH / set_name).glob("*/answer_key.json")):
            match_dir = DATASETS / set_name / key.parent.name
            if not (match_dir / "tracking.parquet").exists():
                continue
            for r in json.loads(key.read_text(encoding="utf-8")):
                cf = r.get("counterfactual")
                if r.get("is_null") or not cf or not r.get("creator_id") or not r.get("dragged_ids") or not r.get("gap_zone"):
                    continue
                if r["moment_id"] in seen:  # the golden cases repeat moments from the showcase
                    continue
                seen.add(r["moment_id"])
                md = cache.setdefault(match_dir, MatchData.load(match_dir))
                t_m = CR.measure_instant(md, r["team_id"], r["period"], r["t_start_ms"], r["t_end_ms"], r.get("receiver_id"))
                c = CR.credit(md, r["team_id"], r["creator_id"], r["dragged_ids"], r["period"], r["t_start_ms"], t_m,
                              r["gap_zone"])
                rows.append({"moment": r["moment_id"], "type": r["type"], "true_m2": cf["space_created_m2"],
                             "est_m2": round(c.space_created_m2, 1), "true_epv": cf["epv_gain"],
                             "est_epv": round(c.threat_created, 4)})
    def scores(group: list[dict]) -> dict:
        true = np.asarray([r["true_m2"] for r in group])
        est = np.asarray([r["est_m2"] for r in group])
        within = np.abs(est - true) <= CREDIT_TOLERANCE * np.abs(true)
        enough = len(group) > 2
        return {"n": len(group), "within": round(float(within.mean()), 3) if group else 0.0,
                "rank": round(float(spearmanr(true, est).statistic), 3) if enough else 0.0,
                "rank_epv": round(float(spearmanr([r["true_epv"] for r in group],
                                                  [r["est_epv"] for r in group]).statistic), 3) if enough else 0.0}

    runs = [r for r in rows if r["type"] in OFF_BALL_RUNS]
    return {"model": "off-ball credit", **scores(rows), "runs": scores(runs),
            "others": scores([r for r in rows if r["type"] not in OFF_BALL_RUNS]), "rows": rows}


def labelled_runs(set_name: str, match_dir: Path, md: MatchData) -> tuple[list, list[str]]:
    """The attacking runs the detector finds, with the run type of the oracle intent the runner held for most of
    the run (players re-decide every few hundred milliseconds, so one instant can mislabel a run)."""
    import bisect
    from collections import Counter

    intents: dict[tuple[str, int], list[tuple[int, str]]] = {}
    for line in (TRUTH / set_name / match_dir.name / "intents.jsonl").read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        intents.setdefault((r["player_id"], r["period"]), []).append((r["t_ms"], r["intent"]))
    poss = Possession(md)
    runs, labels = [], []
    for period in md.periods:
        for run in detect_runs(md, period):
            if poss.at(period, run.t0_ms) != run.club:
                continue
            seq = intents.get((run.player_id, period), [])
            times = [t for t, _ in seq]
            held = Counter()
            for t in range(run.t0_ms, run.t1_ms + 1, 200):
                k = bisect.bisect_right(times, t) - 1
                if k >= 0:
                    held[seq[k][1]] += 1
            kind = RC.INTENT_TYPE.get(held.most_common(1)[0][0]) if held else None
            if kind:
                runs.append(run)
                labels.append(kind)
    return runs, labels


def train_runclass(save: bool = True) -> dict:
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.metrics import confusion_matrix, f1_score

    def rows(set_name: str, dirs: list[Path]) -> tuple[np.ndarray, list[str]]:
        X, y = [], []
        for d in dirs:
            md = MatchData.load(d)
            runs, labels = labelled_runs(set_name, d, md)
            X += [RC.features(md, r) for r in runs]
            y += labels
        return np.asarray(X), y

    X, y = rows(M5_TRAIN, _matches(M5_TRAIN))
    model = HistGradientBoostingClassifier(learning_rate=0.05, max_iter=400, max_leaf_nodes=15,
                                           class_weight="balanced", random_state=0).fit(X, y)
    tests = [rows(s, [d]) for s, d in _m5_test_dirs()]
    Xt = np.vstack([t[0] for t in tests if len(t[1])])
    yt = [label for t in tests for label in t[1]]
    pred = model.predict(Xt)
    labels = [t for t in RC.TYPES if t in set(yt) | set(y)]
    if save:
        RC.ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(model, RC.ARTIFACT)
    per = f1_score(yt, pred, labels=labels, average=None, zero_division=0)
    return {"model": "run classifier", "train_n": len(y), "n": len(yt), "macro_f1": round(float(np.mean(per)), 3),
            "per_type": {t: round(float(f), 3) for t, f in zip(labels, per, strict=True)},
            "counts": {t: yt.count(t) for t in labels}, "labels": labels,
            "confusion": confusion_matrix(yt, pred, labels=labels).tolist()}


def train_m5(save: bool = True) -> list[dict]:
    train = [MatchData.load(d) for d in _matches(M5_TRAIN)]
    if not train:
        raise SystemExit("The M5 models train on the calibration matches: run `uv run offball calib` first")
    tests = [MatchData.load(d) for _, d in _m5_test_dirs()]
    epv = train_epv(train, tests, save)
    EPV.model.cache_clear()
    return [epv, eval_obso(train, [t for t in tests if t.match_id.startswith("s27")], save), eval_credit(),
            train_runclass(save)]


def m5_report(results: list[dict]) -> list[str]:
    epv, obso, cred, runs = results
    lines = ["", "## Space value", "",
             f"Trained on {epv['train_actions']} on-ball actions in the calibration matches; tested on {epv['n']} "
             f"actions in the matchday, smoke and showcase matches, against whether each possession ended in a goal "
             f"({epv['goal_rate']:.2%} did). Values run from {epv['value_range'][0]} to {epv['value_range'][1]}.", "",
             "| Expected calibration error | Target | Brier | Baseline (the goal rate) | Target met |",
             "| --- | --- | --- | --- | --- |",
             f"| {epv['ece']} | {ECE_TARGET} or less | {epv['brier']} | {epv['baseline_brier']} | "
             f"{'yes' if epv['ece'] <= ECE_TARGET else 'no'} |", "", "| Bin | Count | Mean predicted | Observed |",
             "| --- | --- | --- | --- |"]
    lines += [f"| {k + 1} | {n} | {mp:.4f} | {mo:.4f} |" for k, (n, mp, mo) in enumerate(epv["bins"])]
    lines += ["", "## Off-ball scoring opportunity", "",
              f"Transition kernel fitted to the calibration matches' passes: {obso['sigma_m']} m. On the matchday matches, "
              f"{obso['frames']} moments in possession every {OBSO_STEP_MS // 1000} s, {obso['shot_rate']:.1%} followed "
              f"by a shot within {OBSO_HORIZON_MS // 1000} s; and {obso['shots']} shots, {OBSO_LEAD_MS // 1000} s before.",
              "", "| Check | Model | Baseline |", "| --- | --- | --- |",
              f"| A shot follows within {OBSO_HORIZON_MS // 1000} s (ROC AUC) | {obso['auc']} | {obso['baseline_auc']} "
              "(the ball's distance from goal) |",
              f"| The shooter was rated highest | {obso['top_is_shooter']:.1%} | {obso['baseline_top_is_shooter']:.1%} "
              "(the attacker nearest goal) |"]
    lines += ["", "## Off-ball credit", "",
              f"Space Created against the generator's true counterfactual credit, on {cred['n']} planted moments. PRD 19.2 "
              f"asks for {CREDIT_SHARE:.0%} within {CREDIT_TOLERANCE:.0%} of the truth and a rank correlation of "
              f"{CREDIT_RANK}. The estimate reads observed tracking only; the engine re-runs of the counterfactual "
              "workers (ADR 0005) are what the target is set for, and are needed for moments whose creator's decision "
              "isn't an off-ball run.", "", "| Moments | Count | Within 25% | Rank correlation (space) | "
              "Rank correlation (threat) | Target met |", "| --- | --- | --- | --- | --- | --- |"]
    for name, s in (("All", cred), ("Off-ball runs", cred["runs"]), ("Others", cred["others"])):
        met = "yes" if s["within"] >= CREDIT_SHARE and s["rank"] >= CREDIT_RANK else "no"
        lines.append(f"| {name} | {s['n']} | {s['within']:.0%} | {s['rank']} | {s['rank_epv']} | {met} |")
    lines += ["", "| Moment | Type | True m² | Estimated m² | True threat | Estimated threat |",
              "| --- | --- | --- | --- | --- | --- |"]
    lines += [f"| {r['moment']} | {r['type']} | {r['true_m2']} | {r['est_m2']} | {r['true_epv']} | {r['est_epv']} |"
              for r in cred["rows"]]
    lines += ["", "## Run classifier", "",
              f"Trained on {runs['train_n']} labelled attacking runs in the calibration matches; tested on {runs['n']} in "
              f"the matchday, smoke and showcase matches. PRD 19.2 asks for macro-F1 {F1_TARGET}.", "",
              f"Macro-F1: **{runs['macro_f1']}** ({'met' if runs['macro_f1'] >= F1_TARGET else 'not met'}).", "",
              "| Type | Test runs | F1 |", "| --- | --- | --- |"]
    lines += [f"| {t} | {runs['counts'][t]} | {runs['per_type'][t]} |" for t in runs["labels"]]
    lines += ["", "Confusion (rows true, columns predicted): " + ", ".join(runs["labels"]), "",
              "| | " + " | ".join(runs["labels"]) + " |", "| --- |" + " --- |" * len(runs["labels"])]
    lines += [f"| {t} | " + " | ".join(str(v) for v in row) + " |" for t, row in zip(runs["labels"], runs["confusion"],
                                                                                    strict=True)]
    return lines


def report(results: list[dict], events: dict | None = None, m5: list[dict] | None = None) -> str:
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
    if m5:
        lines += m5_report(m5)
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
    m5 = train_m5()
    epv, obso, cred, runs = m5
    print(f"space value: ECE {epv['ece']} (target {ECE_TARGET}) on {epv['n']} held-out actions")
    print(f"scoring opportunity: AUC {obso['auc']} against {obso['baseline_auc']}; shooter rated highest "
          f"{obso['top_is_shooter']:.1%} against {obso['baseline_top_is_shooter']:.1%}")
    print(f"off-ball credit: {cred['within']:.0%} within 25%, rank correlation {cred['rank']} on {cred['n']} moments; "
          f"off-ball runs {cred['runs']['within']:.0%} and {cred['runs']['rank']} on {cred['runs']['n']}")
    print(f"run classifier: macro-F1 {runs['macro_f1']} on {runs['n']} held-out runs {runs['per_type']}")
    REPORT.write_text(report(results, events, m5), encoding="utf-8", newline="\n")
    print(f"Report -> {REPORT}")


if __name__ == "__main__":
    main()
