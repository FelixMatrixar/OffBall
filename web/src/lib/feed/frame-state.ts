// Everything a view needs for one display frame, from the feed's 25 Hz frames (VIS-1: one clock, one source).
import { gapControl } from '../field';
import { A5_START, PLAYERS, backLineX, distance, type XY } from '../match';
import { ms } from './emitter';
import type { FeedStore } from './store';

export interface FrameState {
  t: number;
  t_ms: number;
  pos: Record<string, XY>;
  ball: [number, number, number];
  ballXY: XY;
  /** Four fading ball positions during passes and shots (PRD 16.10). */
  trail: XY[];
  field: Float32Array | null;
  cfField: Float32Array | null;
  /** Gap-zone control change since the build-up, in points, for the field on show. */
  gapPts: number;
  displacement: number;
  depth: number;
  speedOf: (id: string) => number;
  ahead: (id: string, lead: number) => XY;
}

const baseline = new WeakMap<FeedStore, number>();

/**
 * `copy: false` hands back the field cache's shared buffers, for a renderer that draws them straight away; React
 * views keep the default copies, because they draw in an effect after the buffers may have moved on.
 */
export function frameState(store: FeedStore, t: number, { cf = false, alt, fields = true, copy = true }: { cf?: boolean; alt?: string | null; fields?: boolean; copy?: boolean } = {}): FrameState {
  const t_ms = ms(t);
  const s = store.frames.sample(t_ms);
  const pos: Record<string, XY> = s?.pos ?? Object.fromEntries(PLAYERS.map((p) => [p.id, [p.keys[0][1], p.keys[0][2]] as XY]));
  const ball: [number, number, number] = s?.ball ?? [55.8, 39.3, 0.11];
  const ballXY: XY = [ball[0], ball[1]];
  const moving = t > 4.2 && t < 7;
  const trail: XY[] = moving
    ? [1, 2, 3, 4].map((i) => {
        const b = store.frames.sample(t_ms - i * 70)?.ball ?? ball;
        return [b[0], b[1]] as XY;
      })
    : [];

  // The baseline comes first: the cache reuses one buffer per variant, so it must not overwrite this frame's field.
  if (!baseline.has(store) && store.frames.first) {
    const first = store.fields.at(store.frames, store.frames.first.t_ms, 'real');
    if (first) baseline.set(store, gapControl(first));
  }
  const base = baseline.get(store) ?? 0.5;
  const real = fields ? store.fields.at(store.frames, t_ms, 'real') : null;
  // The other world: without No. 9's run, or with one decision changed (`alt`, an option's ID).
  const without = fields && cf ? store.fields.at(store.frames, t_ms, alt ?? 'cf') : null;
  const field = real && copy ? real.slice() : real;
  const cfField = without && copy ? without.slice() : without;
  const shown = cf ? cfField : field;
  const gapPts = shown ? Math.round((gapControl(shown) - base) * 100) : 0;

  const speeds = new Map<string, number>();
  const prev = store.frames.sample(t_ms - 200)?.pos;
  const speedOf = (id: string) => {
    if (!speeds.has(id)) speeds.set(id, prev && pos[id] && prev[id] && t > 0.2 ? (distance(pos[id], prev[id]) / 0.2) * 3.6 : 0);
    return speeds.get(id) ?? 0;
  };
  const ahead = (id: string, lead: number): XY => store.frames.sample(t_ms + lead * 1000)?.pos[id] ?? pos[id];

  return {
    t,
    t_ms,
    pos,
    ball,
    ballXY,
    trail,
    field,
    cfField,
    gapPts,
    displacement: pos['ash-05'] ? distance(pos['ash-05'], A5_START) : 0,
    depth: 105 - backLineX(pos),
    speedOf,
    ahead,
  };
}
