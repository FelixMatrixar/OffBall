// Control fields per 25 Hz frame, computed in a worker and blended for display frames in between.
import { scenarioTracks } from '../decisions';
import { FIELD_GRID, controlField, lerpField, type Body, type Grid } from '../field';
import { COUNTERFACTUAL, at, player } from '../match';
import { tOf } from './emitter';
import type { FrameBuffer } from './frames';
import type { TrackedFrame } from './types';

/** The world a field is for: as played, without No. 9's run, or with one decision changed (an option's ID). */
export type FieldVariant = 'real' | 'cf' | (string & {});

/**
 * Bodies for a frame. The counterfactual swaps in where No. 9 and No. 5 would have been (PRD 10.2); a changed decision
 * swaps in every player it moved (PRD 10.10).
 */
export function bodiesOf(frame: TrackedFrame, variant: FieldVariant): Body[] {
  const t = tOf(frame.t_ms);
  const changed = variant === 'real' ? null : variant === 'cf' ? COUNTERFACTUAL : scenarioTracks(variant);
  return Object.entries(frame.players).map(([id, [x, y]]) => {
    const team = player(id).team;
    const track = changed?.[id];
    if (track) {
      const [cx, cy] = at(track, t);
      return { team, x: cx, y: cy };
    }
    return { team, x, y };
  });
}

export class FieldCache {
  private cache = new Map<string, Float32Array>();
  private pending = new Set<string>();
  private worker: Worker | null = null;
  private listeners = new Set<() => void>();
  /** One output buffer per variant, so the side-by-side view can hold both fields in the same frame. */
  private scratch = new Map<FieldVariant, Float32Array>();

  constructor(readonly grid: Grid = FIELD_GRID) {
    try {
      this.worker = new Worker(new URL('./field.worker.ts', import.meta.url), { type: 'module' });
      this.worker.onmessage = (e: MessageEvent<{ key: string; field: Float32Array }[]>) => {
        for (const r of e.data) {
          this.cache.set(r.key, r.field);
          this.pending.delete(r.key);
        }
        this.listeners.forEach((l) => l());
      };
      this.worker.onerror = () => {
        this.worker = null;
      };
    } catch {
      // No workers here: fields are computed on demand on the main thread instead.
      this.worker = null;
    }
  }

  private key = (frame: TrackedFrame, variant: FieldVariant) => `${variant}:${frame.frame_id}`;

  /** Queues every frame not yet computed, in batches, so the main thread never waits for a field. */
  prime(frames: readonly TrackedFrame[], variant: FieldVariant): void {
    if (!this.worker) return;
    const batch: { key: string; bodies: Body[]; grid: Grid }[] = [];
    for (const f of frames) {
      const key = this.key(f, variant);
      if (this.cache.has(key) || this.pending.has(key)) continue;
      this.pending.add(key);
      batch.push({ key, bodies: bodiesOf(f, variant), grid: this.grid });
      if (batch.length === 25) this.worker.postMessage(batch.splice(0));
    }
    if (batch.length) this.worker.postMessage(batch);
  }

  private fieldOf(frame: TrackedFrame, variant: FieldVariant): Float32Array {
    const key = this.key(frame, variant);
    let f = this.cache.get(key);
    if (!f) {
      f = controlField(bodiesOf(frame, variant), this.grid);
      this.cache.set(key, f);
      this.pending.delete(key);
    }
    return f;
  }

  /** The field at a display time: a blend of the frames either side of it. Reuses one buffer per variant, so copy it to keep it. */
  at(buffer: FrameBuffer, t_ms: number, variant: FieldVariant): Float32Array | null {
    const all = buffer.all;
    if (!all.length) return null;
    const i = buffer.indexAt(t_ms);
    const f0 = all[i];
    const f1 = all[Math.min(all.length - 1, i + 1)];
    const u = f1 === f0 ? 0 : Math.max(0, Math.min(1, (t_ms - f0.t_ms) / (f1.t_ms - f0.t_ms)));
    let out = this.scratch.get(variant);
    if (!out) this.scratch.set(variant, (out = new Float32Array(this.grid.cols * this.grid.rows)));
    return lerpField(this.fieldOf(f0, variant), this.fieldOf(f1, variant), u, out);
  }

  onReady(fn: () => void): () => void {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  }

  clear(): void {
    this.cache.clear();
    this.pending.clear();
  }
}
