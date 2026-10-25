"""The nine quality gates (PRD 12.10): what makes a generated match count as good synthetic data.

Each gate reports pass, fail or not run, with the numbers behind it. Gates read the public match files, and
gates 1, 4 and 6 also read the held-out truth (true probabilities, intents and the answer key), as the
generator's own quality checks may. Thresholds are the PRD's starting values.

    uv run offball gates showcase            every match in datasets/showcase
    uv run offball gates smoke --json        and write calibration/reports/gates-smoke.json
"""

from __future__ import annotations

import collections
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from offball.calibration.metrics import (
    RUN_TYPES,
    RUNNING_MPS,
    SPRINT_MPS,
    dead_seconds,
    fitted,
    possession_count,
    robust_peak,
)
from offball.core import HZ
from offball.generator.names import is_blocked, load_blocklist, name_hash
from offball.models.candidates import DETECTORS, detect
from offball.models.match_data import MatchData
from offball.models.runs import Possession

ROOT = Path(__file__).resolve().parents[2]
DATASETS, TRUTH, RAW = ROOT / "datasets", ROOT / "truth", ROOT / "calibration" / "raw"
REPORTS = ROOT / "calibration" / "reports"
MATCH_SECONDS = 95 * 60
HI_SPEED = 20.0 / 3.6
PITCH_L, PITCH_W = 105.0, 68.0


@dataclass
class Gate:
    number: int
    name: str
    status: str  # pass, fail or not run
    summary: str
    numbers: dict = field(default_factory=dict)


@dataclass
class Match:
    dir: Path
    md: MatchData
    truth: Path | None

    @property
    def match_id(self) -> str:
        return self.md.match_id

    def truth_rows(self, name: str) -> list[dict]:
        path = self.truth / name if self.truth else None
        if path is None or not path.exists():
            return []
        if name.endswith(".jsonl"):
            return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        return json.loads(path.read_text(encoding="utf-8"))


def load_set(name_or_path: str) -> list[Match]:
    path = Path(name_or_path)
    if not path.exists():
        path = DATASETS / name_or_path
    dirs = [path] if (path / "match.json").exists() else sorted(p.parent for p in path.glob("*/match.json"))
    out = []
    for d in dirs:
        truth = TRUTH / d.parent.name / d.name
        out.append(Match(d, MatchData.load(d), truth if truth.exists() else None))
    return out


# ------------------------------------------------------------------------------------------------ helpers


def ks_against(sample: list[float] | np.ndarray, quantiles: list[float]) -> float:
    """Two-sided KS distance between a sample and a distribution given by its 101 percentiles."""
    s = np.sort(np.asarray(sample, dtype=float))
    if s.size == 0:
        return 1.0
    q = np.asarray(quantiles, dtype=float)
    p = np.linspace(0, 1, q.size)
    xs = np.union1d(s, q)
    f_sample = np.searchsorted(s, xs, side="right") / s.size
    f_ref = np.interp(xs, q, p, left=0.0, right=1.0)
    return float(np.max(np.abs(f_sample - f_ref)))


def _played_s(md: MatchData) -> float:
    return sum(p.duration_ms for p in md.info.periods) / 1000.0


def _goalkeepers(md: MatchData) -> set[str]:
    return {e.player_id for s in (md.info.home, md.info.away) for e in s.lineup if e.role == "GK"}


def file_metrics(m: Match) -> tuple[dict[str, float], dict[str, list[float]]]:
    """The calibration metrics of one match file, per 95 minutes, and its samples for the KS checks."""
    md = m.md
    ev = md.events
    scale = MATCH_SECONDS / max(_played_s(md), 1.0)
    passes = [e for e in ev if e.type == "pass"]
    shots = [e for e in ev if e.type == "shot"]
    lengths = [float(np.hypot(e.end_xy[0] - e.start_xy[0], e.end_xy[1] - e.start_xy[1]))
               for e in passes if e.start_xy and e.end_xy]
    shot_dist, in_box = [], 0
    for s in shots:
        x, y = s.start_xy
        attack_right = md.direction(s.period, s.team_id) > 0
        gx = PITCH_L if attack_right else 0.0
        shot_dist.append(float(np.hypot(gx - x, PITCH_W / 2 - y)))
        in_box += abs(gx - x) <= 16.5 and abs(y - PITCH_W / 2) <= 20.16
    probs = [p["p_success"] for p in m.truth_rows("probabilities.jsonl") if p.get("kind") == "shot"]
    keepers = _goalkeepers(md)
    outfield = [k for k, pid in enumerate(md.players) if pid not in keepers]
    total_m = hi_m = run_m = sprint_m = 0.0
    player_m: dict[int, float] = collections.defaultdict(float)
    player_frames: dict[int, int] = collections.defaultdict(int)
    speeds: dict[int, list[np.ndarray]] = collections.defaultdict(list)
    for pf in md.periods.values():
        step = np.linalg.norm(np.diff(pf.xy.astype(float), axis=0), axis=2)
        step = np.where(np.isnan(step), 0.0, step)
        for k in outfield:
            col = step[:, k]
            total_m += float(col.sum())
            hi_m += float(col[col * HZ > HI_SPEED].sum())
            run_m += float(col[(col * HZ > RUNNING_MPS) & (col * HZ <= HI_SPEED)].sum())
            sprint_m += float(col[col * HZ > SPRINT_MPS].sum())
            player_m[k] += float(col.sum())
            on = ~np.isnan(pf.xy[:, k, 0])
            player_frames[k] += int(on.sum())
            speeds[k].append(pf.speed[:, k])
    metrics = {
        "passes": len(passes) * scale,
        "completion": sum(e.outcome == "complete" for e in passes) / max(len(passes), 1),
        "median_pass_m": float(np.median(lengths)) if lengths else 0.0,
        "long_pass_share": float(np.mean([d > 30 for d in lengths])) if lengths else 0.0,
        "shots": len(shots) * scale,
        "goals": sum(e.outcome == "goal" for e in shots) * scale,
        "xg_per_shot": float(np.mean(probs)) if probs else float("nan"),
        "shots_in_box_share": in_box / max(len(shots), 1),
        "possessions": possession_count([e.model_dump() for e in ev]) * scale,
        "tackles": sum(e.type == "tackle" for e in ev) * scale,
        "fouls": sum(e.type == "foul" for e in ev) * scale,
        "offsides": sum(e.type == "offside" for e in ev) * scale,
        "corners": sum(e.type == "pass" and e.subtype == "corner" for e in ev) * scale,
        "throw_ins": sum(e.type == "pass" and e.subtype == "throw_in" for e in ev) * scale,
        "km_per_outfield": total_m / 20 / 1000 * scale,
        "hsr_share": hi_m / max(total_m, 1.0),
        "running_share": run_m / max(total_m, 1.0),
        "sprint_share": sprint_m / max(total_m, 1.0),
        "in_play_share": 1.0 - dead_seconds([e.model_dump() for e in ev]) / max(_played_s(md), 1.0),
    }
    full = [k for k in outfield if player_frames[k] / HZ >= 60 * 60 * min(1.0, _played_s(md) / MATCH_SECONDS)]
    samples = {
        "pass_length_m": lengths,
        "shot_distance_m": shot_dist,
        "player_peak_speed_kmh": [robust_peak(np.concatenate(speeds[k])) * 3.6 for k in full],
        "player_km_per95": [player_m[k] / 1000 * MATCH_SECONDS / (player_frames[k] / HZ) for k in full],
    }
    return metrics, samples


# ------------------------------------------------------------------------------------------------ gates


def gate_realism(matches: list[Match], max_ks: float = 0.10, share: float = 0.90) -> Gate:
    fit = fitted()
    if not fit:
        return Gate(1, "Realism", "not run", "No fitted targets yet: run `offball fit` first.")
    rows, pooled = [], collections.defaultdict(list)
    for m in matches:
        metrics, samples = file_metrics(m)
        rows.append(metrics)
        for k, v in samples.items():
            pooled[k] += v
    inside, problems = {}, []
    for name, b in fit["match"].items():
        values = [r[name] for r in rows if name in r and not np.isnan(r[name])]
        if not values:
            continue
        mean = float(np.mean(values))
        if "aggregates" in b["source"]:
            # Season averages per player vary far less than single matches, so the set's average is what
            # has to sit inside their range.
            ok = b["p5"] <= mean <= b["p95"]
            inside[name] = {"mean_inside_p5_p95": ok, "mean": round(mean, 3), "real_p5": b["p5"],
                            "real_p95": b["p95"], "compared": "set average against season averages"}
        else:
            frac = float(np.mean([b["p5"] <= v <= b["p95"] for v in values]))
            ok = frac >= share
            inside[name] = {"share_inside_p5_p95": round(frac, 2), "mean": round(mean, 3),
                            "real_p5": b["p5"], "real_p95": b["p95"], "compared": "each match against real matches"}
        if not ok:
            problems.append(f"{name} {mean:.3g} (real 5th–95th: {b['p5']:g}–{b['p95']:g})")
    ks = {}
    for name, d in fit["distributions"].items():
        if pooled.get(name):
            ks[name] = round(ks_against(pooled[name], d["quantiles"]), 3)
            if ks[name] > max_ks:
                problems.append(f"KS {name} {ks[name]} (at most {max_ks})")
    status = "pass" if not problems else "fail"
    summary = "Inside the real range on every statistic." if not problems else "Outside: " + "; ".join(problems)
    return Gate(1, "Realism", status, summary, {"per_metric": inside, "ks": ks})


def gate_physics(matches: list[Match]) -> Gate:
    limits = {"speed": 10.5, "accel": 7.0, "decel": 9.0, "turn": 15.0, "pass_ball": 35.0, "shot_ball": 40.0,
              "separation": 0.5}
    worst = collections.defaultdict(float)
    counts = collections.Counter()
    frames_total = 0
    for m in matches:
        md = m.md
        for pf in md.periods.values():
            frames_total += pf.n
            sp = pf.speed
            worst["speed"] = max(worst["speed"], float(np.nanmax(sp)))
            counts["speed"] += int(np.nansum(sp > limits["speed"]))
            acc = np.diff(sp, axis=0) * HZ
            worst["accel"] = max(worst["accel"], float(np.nanmax(acc)))
            worst["decel"] = max(worst["decel"], float(-np.nanmin(acc)))
            counts["accel"] += int(np.nansum(acc > limits["accel"]))
            counts["decel"] += int(np.nansum(acc < -limits["decel"]))
            ori = pf.ori.astype(float)
            d_ori = np.angle(np.exp(1j * np.diff(ori, axis=0))) * HZ
            moving = sp[1:] > 1.0
            turn = np.where(moving, np.abs(d_ori), 0.0)
            worst["turn"] = max(worst["turn"], float(np.nanmax(turn)))
            counts["turn"] += int(np.nansum(turn > limits["turn"]))
            x, y = pf.xy[..., 0], pf.xy[..., 1]
            counts["off_pitch"] += int(np.nansum((x < -2) | (x > PITCH_L + 2) | (y < -2) | (y > PITCH_W + 2)))
            for i in range(0, pf.n, 5):  # every fifth frame is plenty for spacing
                pos = pf.xy[i]
                ok = ~np.isnan(pos[:, 0])
                p = pos[ok].astype(float)
                if len(p) < 2:
                    continue
                far_from_ball = np.linalg.norm(p - pf.ball[i, :2], axis=1) > 3.0
                d = np.linalg.norm(p[:, None] - p[None, :], axis=2)
                d[np.eye(len(p), dtype=bool)] = np.inf
                both_far = far_from_ball[:, None] & far_from_ball[None, :]
                close = (d < limits["separation"]) & both_far
                counts["separation"] += int(close.sum() // 2)
        for e in md.events:
            if e.ball_speed_mps is None:
                continue
            key = "shot_ball" if e.type == "shot" else "pass_ball"
            worst[key] = max(worst[key], e.ball_speed_mps)
            counts[key] += e.ball_speed_mps > limits[key]
    rate = {k: counts[k] / max(frames_total, 1) for k in counts}
    failing = [k for k in counts if (counts[k] > 0 if k in ("pass_ball", "shot_ball") else rate[k] > 1e-4)]
    summary = ("Every player and ball movement is within human and physical limits." if not failing else
               "Over the limits: " + ", ".join(f"{k} ({counts[k]} times)" for k in failing))
    return Gate(2, "Physics", "pass" if not failing else "fail", summary,
                {"worst": {k: round(v, 2) for k, v in worst.items()}, "limits": limits, "violations": dict(counts),
                 "frames": frames_total})


def _ball_near(pf, i: int, xy, within: float = 1.5) -> bool:
    return float(np.hypot(*(pf.ball[i, :2] - np.asarray(xy, dtype=float)))) <= within


def gate_consistency(matches: list[Match]) -> Gate:
    problems, numbers = [], {}
    for m in matches:
        md = m.md
        passer_ok = receiver_ok = n_pass = n_recv = 0
        for e in md.events:
            if e.type != "pass" or e.player_id not in md.players:
                continue
            pf = md.periods[e.period]
            i = pf.index_of(e.t_ms)
            col = md.players.index(e.player_id)
            n_pass += 1
            passer_ok += _ball_near(pf, i, pf.xy[i, col], 1.5)
            if e.outcome == "complete" and e.recipient_id in md.players:
                n_recv += 1
                rc = md.players.index(e.recipient_id)
                window = range(i, min(i + 5 * HZ, pf.n))
                receiver_ok += any(_ball_near(pf, j, pf.xy[j, rc], 1.5) for j in window)
        goals = collections.Counter(e.team_id for e in md.events if e.type == "shot" and e.outcome == "goal")
        score_ok = all(goals.get(c, 0) == n for c, n in md.info.final_score.items())
        reds = collections.Counter(e.team_id for e in md.events if e.type == "card" and e.subtype == "red")
        count_bad = 0
        for p, pf in md.periods.items():
            for club in (md.home, md.away):
                cols = md.columns_of(club)
                on = (~np.isnan(pf.xy[:, cols, 0])).sum(axis=1)
                count_bad += int((on > 11).sum())
                if on.size and int(on[-1]) != 11 - reds.get(club, 0) and p == max(md.periods):
                    count_bad += 1
            order = [e.t_ms for e in md.events if e.period == p]
            if order != sorted(order) or not (np.diff(pf.t_ms) > 0).all():
                problems.append(f"{m.match_id}: time runs backwards in period {p}")
        rate_p = passer_ok / max(n_pass, 1)
        rate_r = receiver_ok / max(n_recv, 1)
        numbers[m.match_id] = {"passer_at_ball": round(rate_p, 4), "receiver_at_ball": round(rate_r, 4),
                               "score_matches_goals": score_ok, "player_count_problems": count_bad}
        if rate_p < 0.99:
            problems.append(f"{m.match_id}: passer at the ball for {rate_p:.1%} of passes")
        if rate_r < 0.99:
            problems.append(f"{m.match_id}: receiver reached the ball for {rate_r:.1%} of completed passes")
        if not score_ok:
            problems.append(f"{m.match_id}: the score doesn't match the goals")
        if count_bad:
            problems.append(f"{m.match_id}: wrong number of players in {count_bad} frames")
    return Gate(3, "Consistency", "pass" if not problems else "fail",
                "Events, tracking and the score agree." if not problems else "; ".join(problems), numbers)


def gate_behaviour(matches: list[Match]) -> Gate:
    """Off-ball run rates per 30 minutes of team possession against SkillCorner's season aggregates."""
    real = fitted().get("runs_per30_tip", {})
    if not real or not any(m.truth for m in matches):
        return Gate(4, "Behaviour", "not run", "Needs fitted run rates and the intent log.")
    mapping = {intent: real_type for intent, real_type in RUN_TYPES.values()}
    rates: dict[str, list[float]] = collections.defaultdict(list)
    for m in matches:
        md = m.md
        poss = Possession(md)
        tip_s = collections.Counter()
        for p, pf in md.periods.items():
            for t in pf.t_ms[:: HZ]:
                club = poss.at(p, int(t))
                if club:
                    tip_s[club] += 1.0
        counts = collections.Counter()
        for it in m.truth_rows("intents.jsonl"):
            if it["intent"] in mapping:
                counts[(it["player_id"], mapping[it["intent"]])] += 1
        keepers = _goalkeepers(md)
        for pid in md.players:
            if pid in keepers:
                continue
            club = md.team_of[pid]
            on_s = sum(int((~np.isnan(pf.xy[:, md.players.index(pid), 0])).sum()) for pf in md.periods.values()) / HZ
            share_on = on_s / max(_played_s(md), 1.0)
            if share_on < 0.6 or not tip_s[club]:
                continue
            tip_min = tip_s[club] * share_on / 60.0
            for key in mapping.values():
                rates[key].append(counts[(pid, key)] / tip_min * 30.0)
    # Means, not medians: runs in behind are mostly forwards' work, so most players' counts are zero.
    problems, numbers = [], {}
    for key, values in rates.items():
        mean = float(np.mean(values))
        b = real[key]
        numbers[key] = {"mean": round(mean, 2), "real_mean": b["mean"], "real_median": b["p50"]}
        if not 0.5 * b["mean"] <= mean <= 1.5 * b["mean"]:
            problems.append(f"{key} {mean:.2f} per 30 min on average (real average {b['mean']:g})")
    return Gate(4, "Behaviour", "pass" if not problems else "fail",
                "Run rates sit within the real range." if not problems else "; ".join(problems), numbers)


def gate_discriminator(matches: list[Match], max_auc: float = 0.65) -> Gate:
    """A classifier tries to tell 10 s of our camera-masked tracking from SkillCorner's broadcast tracking."""
    from offball.calibration import discriminator

    if not discriminator.available():
        return Gate(5, "Discriminator", "not run",
                    "Needs SkillCorner's tracking files in calibration/raw/ (about 90 MB a match, in Git LFS).")
    dirs = [m.dir for m in matches if (m.dir / "tracking_10hz.parquet").exists()]
    if len(dirs) < 2:
        return Gate(5, "Discriminator", "not run", "Needs at least two matches with 10 Hz tracking, to hold one out.")
    result = discriminator.evaluate(dirs)
    tells = ", ".join(f"{k} (real {v['real']:g}, ours {v['generated']:g})"
                      for k, v in list(result["telltales"].items())[:3])
    ok = result["auc"] <= max_auc
    note = (f"A classifier tells our windows from real ones with ROC AUC {result['auc']} (at most {max_auc}) on "
            f"held-out matches; its strongest tells: {tells}.")
    return Gate(5, "Discriminator", "pass" if ok else "fail", note, result)


def gate_detectability(matches: list[Match], need: float = 0.95) -> Gate:
    found = total = invented = 0
    uncovered = collections.Counter()
    for m in matches:
        key = m.truth_rows("answer_key.json")
        if not key:
            continue
        cands = detect(m.md)
        for k in key:
            base = k["type"].removeprefix("null_")
            if base == "run":
                base = "decoy_run"
            if base not in DETECTORS:
                uncovered[k["type"]] += 1
                continue
            det = DETECTORS[base]
            tolerance = getattr(det, "match_tolerance_ms", 3000)
            # Team moments play out over minutes and belong to a team; the others to a player, within seconds.
            owner_key, owner = (("team_id", k["team_id"]) if getattr(det, "team_moment", False)
                                else ("creator_id", k["creator_id"]))
            near = [c for c in cands if c.type == base and c.period == k["period"] and getattr(c, owner_key) == owner
                    and abs(c.t_start_ms - k["t_start_ms"]) <= tolerance]
            if k["is_null"]:
                invented += bool(near)
            else:
                total += 1
                found += bool(near)
    if not total and not invented:
        return Gate(6, "Detectability", "not run", "No answer keys with detectable moments.")
    recall = found / max(total, 1)
    ok = recall >= need and invented == 0
    note = f"{found} of {total} planted moments found from the data alone; {invented} null moments credited"
    if uncovered:
        note += f"; no detector yet for {dict(uncovered)}"
    return Gate(6, "Detectability", "pass" if ok else "fail", note + ".",
                {"recall": round(recall, 3), "invented": invented, "uncovered": dict(uncovered)})


def _paths_wyscout(limit: int, rng: np.random.Generator) -> np.ndarray | None:
    path = RAW / "wyscout" / "events_England.json"
    if not path.exists():
        return None
    events = json.loads(path.read_text(encoding="utf-8"))
    paths, cur, team = [], [], None
    for e in events:
        if e["eventName"] not in ("Pass", "Shot", "Free Kick", "Others on the ball") or not e.get("positions"):
            continue
        if e["teamId"] != team:
            if len(cur) >= 5:
                paths.append(cur)
            cur, team = [], e["teamId"]
        p = e["positions"][0]
        cur.append((p["x"] * PITCH_L / 100, p["y"] * PITCH_W / 100))
    pick = rng.choice(len(paths), size=min(limit, len(paths)), replace=False)
    return np.stack([_resample(paths[i]) for i in pick])


def _resample(points: list[tuple[float, float]], n: int = 8) -> np.ndarray:
    p = np.asarray(points, dtype=float)
    seg = np.r_[0.0, np.cumsum(np.linalg.norm(np.diff(p, axis=0), axis=1))]
    if seg[-1] < 1e-6:
        return np.repeat(p[:1], n, axis=0).ravel()
    t = np.linspace(0, seg[-1], n)
    return np.stack([np.interp(t, seg, p[:, 0]), np.interp(t, seg, p[:, 1])], axis=1).ravel()


def gate_novelty(matches: list[Match], min_distance: float = 1.0) -> Gate:
    bl = load_blocklist()
    named = []
    for m in matches:
        for sheet in (m.md.info.home, m.md.info.away):
            if name_hash(sheet.name) in bl:
                named.append(sheet.name)
            for e in sheet.lineup:
                last = e.name.split(". ", 1)[-1]
                if is_blocked(e.name, last, bl):
                    named.append(e.name)
    numbers: dict = {"blocklist_size": len(bl), "real_names_found": len(named)}
    rng = np.random.default_rng(0)
    real = _paths_wyscout(20000, rng)
    closest = None
    if real is not None:
        sims = []
        for m in matches:
            by_poss = collections.defaultdict(list)
            for e in m.md.events:
                if e.possession_id and e.start_xy and e.type in ("pass", "shot", "carry", "clearance"):
                    x, y = e.start_xy
                    if m.md.direction(e.period, e.team_id) < 0:  # into Wyscout's attacking-left-to-right frame
                        x, y = PITCH_L - x, PITCH_W - y
                    by_poss[e.possession_id].append((x, y))
            sims += [_resample(v) for v in by_poss.values() if len(v) >= 5]
        if sims:
            s = np.stack(sims)
            mirrored = s.reshape(len(s), 8, 2).copy()
            mirrored[..., 1] = PITCH_W - mirrored[..., 1]  # the providers may count y from opposite touchlines
            best = np.full(len(s), np.inf)
            for chunk in np.array_split(real, max(1, len(real) // 2000)):
                c = chunk.reshape(1, len(chunk), 8, 2)
                for variant in (s.reshape(len(s), 1, 8, 2), mirrored.reshape(len(s), 1, 8, 2)):
                    d = np.linalg.norm(variant - c, axis=3).mean(axis=2).min(axis=1)
                    best = np.minimum(best, d)
            closest = float(best.min())
            numbers.update({"possessions_checked": len(s), "real_possessions": len(real),
                            "closest_mean_m": round(closest, 2), "copies": int((best < min_distance).sum())})
    problems = []
    if not bl:
        problems.append("the name blocklist is empty (run `offball blocklist`)")
    if named:
        problems.append(f"real names: {len(named)}")
    if closest is not None and closest < min_distance:
        problems.append(f"{numbers['copies']} possessions trace a real one to within {min_distance} m on average")
    if real is None:
        summary = "Names checked; ball paths not checked (no Wyscout data)."
    else:
        summary = (f"No real names, and no possession closer than {closest:.1f} m on average to any of "
                   f"{len(real)} real ones." if not problems else "; ".join(problems))
    return Gate(7, "Novelty", "pass" if not problems else "fail", summary, numbers)


def gate_diversity(matches: list[Match]) -> Gate:
    if len(matches) < 2:
        return Gate(8, "Diversity", "not run", "Needs at least two matches in the set.")
    fit = fitted()
    rows = [file_metrics(m)[0] for m in matches]
    keys = [k for k in ("passes", "shots", "possessions", "long_pass_share", "km_per_outfield", "fouls")
            if k in fit.get("match", {})]
    scale = np.array([max(fit["match"][k]["p75"] - fit["match"][k]["p25"], 1e-6) for k in keys])
    vecs = np.array([[r[k] for k in keys] for r in rows]) / scale
    d = np.linalg.norm(vecs[:, None] - vecs[None, :], axis=2)
    d[np.eye(len(rows), dtype=bool)] = np.inf
    closest = float(d.min())
    scores = {f"{m.md.info.final_score}" for m in matches}
    ok = closest >= 0.25
    return Gate(8, "Diversity", "pass" if ok else "fail",
                f"Closest pair of matches {closest:.2f} interquartile ranges apart; {len(scores)} different scorelines.",
                {"closest_pair": round(closest, 3), "scorelines": sorted(scores)})


def gate_determinism(matches: list[Match]) -> Gate:
    """Every file still matches the hash written when it was generated. Re-generating from the seed and
    comparing is `offball gates --regenerate` (slow)."""
    bad, checked = [], 0
    for m in matches:
        manifest = m.dir / "manifest.json"
        if not manifest.exists():
            continue
        for rel, digest in json.loads(manifest.read_text(encoding="utf-8")).items():
            name = rel.split("/", 1)[1]
            path = m.dir / name if (m.dir / name).exists() else (m.truth / name if m.truth else None)
            if path is None or not path.exists():
                continue
            checked += 1
            if hashlib.md5(path.read_bytes()).hexdigest() != digest:
                bad.append(rel)
    if not checked:
        return Gate(9, "Determinism", "not run", "No manifests to check.")
    return Gate(9, "Determinism", "pass" if not bad else "fail",
                f"{checked} files match their generation hashes." if not bad else f"Changed since generation: {bad}",
                {"files": checked, "changed": bad})


def run(name_or_path: str) -> list[Gate]:
    matches = load_set(name_or_path)
    if not matches:
        raise FileNotFoundError(f"No matches in {name_or_path}")
    return [gate_realism(matches), gate_physics(matches), gate_consistency(matches), gate_behaviour(matches),
            gate_discriminator(matches), gate_detectability(matches), gate_novelty(matches), gate_diversity(matches),
            gate_determinism(matches)]


def report(set_name: str, gates: list[Gate], matches: int) -> str:
    lines = [f"# Quality gates: {set_name}", "", f"{matches} match(es). Thresholds are PRD 12.10's starting values.", "",
             "| Gate | Status | What it found |", "| --- | --- | --- |"]
    for g in gates:
        lines.append(f"| {g.number}. {g.name} | {g.status} | {g.summary} |")
    return "\n".join(lines) + "\n"
