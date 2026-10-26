"""Panel numbers and chart data (PRD 13, 16.4; INTEGRATION.md 6.5), computed from the observed match.

Each function returns exactly the shape of a stand-in in `web/src/lib/content.ts` or `web/src/lib/stats.ts`, so
the panels need no change, and every number comes from tracking, events and the detected moments up to the viewer's
time; no model writes any of it. Pitch positions are shown with the home club attacking to the right, as the
frontend draws the showcase; shots are shown with each club attacking to the right.

Tracking-heavy series (shape, occupancy, distance) read the tracking once a second.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

import numpy as np

from offball.contracts import Candidate
from offball.core import FRAME_MS, HZ, PITCH_LENGTH, PITCH_WIDTH, SPRINT_MPS
from offball.models import metrics
from offball.models.match_data import MatchData
from offball.models.runs import Possession

Clock = tuple[int, int]  # (period, t_ms)
STEP = HZ  # frames between tracking samples: one a second
TILT_PRIOR = 6  # passes' worth of evenness added to every field-tilt window
SHOT_OUTCOMES = {"goal": "goal", "saved": "saved", "off_target": "off target", "blocked": "blocked"}
# The run types the frontend's run map and Player focus panel know, from the moment types the detectors find.
RUN_TYPES = {"decoy_run": "Decoy", "timed_run_in_behind": "In behind", "blind_side_run": "In behind",
             "third_man_run": "In behind", "overlap": "Overlap", "underlap": "Overlap", "check_to_ball": "Check to ball"}


class StatUnavailable(LookupError):
    """The stat can't be computed for this match yet, so the frontend keeps its own."""


def end_of(md: MatchData) -> Clock:
    last = max(md.periods)
    return last, int(md.periods[last].t_ms[-1])


def minute_of(period: int, t_ms: int) -> float:
    """Match minute, with first-half stoppage time kept inside the 45th minute so it can't overlap the second half."""
    m = t_ms / 60000
    return min(m, 44.99) if period == 1 else 45 + m


def _upto(md: MatchData, until: Clock):
    """(period, frames, last index) for every period up to `until`."""
    for p, pf in sorted(md.periods.items()):
        if p > until[0]:
            break
        yield p, pf, (pf.index_of(until[1]) if p == until[0] else pf.n - 1)


def _home_view(md: MatchData, period: int, xy: Any) -> np.ndarray:
    """Absolute -> the frontend's view, where the home club attacks to the right."""
    return md.to_team(period, md.home, np.asarray(xy, dtype=float))


def _seen(cands: list[Candidate], until: Clock) -> list[Candidate]:
    return [c for c in cands if (c.period, c.t_end_ms) <= until]


# ------------------------------------------------------------------------------------------------ space created


def leaders(md: MatchData, cands: list[Candidate], until: Clock, n: int = 5) -> list[dict[str, Any]]:
    """Space Created so far, per player, with a bootstrap 90% interval over that player's moments (`LEADERS`)."""
    per: dict[str, list[float]] = defaultdict(list)
    for c in _seen(cands, until):
        if c.creator_id and c.space_created_m2:
            per[c.creator_id].append(float(c.space_created_m2))
    rng = np.random.default_rng(7)
    out = []
    for pid, values in per.items():
        v = np.asarray(values)
        sums = rng.choice(v, size=(2000, len(v)), replace=True).sum(axis=1)
        out.append({"id": pid, "v": round(float(v.sum())), "lo": round(float(np.percentile(sums, 5))),
                    "hi": round(float(np.percentile(sums, 95)))})
    return sorted(out, key=lambda r: -r["v"])[:n]


# ------------------------------------------------------------------------------------------------ player focus


def _sprint_starts(md: MatchData, player_id: str, until: Clock) -> list[Clock]:
    col = md.players.index(player_id)
    out = []
    for p, pf, end in _upto(md, until):
        fast = np.nan_to_num(pf.speed[: end + 1, col]) > SPRINT_MPS
        edges = np.diff(np.concatenate([[0], fast.astype(np.int8), [0]]))
        starts, ends = np.nonzero(edges == 1)[0], np.nonzero(edges == -1)[0]
        out += [(p, int(pf.t_ms[a])) for a, b in zip(starts, ends, strict=True) if b - a >= HZ]
    return out


def _tally(times: list[tuple[Clock, float]], window: tuple[Clock, Clock]) -> list[float]:
    """[total before the window, total by its end, seconds into the window when it changed], as `FocusStats` reads
    it. Each item is (when, how much)."""
    start, end = window
    before = sum(v for t, v in times if t < start)
    after = sum(v for t, v in times if t <= end)
    first = min((t for t, _ in times if start <= t <= end), default=None)
    at = round((first[1] - start[1]) / 1000, 1) if first and first[0] == start[0] else 0
    return [round(before, 1), round(after, 1), at]


def focus(md: MatchData, cands: list[Candidate], player_id: str, window: tuple[Clock, Clock]) -> dict[str, Any]:
    """A player's off-ball work before and after a moment (`focusStats`). `window` is the moment, from and to."""
    if player_id not in md.players:
        raise StatUnavailable(f"No player {player_id} in {md.match_id}")
    until = window[1]
    made = [c for c in _seen(cands, until) if c.creator_id == player_id]
    # Off-ball runs are the runs the detectors named (decoys, runs in behind, overlaps), not every fast movement.
    named = [c for c in made if c.type in RUN_TYPES]
    runs = [((c.period, c.t_start_ms), 1) for c in named]
    dragged = [((c.period, c.t_end_ms), len(c.dragged_ids)) for c in named if c.dragged_ids]
    space = [((c.period, c.t_end_ms), float(c.space_created_m2)) for c in made if c.space_created_m2]
    sprints = [(t, 1) for t in _sprint_starts(md, player_id, until)]
    col = md.players.index(player_id)
    top = max(float(np.nanmax(pf.speed[: end + 1, col])) for _, pf, end in _upto(md, until))
    by_type = Counter(RUN_TYPES[c.type] for c in made if c.type in RUN_TYPES)
    return {
        "runs": _tally(runs, window), "dragged": _tally(dragged, window), "space": _tally(space, window),
        "sprints": _tally(sprints, window),
        "distanceKm": metrics.compute(md, "distance_covered_km", player_id=player_id, period=until[0],
                                      t_end_ms=until[1]).value,
        "topSpeed": round(top * 3.6, 1),
        "runsByType": [{"type": t, "n": k} for t, k in by_type.most_common()],
    }


# ------------------------------------------------------------------------------------------------ match series


def momentum(md: MatchData, until: Clock) -> list[dict[str, Any]]:
    """Field tilt per minute (PRD 13): passes in each club's attacking third over five minutes around it, as home
    minus away over the two, shrunk towards zero when there are few. Above zero favours the home club (`MOMENTUM`)."""
    last = int(minute_of(*until))
    counts = np.zeros((last + 1, 2))
    for e in md.events:
        if (e.period, e.t_ms) > until or e.type != "pass" or not e.start_xy or e.team_id not in (md.home, md.away):
            continue
        x = md.to_team(e.period, e.team_id, np.asarray(e.start_xy, dtype=float))[0]
        if x >= PITCH_LENGTH * 2 / 3:
            counts[int(minute_of(e.period, e.t_ms)), 0 if e.team_id == md.home else 1] += 1
    kernel = np.ones(5)
    home, away = np.convolve(counts[:, 0], kernel, "same"), np.convolve(counts[:, 1], kernel, "same")
    tilt = (home - away) / (home + away + TILT_PRIOR)
    return [{"minute": m, "value": round(float(v), 2)} for m, v in enumerate(tilt)]


def control_index(md: MatchData, until: Clock) -> list[dict[str, Any]]:
    """Control versus chaos (PRD 9.2): the share of each minute each club spent in settled possession, meaning a
    possession that has strung three passes together, 0 to 100 (`CONTROL_INDEX`)."""
    last = int(minute_of(*until))
    settled = np.zeros((last + 1, 2))
    by_pos: dict[str, list] = defaultdict(list)
    for e in md.events:
        if (e.period, e.t_ms) <= until and e.possession_id and e.team_id in (md.home, md.away):
            by_pos[e.possession_id].append(e)
    for evs in by_pos.values():
        passes = [e for e in evs if e.type == "pass" and e.outcome == "complete"]
        if len(passes) < 3:
            continue
        team = 0 if evs[0].team_id == md.home else 1
        period, t0, t1 = evs[0].period, passes[2].t_ms, evs[-1].t_ms  # settled from the third pass on
        for t in range(t0, t1, 1000):
            settled[int(minute_of(period, t)), team] += 1
    seconds = np.full(last + 1, 60.0)
    seconds[last] = max(1.0, (minute_of(*until) - last) * 60)  # the minute in play counts only what has been played
    pct = np.clip(settled / seconds[:, None] * 100, 0, 100)
    return [{"minute": m, md.home: round(float(h)), md.away: round(float(a))} for m, (h, a) in enumerate(pct)]


def shots(md: MatchData, until: Clock) -> list[dict[str, Any]]:
    """Every shot so far with its xG, each club shown attacking to the right (`SHOTS`)."""
    if "xg" not in metrics.REGISTRY:
        raise StatUnavailable("The xG model isn't available yet")
    out = []
    for e in md.events:
        if (e.period, e.t_ms) > until or e.type != "shot" or not e.start_xy or e.outcome not in SHOT_OUTCOMES:
            continue
        x, y = md.to_team(e.period, e.team_id, np.asarray(e.start_xy, dtype=float))
        out.append({"minute": int(minute_of(e.period, e.t_ms)), "team": e.team_id, "playerId": e.player_id,
                    "x": round(float(x), 1), "y": round(float(y), 1),
                    "xg": round(float(metrics.compute(md, "xg", event_id=e.event_id).value), 2),
                    "outcome": SHOT_OUTCOMES[e.outcome]})
    return out


def shape(md: MatchData, until: Clock) -> list[dict[str, Any]]:
    """Shape and pressure in 5-minute bins (`SHAPE`): the away club's back-line height, width and compactness, and
    the home club's press height (its four most advanced outfielders' distance from their own goal while the away
    club has the ball), in metres."""
    poss = Possession(md)
    away, home = md.columns_of(md.away), md.columns_of(md.home)
    bins: dict[int, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for p, pf, end in _upto(md, until):
        for i in range(0, end + 1, STEP):
            b = int(minute_of(p, int(pf.t_ms[i])) // 5) * 5
            a_xy = pf.xy[i, away].astype(float)
            a_xy = md.to_team(p, md.away, a_xy[~np.isnan(a_xy[:, 0])])
            if len(a_xy) >= 8:
                xs = np.sort(a_xy[:, 0])
                bins[b]["line"].append(float(xs[1:5].mean()))
                bins[b]["width"].append(float(np.percentile(a_xy[:, 1], 95) - np.percentile(a_xy[:, 1], 5)))
                bins[b]["compact"].append(float(xs[-1] - xs[1]))
            if poss.at(p, int(pf.t_ms[i])) == md.away:
                h_xy = pf.xy[i, home].astype(float)
                h_xy = md.to_team(p, md.home, h_xy[~np.isnan(h_xy[:, 0])])
                if len(h_xy) >= 8:
                    bins[b]["press"].append(float(np.sort(h_xy[:, 0])[-4:].mean()))
    mean = lambda v: round(float(np.mean(v)), 1) if v else None  # noqa: E731
    return [{"minute": b, f"{md.away}Line": mean(s["line"]), f"{md.away}Width": mean(s["width"]),
             f"{md.away}Compact": mean(s["compact"]), f"{md.home}Press": mean(s["press"])}
            for b, s in sorted(bins.items())]


def pass_network(md: MatchData, until: Clock, club: str | None = None) -> dict[str, Any]:
    """A club's pass network so far (`PASS_NETWORK`): each player at the average place they passed from and received,
    with their touches, and passes between each pair. Shown with the home club attacking to the right."""
    club = club or md.home
    spots: dict[str, list[np.ndarray]] = defaultdict(list)
    touches: Counter[str] = Counter()
    pairs: Counter[tuple[str, str]] = Counter()
    for e in md.events:
        if (e.period, e.t_ms) > until or e.team_id != club or not e.player_id:
            continue
        touches[e.player_id] += 1
        if e.type != "pass" or e.outcome != "complete" or not e.recipient_id or not e.start_xy or not e.end_xy:
            continue
        spots[e.player_id].append(_home_view(md, e.period, e.start_xy))
        spots[e.recipient_id].append(_home_view(md, e.period, e.end_xy))
        pairs[tuple(sorted((e.player_id, e.recipient_id)))] += 1
    nodes = [{"id": pid, "num": md.player_number(pid), "x": round(float(np.mean([s[0] for s in xy])), 1),
              "y": round(float(np.mean([s[1] for s in xy])), 1), "touches": touches[pid]}
             for pid, xy in sorted(spots.items())]
    edges = [{"from": a, "to": b, "n": n} for (a, b), n in pairs.most_common() if n >= 3]
    return {"nodes": nodes, "edges": edges}


def occupancy(md: MatchData, player_id: str, until: Clock, cols: int = 21, rows: int = 14) -> list[float]:
    """Minutes a player spent in each cell of a coarse grid, row by row from the top (`occupancy`)."""
    if player_id not in md.players:
        raise StatUnavailable(f"No player {player_id} in {md.match_id}")
    col = md.players.index(player_id)
    grid = np.zeros((rows, cols))
    for p, pf, end in _upto(md, until):
        xy = pf.xy[: end + 1: STEP, col].astype(float)
        xy = _home_view(md, p, xy[~np.isnan(xy[:, 0])])
        c = np.clip((xy[:, 0] / PITCH_LENGTH * cols).astype(int), 0, cols - 1)
        r = np.clip(((PITCH_WIDTH - xy[:, 1]) / PITCH_WIDTH * rows).astype(int), 0, rows - 1)
        np.add.at(grid, (r, c), STEP * FRAME_MS / 60000)
    return [round(float(v), 2) for v in grid.ravel()]


def run_map(md: MatchData, cands: list[Candidate], player_id: str, until: Clock) -> list[dict[str, Any]]:
    """A player's runs so far that the detectors named, by type (`runMap`)."""
    out = []
    for c in _seen(cands, until):
        if c.creator_id != player_id or c.type not in RUN_TYPES or not c.run_from or not c.run_to:
            continue
        a, b = _home_view(md, c.period, c.run_from), _home_view(md, c.period, c.run_to)
        out.append({"type": RUN_TYPES[c.type], "from": [round(float(a[0]), 1), round(float(a[1]), 1)],
                    "to": [round(float(b[0]), 1), round(float(b[1]), 1)], "minute": int(minute_of(c.period, c.t_start_ms))})
    return out


def distance_series(md: MatchData, player_id: str, until: Clock) -> list[dict[str, Any]]:
    """Metres covered in each 5-minute spell (`distanceSeries`)."""
    if player_id not in md.players:
        raise StatUnavailable(f"No player {player_id} in {md.match_id}")
    col = md.players.index(player_id)
    bins: Counter[int] = Counter()
    for p, pf, end in _upto(md, until):
        xy = pf.xy[: end + 1, col].astype(float)
        step = np.linalg.norm(np.diff(xy, axis=0), axis=1)
        minutes = np.array([minute_of(p, int(t)) for t in pf.t_ms[1: end + 1: HZ]])
        per_second = np.add.reduceat(np.nan_to_num(step), np.arange(0, len(step), HZ)) if len(step) else []
        for m, d in zip(minutes, per_second, strict=False):
            bins[int(m // 5) * 5] += float(d)
    return [{"minute": b, "metres": round(v)} for b, v in sorted(bins.items())]


# ------------------------------------------------------------------------------------------------ the API's entry


MATCH_STATS = ("leaders", "momentum", "control_index", "shots", "shape", "pass_network")
PLAYER_STATS = ("focus", "occupancy", "run_map", "distance_series")


def compute(md: MatchData, cands: list[Candidate], name: str, until: Clock, player_id: str | None = None,
            window: tuple[Clock, Clock] | None = None) -> Any:
    """One named stat, up to `until`. Player stats need `player_id`; `focus` also takes the moment's window."""
    if name in PLAYER_STATS and not player_id:
        raise StatUnavailable(f"{name} needs a player_id")
    match name:
        case "leaders":
            return leaders(md, cands, until)
        case "momentum":
            return momentum(md, until)
        case "control_index":
            return control_index(md, until)
        case "shots":
            return shots(md, until)
        case "shape":
            return shape(md, until)
        case "pass_network":
            return pass_network(md, until)
        case "focus":
            return focus(md, cands, player_id, window or (until, until))
        case "occupancy":
            return occupancy(md, player_id, until)
        case "run_map":
            return run_map(md, cands, player_id, until)
        case "distance_series":
            return distance_series(md, player_id, until)
    raise StatUnavailable(f"Unknown stat {name}; known: {', '.join(MATCH_STATS + PLAYER_STATS)}")
