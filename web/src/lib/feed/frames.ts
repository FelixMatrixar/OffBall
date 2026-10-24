// 25 Hz tracked frames, sampled at the display's refresh rate (VIS-2). Positions use cubic Hermite curves
// with velocities from neighbouring frames, and never run more than 200 ms past the newest frame (PRD 16.2).
import type { XY } from '../match';
import type { TrackedFrame } from './types';

const MAX_EXTRAPOLATE_MS = 200;

export interface Sample {
  t_ms: number;
  pos: Record<string, XY>;
  ball: [number, number, number];
  /** Index of the frame at or before t, and how far towards the next one. */
  index: number;
  u: number;
}

function hermite(p0: number, p1: number, m0: number, m1: number, u: number, dt: number): number {
  const u2 = u * u;
  const u3 = u2 * u;
  return (2 * u3 - 3 * u2 + 1) * p0 + (u3 - 2 * u2 + u) * dt * m0 + (-2 * u3 + 3 * u2) * p1 + (u3 - u2) * dt * m1;
}

export class FrameBuffer {
  private frames: TrackedFrame[] = [];
  private ids = new Set<number>();

  get size(): number {
    return this.frames.length;
  }

  get first(): TrackedFrame | undefined {
    return this.frames[0];
  }

  get latest(): TrackedFrame | undefined {
    return this.frames[this.frames.length - 1];
  }

  get all(): readonly TrackedFrame[] {
    return this.frames;
  }

  /** Adds a frame, ignoring duplicates and keeping time order, so late or reordered frames slot in. */
  add(frame: TrackedFrame): boolean {
    if (this.ids.has(frame.frame_id)) return false;
    this.ids.add(frame.frame_id);
    const last = this.latest;
    if (!last || frame.t_ms > last.t_ms) this.frames.push(frame);
    else {
      let i = this.frames.length - 1;
      while (i >= 0 && this.frames[i].t_ms > frame.t_ms) i--;
      this.frames.splice(i + 1, 0, frame);
    }
    return true;
  }

  clear(): void {
    this.frames = [];
    this.ids.clear();
  }

  /** Drops frames older than `keepMs` before the newest one (the offline buffer keeps 10 minutes). */
  trim(keepMs: number): void {
    const last = this.latest;
    if (!last) return;
    const cut = this.frames.findIndex((f) => f.t_ms >= last.t_ms - keepMs);
    if (cut > 0) {
      for (const f of this.frames.slice(0, cut)) this.ids.delete(f.frame_id);
      this.frames = this.frames.slice(cut);
    }
  }

  /** Index of the last frame at or before t_ms (binary search). */
  indexAt(t_ms: number): number {
    let lo = 0;
    let hi = this.frames.length - 1;
    if (hi < 0) return -1;
    if (t_ms <= this.frames[0].t_ms) return 0;
    while (lo < hi) {
      const mid = (lo + hi + 1) >> 1;
      if (this.frames[mid].t_ms <= t_ms) lo = mid;
      else hi = mid - 1;
    }
    return lo;
  }

  sample(t_ms: number): Sample | null {
    const n = this.frames.length;
    if (n === 0) return null;
    const last = this.frames[n - 1];
    const clamped = Math.min(t_ms, last.t_ms + MAX_EXTRAPOLATE_MS);
    const i = this.indexAt(clamped);
    const f0 = this.frames[i];
    const f1 = this.frames[Math.min(n - 1, i + 1)];
    const fp = this.frames[Math.max(0, i - 1)];
    const fn = this.frames[Math.min(n - 1, i + 2)];
    const dt = Math.max(1, f1.t_ms - f0.t_ms) / 1000;
    const u = f1 === f0 ? 0 : Math.max(0, Math.min(1, (clamped - f0.t_ms) / (f1.t_ms - f0.t_ms)));
    const vel = (a: TrackedFrame, b: TrackedFrame, k: number, id?: string) => {
      const span = Math.max(1, b.t_ms - a.t_ms) / 1000;
      if (id === undefined) return (b.ball[k] - a.ball[k]) / span;
      const pa = a.players[id];
      const pb = b.players[id];
      return pa && pb ? (pb[k] - pa[k]) / span : 0;
    };
    const pos: Record<string, XY> = {};
    for (const id of Object.keys(f0.players)) {
      const a = f0.players[id];
      const b = f1.players[id] ?? a;
      const xy: XY = [0, 0];
      for (const k of [0, 1] as const) {
        const m0 = vel(fp, f1, k, id);
        const m1 = vel(f0, fn, k, id);
        xy[k] = f1 === f0 ? a[k] + m0 * ((clamped - f0.t_ms) / 1000) : hermite(a[k], b[k], m0, m1, u, dt);
      }
      pos[id] = xy;
    }
    // The ball is linear between frames: passes and shots change direction too sharply for a smooth curve.
    const ball = [0, 1, 2].map((k) => f0.ball[k] + (f1.ball[k] - f0.ball[k]) * u) as [number, number, number];
    return { t_ms: clamped, pos, ball, index: i, u };
  }
}
