// The space-control field: pure functions shared by the main thread and the field worker (PRD 16.2).
import type { Team, XY } from './match';

export interface Body {
  team: Team;
  x: number;
  y: number;
}

export interface Grid {
  cols: number;
  rows: number;
}

/** About 2 m cells: the 2D view (tier C). */
export const FIELD_GRID: Grid = { cols: 53, rows: 34 };
/** 1 m cells: the 3D views at tier A. */
export const FINE_GRID: Grid = { cols: 105, rows: 68 };

/** Centre of cell i in metres; rows run from the top touchline (y = 68) down. */
export function cellCentre(i: number, g: Grid): XY {
  const r = Math.floor(i / g.cols);
  const c = i % g.cols;
  return [((c + 0.5) * 105) / g.cols, 68 - ((r + 0.5) * 68) / g.rows];
}

/** Simplified pitch control: the probability that Kestrel Bay reach (x, y) first. */
export function control(bodies: readonly Body[], x: number, y: number): number {
  let tk = Infinity;
  let ta = Infinity;
  for (const b of bodies) {
    const time = 0.7 + Math.hypot(b.x - x, b.y - y) / 7;
    if (b.team === 'kes') {
      if (time < tk) tk = time;
    } else if (time < ta) ta = time;
  }
  return 1 / (1 + Math.exp(-(ta - tk) / 0.35));
}

export function controlField(bodies: readonly Body[], g: Grid = FIELD_GRID): Float32Array {
  const out = new Float32Array(g.cols * g.rows);
  for (let i = 0; i < out.length; i++) {
    const [x, y] = cellCentre(i, g);
    out[i] = control(bodies, x, y);
  }
  return out;
}

/** Linear blend of two fields, for display frames between 25 Hz data frames. */
export function lerpField(a: Float32Array, b: Float32Array, u: number, out = new Float32Array(a.length)): Float32Array {
  for (let i = 0; i < a.length; i++) out[i] = a[i] + (b[i] - a[i]) * u;
  return out;
}

/** The zone just outside Ashmoor's box where the gap opens. */
const inGapZone = ([x, y]: XY) => x >= 84 && x <= 93 && y >= 34 && y <= 46;
const gapCells = new Map<string, number[]>();

/** The cells inside the gap zone for a grid, worked out once. */
function gapIndices(g: Grid): number[] {
  const key = `${g.cols}x${g.rows}`;
  let cells = gapCells.get(key);
  if (!cells) {
    cells = [];
    for (let i = 0; i < g.cols * g.rows; i++) if (inGapZone(cellCentre(i, g))) cells.push(i);
    gapCells.set(key, cells);
  }
  return cells;
}

/** Kestrel Bay's mean control over the gap zone, 0 to 1. */
export function gapControl(field: ArrayLike<number>, g: Grid = FIELD_GRID): number {
  const cells = gapIndices(g);
  let sum = 0;
  for (const i of cells) sum += field[i];
  return cells.length ? sum / cells.length : 0;
}

export type Segment = readonly [XY, XY];

/**
 * Joins marching-squares segments into lines through their shared ends, so a contour can be drawn as one smooth curve
 * rather than a run of straight steps. Neighbouring cells compute a shared crossing identically, so ends match exactly.
 * A line that comes back to its start is closed: its last point repeats its first.
 */
export function chains(segments: readonly Segment[]): XY[][] {
  const key = (p: XY) => `${p[0]},${p[1]}`;
  const at = new Map<string, number[]>();
  segments.forEach(([a, b], i) => {
    for (const p of [a, b]) {
      const k = key(p);
      const list = at.get(k);
      if (list) list.push(i);
      else at.set(k, [i]);
    }
  });
  const used = new Uint8Array(segments.length);
  /** The point after `p` along an unused segment that touches it, marking that segment used. */
  const next = (p: XY): XY | null => {
    for (const i of at.get(key(p)) ?? []) {
      if (used[i]) continue;
      used[i] = 1;
      const [a, b] = segments[i];
      return key(a) === key(p) ? b : a;
    }
    return null;
  };
  const out: XY[][] = [];
  segments.forEach(([a, b], i) => {
    if (used[i]) return;
    used[i] = 1;
    const line: XY[] = [a, b];
    for (let p = next(b); p; p = next(p)) line.push(p);
    if (key(line[line.length - 1]) !== key(a)) for (let p = next(a); p; p = next(p)) line.unshift(p);
    out.push(line);
  });
  return out;
}

/**
 * Iso-lines of the field by marching squares, joining cell centres. Contours at 25%, 50% and 75% control
 * let the field read without colour (PRD 16.3).
 */
export function contours(field: ArrayLike<number>, g: Grid, level: number): Segment[] {
  const out: Segment[] = [];
  const v = (c: number, r: number) => field[r * g.cols + c];
  const pt = (c: number, r: number): XY => cellCentre(r * g.cols + c, g);
  const cross = (c0: number, r0: number, c1: number, r1: number): XY => {
    const a = v(c0, r0);
    const b = v(c1, r1);
    const u = b === a ? 0.5 : (level - a) / (b - a);
    const p0 = pt(c0, r0);
    const p1 = pt(c1, r1);
    return [p0[0] + (p1[0] - p0[0]) * u, p0[1] + (p1[1] - p0[1]) * u];
  };
  for (let r = 0; r < g.rows - 1; r++) {
    for (let c = 0; c < g.cols - 1; c++) {
      const tl = v(c, r) >= level ? 8 : 0;
      const tr = v(c + 1, r) >= level ? 4 : 0;
      const br = v(c + 1, r + 1) >= level ? 2 : 0;
      const bl = v(c, r + 1) >= level ? 1 : 0;
      const idx = tl | tr | br | bl;
      if (idx === 0 || idx === 15) continue;
      const top = () => cross(c, r, c + 1, r);
      const right = () => cross(c + 1, r, c + 1, r + 1);
      const bottom = () => cross(c, r + 1, c + 1, r + 1);
      const left = () => cross(c, r, c, r + 1);
      switch (idx) {
        case 1:
        case 14:
          out.push([left(), bottom()]);
          break;
        case 2:
        case 13:
          out.push([bottom(), right()]);
          break;
        case 3:
        case 12:
          out.push([left(), right()]);
          break;
        case 4:
        case 11:
          out.push([top(), right()]);
          break;
        case 6:
        case 9:
          out.push([top(), bottom()]);
          break;
        case 7:
        case 8:
          out.push([left(), top()]);
          break;
        case 5: {
          // Saddle: resolve by the centre value.
          const centre = (v(c, r) + v(c + 1, r) + v(c + 1, r + 1) + v(c, r + 1)) / 4;
          if (centre >= level) out.push([left(), top()], [bottom(), right()]);
          else out.push([left(), bottom()], [top(), right()]);
          break;
        }
        case 10: {
          const centre = (v(c, r) + v(c + 1, r) + v(c + 1, r + 1) + v(c, r + 1)) / 4;
          if (centre >= level) out.push([left(), bottom()], [top(), right()]);
          else out.push([left(), top()], [bottom(), right()]);
          break;
        }
      }
    }
  }
  return out;
}
