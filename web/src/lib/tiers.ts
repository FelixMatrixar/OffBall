// Rendering tiers (PRD 16.2): a capability probe and a quick benchmark set the ceiling, then a frame-time monitor
// steps down when the 95th-percentile frame time stays over budget for 2 s, and back up after 10 s of headroom.
import { startTransition, useEffect, useRef, useState } from 'react';
import { FIELD_GRID, controlField } from './field';
import { PLAYERS } from './match';
import type { TierChoice, View } from './prefs';

export type Tier = 'A' | 'B' | 'C' | 'D';
export const TIER_ORDER: readonly Tier[] = ['A', 'B', 'C', 'D'];

export const TIERS: Record<Tier, { name: string; budget: number; fps: number; what: string }> = {
  A: { name: 'WebGPU', budget: 16.7, fps: 60, what: '3D with Babylon.js, the control field computed per pixel on the GPU, every overlay' },
  B: { name: 'WebGL2', budget: 16.7, fps: 60, what: '3D with Babylon.js, control field as a texture, every overlay' },
  C: { name: 'Canvas 2D', budget: 33.3, fps: 30, what: '2D view, control field on a 2 m grid, every overlay' },
  D: { name: 'Video', budget: Infinity, fps: 0, what: 'Pre-rendered clip with overlays burned in, and a live caption track' },
};

export interface Caps {
  webgpu: boolean;
  webgl2: boolean;
}

let capsPromise: Promise<Caps> | null = null;

export function probeCaps(): Promise<Caps> {
  capsPromise ??= (async () => {
    let webgl2 = false;
    try {
      webgl2 = !!document.createElement('canvas').getContext('webgl2');
    } catch {
      webgl2 = false;
    }
    let webgpu = false;
    try {
      const gpu = (navigator as Navigator & { gpu?: { requestAdapter(): Promise<unknown> } }).gpu;
      webgpu = !!gpu && !!(await gpu.requestAdapter());
    } catch {
      webgpu = false;
    }
    return { webgpu, webgl2 };
  })();
  return capsPromise;
}

/** Milliseconds per 2 m control field on this device: the start-up benchmark. */
export function cpuBenchmark(): number {
  const bodies = PLAYERS.map((p) => ({ team: p.team, x: p.keys[0][1], y: p.keys[0][2] }));
  const start = performance.now();
  for (let i = 0; i < 6; i++) controlField(bodies, FIELD_GRID);
  return (performance.now() - start) / 6;
}

const rank = (t: Tier) => TIER_ORDER.indexOf(t);
const lowerOf = (a: Tier, b: Tier): Tier => (rank(a) >= rank(b) ? a : b);
const below = (t: Tier): Tier => TIER_ORDER[Math.min(3, rank(t) + 1)];
const above = (t: Tier): Tier => TIER_ORDER[Math.max(0, rank(t) - 1)];

export const is3D = (t: Tier) => t === 'A' || t === 'B';

function stepText(from: Tier, to: Tier): string {
  if (rank(to) < rank(from)) return `Back to Tier ${to} (${TIERS[to].name}): there’s headroom again.`;
  if (to === 'B') return `Switched to Tier B (WebGL2) to hold 60 fps. Back to Tier A after 10 s of headroom.`;
  if (to === 'C') return `Switched to the 2D view (Tier C) to hold 30 fps. Back to 3D after 10 s of headroom.`;
  return `Switched to the video clip (Tier D) to keep playing smoothly. Live drawing returns after 10 s of headroom.`;
}

export interface TierState {
  /** The tier being rendered now. */
  tier: Tier;
  caps: Caps | null;
  fps: number;
  p95: number;
  notice: { id: number; text: string } | null;
  locked: boolean;
}

const OVER_FOR_MS = 2000;
const HEADROOM_FOR_MS = 10_000;
const WARMUP_MS = 1000;

/** Tiers with a renderer; the monitor never steps to one that isn't available here. */
export const AVAILABLE_TIERS: readonly Tier[] = ['A', 'B', 'C', 'D'];

export function useTiers({ view, choice, slow, available = AVAILABLE_TIERS }: { view: View; choice: TierChoice; slow: boolean; available?: readonly Tier[] }): TierState {
  const [caps, setCaps] = useState<Caps | null>(null);
  const [ceiling, setCeiling] = useState<Tier>('A');
  const [fps, setFps] = useState(60);
  const [p95, setP95] = useState(16);
  const [notice, setNotice] = useState<TierState['notice']>(null);

  useEffect(() => {
    let alive = true;
    void probeCaps().then((c) => {
      if (!alive) return;
      setCaps(c);
      // A device that takes over 6 ms per field won't hold 3D: start one tier lower.
      if (cpuBenchmark() > 6) setCeiling('B');
    });
    return () => {
      alive = false;
    };
  }, []);

  const can = (t: Tier) => available.includes(t);
  const best3D: Tier = caps?.webgpu && can('A') ? 'A' : caps?.webgl2 && can('B') ? 'B' : 'C';
  const locked = choice !== 'auto' && can(choice);
  const requested: Tier = locked ? (choice === 'A' && !caps?.webgpu ? best3D : choice === 'B' && !caps?.webgl2 ? 'C' : (choice as Tier)) : view === '2d' ? 'C' : best3D;
  const capped = lowerOf(requested, ceiling);
  const tier: Tier = locked ? requested : can(capped) ? capped : requested;

  const live = useRef({ tier, requested, locked, slow, available });
  live.current = { tier, requested, locked, slow, available };

  useEffect(() => {
    let frame = 0;
    let last = performance.now();
    let since = last;
    let lastTier = live.current.tier;
    let overSince: number | null = null;
    let roomSince: number | null = null;
    let lastEval = last;
    const samples: { at: number; dt: number }[] = [];
    const tick = (now: number) => {
      // The "slow device" switch adds 45 ms of real main-thread work a frame, about 20 fps: well under tier C's 30, so
      // the monitor reacts to it as it would to a slow phone.
      if (live.current.slow) {
        const until = performance.now() + 45;
        while (performance.now() < until) {
          /* busy */
        }
      }
      const dt = now - last;
      last = now;
      const cur = live.current;
      if (cur.tier !== lastTier) {
        lastTier = cur.tier;
        since = now;
        samples.length = 0;
        overSince = roomSince = null;
      }
      if (dt < 1000 && now - since > WARMUP_MS) samples.push({ at: now, dt });
      while (samples.length && now - samples[0].at > OVER_FOR_MS) samples.shift();
      if (now - lastEval > 500 && samples.length > 10) {
        lastEval = now;
        const sorted = samples.map((w) => w.dt).sort((a, b) => a - b);
        const p = sorted[Math.floor(sorted.length * 0.95)];
        const med = sorted[Math.floor(sorted.length / 2)];
        // The readout is a transition: React renders it in slices between frames rather than in one block.
        startTransition(() => {
          setP95(Math.round(p * 10) / 10);
          setFps(Math.round(1000 / med));
        });
        if (!cur.locked) {
          const budget = TIERS[cur.tier].budget;
          if (p > budget * 1.05) {
            overSince ??= now;
            roomSince = null;
            const to = below(cur.tier);
            if (now - overSince >= OVER_FOR_MS && cur.tier !== 'D' && cur.available.includes(to)) {
              setCeiling(to);
              setNotice({ id: now, text: stepText(cur.tier, to) });
              overSince = null;
            }
          } else {
            overSince = null;
            const up = above(cur.tier);
            const room = cur.tier !== cur.requested && rank(up) >= rank(cur.requested) && cur.available.includes(up) && p < TIERS[up].budget * 0.6;
            if (room) {
              roomSince ??= now;
              if (now - roomSince >= HEADROOM_FOR_MS) {
                setCeiling(up);
                setNotice({ id: now, text: stepText(cur.tier, up) });
                roomSince = null;
              }
            } else roomSince = null;
          }
        }
      }
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, []);

  return { tier, caps, fps, p95, notice, locked };
}
