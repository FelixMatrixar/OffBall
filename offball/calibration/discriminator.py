"""Gate 5, the discriminator (PRD 12.10): can a model tell generated tracking from real broadcast tracking?

Real windows are 10 s of SkillCorner's A-League tracking at 10 Hz, using only the players the broadcast camera
saw. Generated windows are 10 s of our 10 Hz tracking, masked by a real camera footprint that follows our ball,
so both sides show only what a broadcast camera would. Each window becomes a vector of physical statistics,
and a gradient-boosted classifier, cross-validated by match, tries to tell them apart. The gate passes when its
ROC AUC on held-out matches is at most 0.65.

Ball height is left out of the features: SkillCorner estimates it from broadcast video (about 0.3 m on average
even on the ground), while ours is exact, so it would separate the sources by measurement, not by football.

The raw SkillCorner files stay in the git-ignored `calibration/raw/`; nothing from them is written elsewhere.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

RAW = Path(__file__).resolve().parents[2] / "calibration" / "raw" / "skillcorner" / "matches"
CACHE = RAW.parent / "cache"
HZ = 10
WINDOW = 10 * HZ  # 10 s
STEP = 5 * HZ  # windows start every 5 s
MIN_SEEN = 8  # players the camera must see in a frame for it to count
FEATURES = [
    "players_seen", "speed_mean", "speed_p50", "speed_p90", "speed_max", "accel_mean", "accel_p90",
    "hsr_share", "sprint_share", "turn_mean", "nn_team_mean", "nn_opp_mean", "spread_x", "spread_y",
    "ball_speed_mean", "ball_speed_p90",
]
# The features that told our tracking from real tracking most clearly; calibration tunes against their real bands.
TRACKING_FEATURES = ("accel_p90", "accel_mean", "players_seen", "nn_team_mean", "nn_opp_mean", "turn_mean")


@dataclass
class Clip:
    """10 Hz tracking for one period: players' xy (NaN when unseen), their team (0/1), the ball, and the
    camera's footprint on the pitch per frame (4 corners, NaN when unknown)."""

    xy: np.ndarray  # (T, P, 2)
    team: np.ndarray  # (P,)
    ball: np.ndarray  # (T, 3)
    corners: np.ndarray  # (T, 4, 2)
    match: str


# ------------------------------------------------------------------------------------------------ real data


def _parse_skillcorner(match_dir: Path) -> list[Clip]:
    mid = match_dir.name
    meta = json.loads((match_dir / f"{mid}_match.json").read_text(encoding="utf-8"))
    home = meta["home_team"]["id"]
    team_of = {p["id"]: (0 if p["team_id"] == home else 1) for p in meta["players"]}
    ids = sorted(team_of)
    col = {pid: k for k, pid in enumerate(ids)}
    rows: dict[int, list] = {}
    with (match_dir / f"{mid}_tracking_extrapolated.jsonl").open(encoding="utf-8") as fh:
        for line in fh:
            f = json.loads(line)
            if not f.get("period") or not f.get("player_data"):
                continue
            xy = np.full((len(ids), 2), np.nan)
            for pl in f["player_data"]:
                if pl.get("is_detected") and pl["player_id"] in col and pl["x"] is not None:
                    xy[col[pl["player_id"]]] = (pl["x"] + 52.5, pl["y"] + 34.0)
            b = f["ball_data"]
            ball = (np.array([b["x"] + 52.5, b["y"] + 34.0, b["z"] or 0.0]) if b.get("x") is not None
                    else np.full(3, np.nan))
            c = f["image_corners_projection"]
            keys = ("top_left", "bottom_left", "bottom_right", "top_right")
            corners = (np.array([[c[f"x_{k}"] + 52.5, c[f"y_{k}"] + 34.0] for k in keys])
                       if c.get("x_top_left") is not None else np.full((4, 2), np.nan))
            rows.setdefault(f["period"], []).append((xy, ball, corners))
    team = np.array([team_of[pid] for pid in ids])
    return [Clip(np.stack([r[0] for r in rs]), team, np.stack([r[1] for r in rs]), np.stack([r[2] for r in rs]), mid)
            for _, rs in sorted(rows.items())]


def load_real(raw: Path = RAW) -> list[Clip]:
    """Every downloaded SkillCorner match with tracking, parsed once and cached under calibration/raw/."""
    clips: list[Clip] = []
    CACHE.mkdir(parents=True, exist_ok=True)
    for match_dir in sorted(p for p in raw.iterdir() if p.is_dir()):
        mid = match_dir.name
        if not (match_dir / f"{mid}_tracking_extrapolated.jsonl").exists():
            continue
        cache = CACHE / f"{mid}.npz"
        if not cache.exists():
            parsed = _parse_skillcorner(match_dir)
            np.savez_compressed(cache, **{f"{k}_{name}": getattr(c, name) for k, c in enumerate(parsed)
                                          for name in ("xy", "team", "ball", "corners")})
        data = np.load(cache)
        n = len({key.split("_", 1)[0] for key in data.files})
        clips += [Clip(data[f"{k}_xy"], data[f"{k}_team"], data[f"{k}_ball"], data[f"{k}_corners"], mid)
                  for k in range(n)]
    return clips


def available(raw: Path = RAW) -> bool:
    return raw.exists() and any(raw.glob("*/*_tracking_extrapolated.jsonl"))


# ------------------------------------------------------------------------------------------------ generated


def clips_from_table(table, home: str, name: str) -> list[Clip]:
    """One clip per period from a 10 Hz tracking table, as the writer lays it out."""
    clips = []
    players = sorted({n[:-2] for n in table.column_names if n.endswith("_x") and not n.startswith("ball")})
    team = np.array([0 if p.split("-")[0] == home else 1 for p in players])
    period = table.column("period").to_numpy()
    for p in np.unique(period):
        sel = np.nonzero(period == p)[0]
        sub = table.take(sel)
        xy = np.stack([np.stack([sub.column(f"{pid}_x").to_numpy(zero_copy_only=False),
                                 sub.column(f"{pid}_y").to_numpy(zero_copy_only=False)], axis=1)
                       for pid in players], axis=1).astype(float)
        ball = np.stack([sub.column(c).to_numpy(zero_copy_only=False) for c in ("ball_x", "ball_y", "ball_z")],
                        axis=1).astype(float)
        clips.append(Clip(xy, team, ball, np.full((len(sel), 4, 2), np.nan), name))
    return clips


def load_generated(match_dirs: list[Path]) -> list[Clip]:
    clips = []
    for d in match_dirs:
        home = json.loads((d / "match.json").read_text(encoding="utf-8"))["home"]["club_id"]
        clips += clips_from_table(pq.read_table(d / "tracking_10hz.parquet"), home, d.name)
    return clips


def _inside(points: np.ndarray, poly: np.ndarray) -> np.ndarray:
    """Points inside a convex quadrilateral (corners in order), by the sign of the cross products."""
    inside = np.ones(len(points), dtype=bool)
    sign = None
    for k in range(4):
        a, b = poly[k], poly[(k + 1) % 4]
        cross = (b[0] - a[0]) * (points[:, 1] - a[1]) - (b[1] - a[1]) * (points[:, 0] - a[0])
        s = np.sign(cross)
        if sign is None:
            sign = np.where(s == 0, 1, s)
        inside &= (s == sign) | (s == 0)
    return inside


def camera_mask(gen: Clip, real: list[Clip], rng: np.random.Generator) -> Clip:
    """Hide the players a broadcast camera wouldn't see: take a real camera footprint sequence and slide it
    along the touchline to follow our ball, as a broadcast camera follows play."""
    xy = gen.xy.copy()
    sources = [c for c in real if np.isfinite(c.corners[:, 0, 0]).mean() > 0.5]
    src = sources[int(rng.integers(len(sources)))]
    ok = np.nonzero(np.isfinite(src.corners[:, 0, 0]) & np.isfinite(src.ball[:, 0]))[0]
    start = int(rng.integers(max(len(ok) - len(xy), 1)))
    for t in range(len(xy)):
        k = ok[min(start + t, len(ok) - 1)]
        poly = src.corners[k].copy()
        if np.isfinite(gen.ball[t, 0]):
            poly[:, 0] += gen.ball[t, 0] - src.ball[k, 0]
        seen = _inside(np.nan_to_num(xy[t], nan=-999.0), poly)
        xy[t, ~seen] = np.nan
    return Clip(xy, gen.team, gen.ball, gen.corners, gen.match)


# ------------------------------------------------------------------------------------------------ features


def window_features(c: Clip, i0: int) -> np.ndarray | None:
    xy = c.xy[i0: i0 + WINDOW]
    ball = c.ball[i0: i0 + WINDOW]
    seen = np.isfinite(xy[..., 0])
    if (seen.sum(axis=1) < MIN_SEEN).mean() > 0.2 or np.isnan(ball[:, 0]).mean() > 0.2:
        return None
    # Live play only: at stoppages broadcasts cut to replays and close-ups, which SkillCorner leaves out, so its
    # windows almost never hold a dead ball and ours shouldn't either.
    still = np.linalg.norm(np.diff(ball[:, :2], axis=0), axis=1) * HZ < 0.05
    if still.mean() > 0.2:
        return None
    vel = np.diff(xy, axis=0) * HZ
    speed = np.linalg.norm(vel, axis=2)
    acc = np.abs(np.diff(speed, axis=0)) * HZ
    s, a = speed[np.isfinite(speed)], acc[np.isfinite(acc)]
    s, a = s[s < 12.5], a[a < 30.0]  # drop the frame where a player comes into view
    if s.size < 50:
        return None
    heading = np.arctan2(vel[..., 1], vel[..., 0])
    turn = np.abs(np.angle(np.exp(1j * np.diff(heading, axis=0)))) * HZ
    moving = (speed[1:] > 2.0) & (speed[:-1] > 2.0)
    turn = turn[moving & np.isfinite(turn)]
    nn_team, nn_opp, spread_x, spread_y = [], [], [], []
    for t in range(0, WINDOW, 10):
        p, tm = xy[t], c.team
        ok = np.isfinite(p[:, 0])
        for side in (0, 1):
            mine, theirs = p[ok & (tm == side)], p[ok & (tm != side)]
            if len(mine) >= 2:
                d = np.linalg.norm(mine[:, None] - mine[None], axis=2)
                np.fill_diagonal(d, np.inf)
                nn_team.append(float(d.min(axis=1).mean()))
                spread_x.append(float(mine[:, 0].std()))
                spread_y.append(float(mine[:, 1].std()))
            if len(mine) and len(theirs):
                nn_opp.append(float(np.linalg.norm(mine[:, None] - theirs[None], axis=2).min(axis=1).mean()))
    bs = np.linalg.norm(np.diff(ball[:, :2], axis=0), axis=1) * HZ
    bs = bs[np.isfinite(bs) & (bs < 45.0)]
    return np.array([
        float(seen.sum(axis=1).mean()), float(s.mean()), float(np.median(s)), float(np.percentile(s, 90)),
        float(s.max()), float(a.mean()) if a.size else 0.0, float(np.percentile(a, 90)) if a.size else 0.0,
        float((s > 20 / 3.6).mean()), float((s > 25 / 3.6).mean()), float(turn.mean()) if turn.size else 0.0,
        float(np.mean(nn_team)) if nn_team else 0.0, float(np.mean(nn_opp)) if nn_opp else 0.0,
        float(np.mean(spread_x)) if spread_x else 0.0, float(np.mean(spread_y)) if spread_y else 0.0,
        float(bs.mean()) if bs.size else 0.0, float(np.percentile(bs, 90)) if bs.size else 0.0,
    ])


def windows(clips: list[Clip], per_match: int, rng: np.random.Generator) -> tuple[np.ndarray, list[str]]:
    feats, groups = [], []
    by_match: dict[str, list[np.ndarray]] = {}
    for c in clips:
        for i0 in range(0, len(c.xy) - WINDOW, STEP):
            f = window_features(c, i0)
            if f is not None:
                by_match.setdefault(c.match, []).append(f)
    for m, fs in by_match.items():
        pick = rng.choice(len(fs), size=min(per_match, len(fs)), replace=False)
        feats += [fs[k] for k in pick]
        groups += [m] * len(pick)
    return np.array(feats), groups


@cache
def _footprints() -> tuple[Clip, ...]:
    """The real camera footprints and ball paths, without the players: all `camera_mask` needs, kept small."""
    return tuple(Clip(np.zeros((len(c.ball), 0, 2)), c.team, c.ball.astype(np.float32), c.corners.astype(np.float32),
                      c.match) for c in load_real())


def tracking_summary(clips: list[Clip], per_match: int = 150, seed: int = 0) -> dict[str, float]:
    """Medians of the telling tracking features over camera-masked live-play windows, as gate 5 sees them."""
    rng = np.random.default_rng(seed)
    x, _ = windows([camera_mask(c, list(_footprints()), rng) for c in clips], per_match, rng)
    return {name: float(np.median(x[:, FEATURES.index(name)])) for name in TRACKING_FEATURES} if len(x) else {}


def real_windows(per_match: int = 150, seed: int = 0) -> np.ndarray:
    """Feature vectors of real live-play windows, for fitting the tracking bands."""
    x, _ = windows(load_real(), per_match, np.random.default_rng(seed))
    return x


# ------------------------------------------------------------------------------------------------ the gate


def evaluate(generated_dirs: list[Path], per_match: int = 150, seed: int = 0) -> dict:
    """ROC AUC of a classifier separating generated from real windows, on matches it never trained on."""
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.inspection import permutation_importance
    from sklearn.metrics import roc_auc_score
    from sklearn.model_selection import GroupKFold

    rng = np.random.default_rng(seed)
    real = load_real()
    gen = [camera_mask(c, real, rng) for c in load_generated(generated_dirs)]
    xr, gr = windows(real, per_match, rng)
    xg, gg = windows(gen, per_match, rng)
    x = np.vstack([xr, xg])
    y = np.concatenate([np.zeros(len(xr)), np.ones(len(xg))])
    groups = np.array([f"real-{g}" for g in gr] + [f"gen-{g}" for g in gg])
    folds = min(5, len(set(gr)), len(set(gg)))
    scores = np.zeros(len(y))
    for train, test in GroupKFold(n_splits=folds).split(x, y, groups):
        clf = HistGradientBoostingClassifier(max_iter=200, learning_rate=0.05, random_state=seed)
        clf.fit(x[train], y[train])
        scores[test] = clf.predict_proba(x[test])[:, 1]
    auc = float(roc_auc_score(y, scores))
    clf = HistGradientBoostingClassifier(max_iter=200, learning_rate=0.05, random_state=seed).fit(x, y)
    imp = permutation_importance(clf, x, y, n_repeats=5, random_state=seed, scoring="roc_auc")
    order = np.argsort(-imp.importances_mean)
    gaps = {FEATURES[k]: {"real": round(float(np.median(xr[:, k])), 3), "generated": round(float(np.median(xg[:, k])), 3),
                          "importance": round(float(imp.importances_mean[k]), 3)} for k in order[:6]}
    return {"auc": round(auc, 3), "real_windows": len(xr), "generated_windows": len(xg),
            "real_matches": len(set(gr)), "generated_matches": len(set(gg)), "telltales": gaps}
