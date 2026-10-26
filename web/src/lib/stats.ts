// Chart data for the showcase match (PRD 16.4). Deterministic, synthetic and consistent with the moment.
// The evaluation charts (fidelity, reliability, benchmark) are sample data until the evaluation pipeline publishes.
import { PLAYERS, player, type Team, type XY } from './match';
import { focusStats } from './content';
import { served } from './served';

/** Deterministic noise in [0, 1). */
export const rnd = (i: number, k = 0) => {
  const v = Math.sin(i * 12.9898 + k * 78.233) * 43758.5453;
  return v - Math.floor(v);
};
const round = (v: number, d = 1) => Math.round(v * 10 ** d) / 10 ** d;
const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));

/** Space-value flow per minute: above zero favours Kestrel Bay, below favours Ashmoor (the momentum ribbon). */
export const momentum = (m: number) => clamp(0.5 * Math.sin(m / 6.5) + 0.28 * Math.sin(m / 2.7 + 1.3) + 0.16 * Math.sin(m / 1.1 + 0.4) + (m > 54 ? 0.3 : 0), -1, 1);
export const MOMENTUM = Array.from({ length: 64 }, (_, minute) => ({ minute, value: round(momentum(minute), 2) }));
/** Big chances, marked on the ribbon. */
export const BIG_CHANCES: readonly { minute: number; team: Team }[] = [
  { minute: 12, team: 'kes' },
  { minute: 27, team: 'ash' },
  { minute: 41, team: 'kes' },
  { minute: 63, team: 'kes' },
];

/** Control versus chaos (PRD 9.2): how much of each minute was settled possession, 0–100, per team. */
export const CONTROL_INDEX = Array.from({ length: 64 }, (_, minute) => {
  const kes = clamp(52 + 18 * Math.sin(minute / 8.5) + 9 * Math.sin(minute / 2.9 + 0.6) + (minute > 54 ? 8 : 0) + (rnd(minute) - 0.5) * 6, 8, 92);
  return { minute, kes: round(kes, 0), ash: round(clamp(100 - kes - 12 - 8 * Math.abs(Math.sin(minute / 4)), 4, 90), 0) };
});

/** Kestrel Bay's pass network: average positions this match and passes between pairs. */
export const PASS_NETWORK = (() => {
  const nodes = PLAYERS.filter((p) => p.team === 'kes').map((p) => {
    const [, x, y] = p.keys[0];
    // Whole-match averages sit deeper and more central than the moment's positions.
    return { id: p.id, num: p.num, x: round(x * 0.78 + 4), y: round(34 + (y - 34) * 0.85), touches: p.role === 'GK' ? 28 : 30 + Math.round(rnd(p.num, 3) * 40) };
  });
  const pairs: [number, number, number][] = [
    [1, 4, 9], [1, 5, 8], [4, 5, 14], [4, 6, 12], [5, 6, 13], [4, 2, 10], [5, 3, 9], [6, 8, 18], [8, 10, 15], [6, 10, 7],
    [2, 7, 11], [3, 11, 9], [8, 7, 6], [8, 11, 8], [10, 9, 5], [7, 9, 4], [11, 9, 3], [10, 7, 6], [10, 11, 5], [2, 8, 7],
  ];
  const id = (n: number) => `kes-${String(n).padStart(2, '0')}`;
  const edges = pairs.map(([a, b, n]) => ({ from: id(a), to: id(b), n }));
  return { nodes, edges };
})();

export interface Shot {
  minute: number;
  team: Team;
  playerId: string;
  /** Pitch position in metres, with both teams shown attacking to the right. */
  x: number;
  y: number;
  xg: number;
  outcome: 'goal' | 'saved' | 'off target' | 'blocked';
}

export const SHOTS: readonly Shot[] = [
  { minute: 12, team: 'kes', playerId: 'kes-09', x: 92, y: 30, xg: 0.12, outcome: 'saved' },
  { minute: 27, team: 'kes', playerId: 'kes-08', x: 81, y: 44, xg: 0.04, outcome: 'off target' },
  { minute: 41, team: 'kes', playerId: 'kes-10', x: 96, y: 36, xg: 0.21, outcome: 'saved' },
  { minute: 55, team: 'kes', playerId: 'kes-07', x: 90, y: 22, xg: 0.06, outcome: 'blocked' },
  { minute: 63, team: 'kes', playerId: 'kes-10', x: 89.4, y: 40, xg: 0.31, outcome: 'goal' },
  { minute: 18, team: 'ash', playerId: 'ash-09', x: 91, y: 38, xg: 0.09, outcome: 'off target' },
  { minute: 27, team: 'ash', playerId: 'ash-10', x: 96, y: 30, xg: 0.34, outcome: 'saved' },
  { minute: 50, team: 'ash', playerId: 'ash-11', x: 85, y: 45, xg: 0.04, outcome: 'blocked' },
];

/** Shape and pressure in 5-minute bins: back-line height (m from own goal), width and compactness, in metres. */
export const SHAPE = Array.from({ length: 13 }, (_, i) => {
  const minute = i * 5;
  return {
    minute,
    ashLine: round(clamp(34 - 6 * Math.sin(i / 2.4) - (minute > 54 ? 4 : 0) + (rnd(i, 2) - 0.5) * 3, 18, 42)),
    ashWidth: round(clamp(44 - 4 * Math.sin(i / 1.7) + (rnd(i, 4) - 0.5) * 3, 34, 52)),
    ashCompact: round(clamp(31 + 5 * Math.sin(i / 2.1 + 1) + (minute > 54 ? 4 : 0), 24, 42)),
    kesPress: round(clamp(48 + 7 * Math.sin(i / 2.6) + (minute > 54 ? 5 : 0), 36, 62)),
  };
});

/** Where a player spent the match, as minutes per cell on a coarse grid (the heat map). */
export function occupancy(id: string, cols = 21, rows = 14): number[] {
  // The backend computes the default 21 × 14 grid.
  const computed = cols === 21 && rows === 14 ? served<number[] | null>(`occupancy:${id}`, null) : null;
  if (computed) return computed;
  const p = player(id);
  const [, x0, y0] = p.keys[0];
  const ax = p.team === 'kes' ? x0 * 0.78 + 4 : 105 - (105 - x0) * 0.78 - 4;
  const ay = 34 + (y0 - 34) * 0.85;
  const sx = p.role === 'GK' ? 5 : p.role === 'CB' ? 9 : 14;
  const sy = p.role === 'GK' ? 6 : p.role.endsWith('B') || p.role.startsWith('R') || p.role.startsWith('L') ? 9 : 11;
  const out: number[] = [];
  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      const x = ((c + 0.5) * 105) / cols;
      const y = 68 - ((r + 0.5) * 68) / rows;
      const g = Math.exp(-(((x - ax) / sx) ** 2 + ((y - ay) / sy) ** 2) / 2);
      out.push(round(g * 6 + rnd(r * cols + c, p.num) * 0.4, 2));
    }
  }
  return out;
}

export interface RunLine {
  type: 'Decoy' | 'In behind' | 'Overlap' | 'Check to ball';
  from: XY;
  to: XY;
  minute: number;
}

/** A player's off-ball runs this match, by type (the run map). The last decoy run is this moment's. */
export function runMap(id: string): RunLine[] {
  const computed = served<RunLine[] | null>(`run_map:${id}`, null);
  if (computed) return computed;
  const p = player(id);
  const [, x0, y0] = p.keys[0];
  const dir = p.team === 'kes' ? 1 : -1;
  const out: RunLine[] = [];
  let k = 0;
  for (const { type, n } of focusStats(id).runsByType) {
    for (let i = 0; i < n; i++, k++) {
      const fx = clamp(x0 - dir * (6 + rnd(k, p.num) * 14), 5, 100);
      const fy = clamp(y0 + (rnd(k, p.num + 1) - 0.5) * 24, 4, 64);
      const len = type === 'Check to ball' ? 8 : type === 'Overlap' ? 18 : 15;
      const ang = type === 'Check to ball' ? Math.PI + (rnd(k, 5) - 0.5) : type === 'Decoy' ? (rnd(k, 6) > 0.5 ? 1 : -1) * (0.9 + rnd(k, 7) * 0.4) : (rnd(k, 8) - 0.5) * 0.6;
      const to: XY = [clamp(fx + dir * Math.cos(ang) * len, 3, 102), clamp(fy + Math.sin(ang) * len, 3, 65)];
      out.push({ type, from: [round(fx), round(fy)], to: [round(to[0]), round(to[1])], minute: Math.round(6 + rnd(k, 9) * 55) });
    }
  }
  if (id === 'kes-09') out.push({ type: 'Decoy', from: [84, 34], to: [91, 53], minute: 63 });
  return out;
}

/** Distance per 5 minutes, in metres (the physical sparkline). */
export function distanceSeries(id: string): { minute: number; metres: number }[] {
  const computed = served<{ minute: number; metres: number }[] | null>(`distance_series:${id}`, null);
  if (computed) return computed;
  const p = player(id);
  const base = p.role === 'GK' ? 300 : 640;
  return Array.from({ length: 13 }, (_, i) => ({ minute: i * 5, metres: Math.round(base + Math.sin(i / 2 + p.num) * 60 + rnd(i, p.num) * 70 - (i > 8 ? 30 : 0)) }));
}

// ---------- The same series as the backend computes them, when it does (INTEGRATION.md 6.5) ----------

export const controlIndex = () => served('control_index', CONTROL_INDEX);
export const shape = () => served('shape', SHAPE);
export const passNetwork = () => served('pass_network', PASS_NETWORK);
/** Shots arrive only once the backend's xG model is in place; until then the stand-in's stay. */
export const shots = (): readonly Shot[] => served('shots', SHOTS);

// ---------- Evaluation (sample data) ----------

/** The standard normal's inverse cumulative distribution (Acklam's approximation, accurate to about 1e-9). */
function invNorm(p: number): number {
  const a = [-39.69683028665376, 220.9460984245205, -275.9285104469687, 138.357751867269, -30.66479806614716, 2.506628277459239];
  const b = [-54.47609879822406, 161.5858368580409, -155.6989798598866, 66.80131188771972, -13.28068155288572];
  const c = [-0.007784894002430293, -0.3223964580411365, -2.400758277161838, -2.549732539343734, 4.374664141464968, 2.938163982698783];
  const d = [0.007784695709041462, 0.3224671290700398, 2.445134137142996, 3.754408661907416];
  const tail = (q: number) => (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1);
  if (p < 0.02425) return tail(Math.sqrt(-2 * Math.log(p)));
  if (p > 1 - 0.02425) return -tail(Math.sqrt(-2 * Math.log(1 - p)));
  const q = p - 0.5;
  const r = q * q;
  return ((((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q) / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1);
}

/**
 * A sample of `n` drawn one from each of `n` equal slices of a distribution (stratified), so a chart shows the
 * distribution rather than the luck of the draw. `at` turns a standard normal value into the statistic.
 */
const strata = (n: number, k: number, at: (z: number) => number) => Array.from({ length: n }, (_, i) => round(at(invNorm((i + 0.15 + 0.7 * rnd(i, k)) / n)), 1));
const normalOf = (mean: number, sd: number, floor: number) => (z: number) => Math.max(floor, mean + sd * z);
/** Right-skewed and never negative, like pass lengths and possession times. */
const logNormalOf = (median: number, sigma: number) => (z: number) => median * Math.exp(sigma * z);

/** Synthetic against calibration distributions (PRD 12.6, 16.4), drawn as overlaid ECDFs. */
export const FIDELITY = [
  { metric: 'Sprint distance per player-match', unit: 'm', synthetic: strata(200, 1, normalOf(251, 72, 12)), calibration: strata(200, 2, normalOf(256, 70, 12)) },
  { metric: 'Pass length', unit: 'm', synthetic: strata(200, 3, logNormalOf(15.4, 0.56)), calibration: strata(200, 4, logNormalOf(15, 0.6)) },
  { metric: 'Possession duration', unit: 's', synthetic: strata(200, 5, logNormalOf(9.6, 0.62)), calibration: strata(200, 6, logNormalOf(10.1, 0.6)) },
];

/** Predicted against observed rates per probability bin (reliability diagrams). */
export const RELIABILITY = {
  'Pass completion (difficulty model)': [0.1, 0.25, 0.4, 0.55, 0.7, 0.85, 0.95].map((p, i) => ({ predicted: p, observed: round(clamp(p + (rnd(i, 11) - 0.5) * 0.08, 0, 1), 2), n: 400 + i * 220 })),
  'Shot xG': [0.03, 0.08, 0.15, 0.25, 0.4, 0.6].map((p, i) => ({ predicted: p, observed: round(clamp(p + (rnd(i, 12) - 0.5) * 0.07, 0, 1), 2), n: 900 - i * 130 })),
  'Space value': [0.05, 0.12, 0.2, 0.3, 0.45].map((p, i) => ({ predicted: p, observed: round(clamp(p + (rnd(i, 13) - 0.5) * 0.06, 0, 1), 2), n: 600 - i * 90 })),
};

/**
 * OffBall-Bench by agent version, with the two published baselines (PRD 19.1): sample values until Foundry
 * evaluations publish results. Recall of planted moments, precision of aired claims, median credit error (%) and
 * graphic latency p95 (s).
 */
export const BENCH = [
  { version: 'Rules-only baseline', short: 'Rules only', recall: 0.48, precision: 0.88, creditError: 19.4, latency: 0.6 },
  { version: 'Single-agent baseline', short: 'Single agent', recall: 0.61, precision: 0.82, creditError: 14.2, latency: 4.8 },
  { version: 'Crew v1', short: 'Crew v1', recall: 0.74, precision: 0.93, creditError: 9.6, latency: 2.9 },
  { version: 'Crew v5, after Agent Optimizer', short: 'Crew v5', recall: 0.87, precision: 0.98, creditError: 5.8, latency: 2.3 },
];

/** Each released crew version on the test split (PRD 14.9 release gate): sample values, as BENCH. */
export const BENCH_RUNS = [
  { version: 'v1', date: '2026-06-02', recall: 0.74, invented: 0.62, credit: 0.68 },
  { version: 'v2', date: '2026-06-16', recall: 0.77, invented: 0.48, credit: 0.72 },
  { version: 'v3', date: '2026-06-30', recall: 0.81, invented: 0.33, credit: 0.77 },
  { version: 'v4', date: '2026-07-14', recall: 0.84, invented: 0.27, credit: 0.79 },
  { version: 'v5', date: '2026-07-28', recall: 0.87, invented: 0.21, credit: 0.82 },
];
