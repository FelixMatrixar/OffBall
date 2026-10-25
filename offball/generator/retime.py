"""Moving a moment on a match's clock: earlier stoppages are held longer, and the moment's seconds between its beats
are stretched or squeezed, so each beat falls at a given time. Frames, events, intents and the answer key move
together, so the match stays consistent."""

from __future__ import annotations

import numpy as np
from scipy.interpolate import PchipInterpolator

from offball.contracts import AnswerKeyMoment
from offball.core import FRAME_MS
from offball.generator.engine.sim import MatchResult

RESTARTS = ("throw_in", "corner", "goal_kick", "free_kick", "kick_off")
MAX_HOLD_MS = 30_000  # the most any one stoppage is held over
EASE_MS = 1500.0  # the clock eases into and out of the moment's new pace over this long, so play speeds up or
# slows down smoothly


def retime_moment(result: MatchResult, answer_key: list[AnswerKeyMoment], period: int,
                  beats_ms: dict[str, int | None], targets_ms: dict[str, int], seed: int,
                  firm: tuple[str, ...] = ()) -> None:
    """Put each beat of a moment at its target time (ms, period clock). The first and the `firm` beats anchor the
    clock; any other beat is placed only where it keeps the order, and otherwise falls where the anchors put it.
    The first beat must come no later than its target."""
    names = [n for n in targets_ms if beats_ms.get(n) is not None]
    chosen = [n for i, n in enumerate(names) if i == 0 or n in firm]
    for n in names:
        if n in chosen:
            continue
        trial = sorted([*chosen, n], key=names.index)
        times = [beats_ms[m] for m in trial]
        if all(a < b for a, b in zip(times, times[1:], strict=False)):
            chosen = trial
    old = [float(beats_ms[n]) for n in chosen]
    new = [float(targets_ms[n]) for n in chosen]
    total = int(round((new[0] - old[0]) / FRAME_MS)) * FRAME_MS
    if total < 0:
        raise ValueError(f"the moment starts {-total} ms after its target")
    tail = int(round((new[-1] - old[-1]) / FRAME_MS)) * FRAME_MS
    new[0], new[-1] = old[0] + total, old[-1] + tail
    # A smooth, monotone clock through the beats, joining the shifted clock on either side.
    a = [old[0] - EASE_MS, *old, old[-1] + EASE_MS]
    b = [new[0] - EASE_MS, *new, new[-1] + EASE_MS]
    curve = PchipInterpolator(a, b)
    grid = np.arange(a[0], a[-1] + 1.0, 1.0)
    mapped = curve(grid)

    # The stoppages to hold over, latest first, each by at most MAX_HOLD_MS.
    restarts = sorted({e["t_ms"] for e in result.events if e["period"] == period and e["type"] == "pass"
                       and e.get("subtype") in RESTARTS and 0 < e["t_ms"] < a[0]}, reverse=True)
    holds: list[tuple[int, int]] = []
    left = total
    for at in restarts:
        if left <= 0:
            break
        h = min(left, MAX_HOLD_MS)
        holds.append((at - at % FRAME_MS, h))
        left -= h
    if left > 0:
        raise ValueError(f"not enough stoppages before {old[0]:.0f} ms in period {period} to hold over")
    holds.sort()

    def before(t: float) -> int:
        return sum(h for at, h in holds if at <= t)

    def forward(t: float) -> float:
        if t < a[0]:
            return t + before(t)
        if t <= a[-1]:
            return float(curve(t))
        return t + tail

    rec = result.recorders[period]
    n_new = rec.n + tail // FRAME_MS
    t_new = np.arange(n_new) * float(FRAME_MS)
    src = t_new - tail  # after the moment
    held = np.full(n_new, -1)  # the frame each held-over frame keeps, else -1
    shift = np.zeros(n_new)  # before the moment: how much later each frame now falls
    done = 0
    for at, h in holds:
        start = at + done
        held[(t_new >= start) & (t_new < start + h)] = at // FRAME_MS - 1
        shift[t_new >= start + h] += h
        done += h
    pre = t_new < b[0]
    src[pre] = t_new[pre] - shift[pre]
    warp = (t_new >= b[0]) & (t_new <= b[-1])
    src[warp] = np.interp(t_new[warp], mapped, grid)  # the curve's exact inverse
    pos = np.clip(src / FRAME_MS, 0, rec.n - 1)
    lo = np.floor(pos).astype(int)
    hi = np.minimum(lo + 1, rec.n - 1)
    w = (pos - lo)[:, None]
    xy = rec.xy[lo] * (1 - w[..., None]) + rec.xy[hi] * w[..., None]
    turn = (rec.ori[hi] - rec.ori[lo] + np.pi) % (2 * np.pi) - np.pi
    ori = rec.ori[lo] + turn * w
    ball = rec.ball[lo] * (1 - w) + rec.ball[hi] * w
    slot_player = rec.slot_player[lo]
    # While the ball is dead, players ease to a stop, mill about, and ease back into the moves they were making, so
    # the held frames join the real ones on either side at the same speed.
    rng = np.random.default_rng(seed)
    dt = FRAME_MS / 1000.0
    for f in sorted(set(held[held >= 0].tolist())):
        idx = np.nonzero(held == f)[0]
        span = (len(idx) + 1) * dt  # from real frame f to real frame f + 1, now this far apart
        tau = np.arange(1, len(idx) + 1)[:, None, None] * dt
        ease = min(1.0, span / 3)
        p0, p1 = rec.xy[f].astype(float), rec.xy[min(f + 1, rec.n - 1)].astype(float)
        v0 = (p0 - rec.xy[max(f - 1, 0)]) / dt
        v1 = (rec.xy[min(f + 2, rec.n - 1)] - p1) / dt
        out_end, in_start = p0 + v0 * ease / 2, p1 - v1 * ease / 2
        mid = np.clip((tau - ease) / max(span - 2 * ease, dt), 0.0, 1.0)
        path = out_end + (in_start - out_end) * (mid * mid * (3 - 2 * mid))
        path = np.where(tau < ease, p0 + v0 * (tau - tau ** 2 / (2 * ease)), path)
        back = span - tau
        path = np.where(back < ease, p1 - v1 * (back - back ** 2 / (2 * ease)), path)
        reach = rng.uniform(0.15, 0.6, rec.xy.shape[1])
        angle = rng.uniform(0.0, 2 * np.pi, rec.xy.shape[1])
        sway = np.sin(np.pi * mid)
        mill = np.stack([np.cos(angle), np.sin(angle)], axis=1)[None] * (sway * reach[None, :, None])
        xy[idx] = path + mill
        ori[idx], ball[idx], slot_player[idx] = rec.ori[f], rec.ball[f], rec.slot_player[f]
    rec.xy, rec.ori, rec.ball = xy.astype(rec.xy.dtype), ori.astype(rec.ori.dtype), ball.astype(rec.ball.dtype)
    rec.slot_player, rec.n = slot_player, n_new
    result.period_lengths[period] = n_new
    for rows in (result.events, result.intents):
        for e in rows:
            if e["period"] == period:
                e["t_ms"] = int(round(forward(e["t_ms"])))
    for n, row in enumerate(answer_key):
        if row.period == period:
            answer_key[n] = row.model_copy(update={"t_start_ms": int(round(forward(row.t_start_ms))),
                                                   "t_end_ms": int(round(forward(row.t_end_ms)))})
