// A what-if on the pitch, as graphics the 2D renderer already draws: dashed ghosts where the players free to react
// would have been, and the gap, open or shut (PRD 15.2: anything counterfactual is dashed, never solid).
import type { Overlay } from '../feed/types';
import type { Key } from '../match';
import type { WhatIf } from './api';

/** How long either side of a what-if its ghosts stay on the pitch. */
export const GHOST_BEFORE_MS = 500;
export const GHOST_AFTER_MS = 2500;

/** When a what-if's ghosts leave the pitch: a while after the last of them stops, or after the measurement. */
export function whatIfEnd(w: WhatIf): number {
  const last = Math.max(w.t_measure_ms, ...Object.values(w.tracks).map((t) => (t.length ? t[t.length - 1][0] : 0)));
  return last + GHOST_AFTER_MS;
}

const blank = (o: Partial<Overlay> & Pick<Overlay, 'overlay_id' | 'kind' | 'period' | 't_start_ms' | 't_end_ms'>): Overlay => ({
  rev: 1,
  match_id: '',
  layer: 'pitch',
  priority: 0,
  mode: 'casual',
  anchors: {},
  text: {},
  a11y_text: {},
  evidence_ids: [],
  confidence: 1,
  approval: 'auto',
  ai_generated: false,
  labels: [],
  ...o,
});

/** The what-if's ghosts and gap as graphics the renderer already draws: dashed paths, and a ring open or shut. */
export function whatIfItems(w: WhatIf): Overlay[] {
  const t0 = w.t_start_ms - GHOST_BEFORE_MS;
  const t1 = whatIfEnd(w);
  const ring = blank({
    overlay_id: `${w.counterfactual_id}-ring`,
    kind: 'gap_ring',
    period: w.period,
    t_start_ms: t0,
    t_end_ms: t1,
    anchors: { centre_xy: w.ring.at },
    data: { rx_m: w.ring.rx_m, ry_m: w.ring.ry_m, shut: !w.ring.open },
  });
  const ghosts = Object.entries(w.tracks).map(([pid, track]) =>
    blank({
      overlay_id: `${w.counterfactual_id}-${pid}`,
      kind: 'ghost',
      period: w.period,
      t_start_ms: t0,
      t_end_ms: t1,
      anchors: { player_id: pid },
      counterfactual_id: w.counterfactual_id,
      data: { track: track.map(([t, x, y]) => [t / 1000, x, y] as Key), path: 'trail', from: w.t_start_ms / 1000 },
    }),
  );
  return [ring, ...ghosts];
}

