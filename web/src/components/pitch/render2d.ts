// Tier C (PRD 16.2): the pitch's shapes, players and ball, drawn with Canvas 2D every display frame. Text isn't drawn
// here: labels live in the DOM layer above, so they stay sharp, shape correctly in every script and reach screen
// readers. Coordinates are pitch units (10 per metre, with a 3 m margin), the same grammar as the SVG components in
// overlays.tsx, so both draw the same picture in either orientation. Every entrance is built from the duration and
// easing tokens, with the same keyframes as motion.css (PRD 16.10).
import type { ActiveOverlay } from '../../lib/feed';
import { chains, contours, type Grid } from '../../lib/field';
import type { Pattern } from '../../lib/kits';
import { GOAL_AT, PASS_FROM, T_GOAL, at as along, type Key, type Team, type XY } from '../../lib/match';
import type { Density } from '../../lib/prefs';
import { SIZE, project, type Orientation } from './geometry';

export type Ease = (u: number) => number;

const clamp01 = (v: number) => (v < 0 ? 0 : v > 1 ? 1 : v);

/** A CSS cubic-bezier, solved for x the way browsers do, so canvas motion matches CSS motion. */
export function bezier(x1: number, y1: number, x2: number, y2: number): Ease {
  const cx = 3 * x1;
  const bx = 3 * (x2 - x1) - cx;
  const ax = 1 - cx - bx;
  const cy = 3 * y1;
  const by = 3 * (y2 - y1) - cy;
  const ay = 1 - cy - by;
  const x = (s: number) => ((ax * s + bx) * s + cx) * s;
  const y = (s: number) => ((ay * s + by) * s + cy) * s;
  const dx = (s: number) => (3 * ax * s + 2 * bx) * s + cx;
  return (u) => {
    if (u <= 0) return 0;
    if (u >= 1) return 1;
    let s = u;
    for (let i = 0; i < 8; i++) {
      const err = x(s) - u;
      if (Math.abs(err) < 1e-6) return y(s);
      const d = dx(s);
      if (Math.abs(d) < 1e-6) break;
      s -= err / d;
    }
    let lo = 0;
    let hi = 1;
    s = u;
    for (let i = 0; i < 30 && hi - lo > 1e-6; i++) {
      if (x(s) < u) lo = s;
      else hi = s;
      s = (lo + hi) / 2;
    }
    return y(s);
  };
}

/** An easing token's value: a cubic-bezier, or linear. */
export function parseEasing(value: string): Ease {
  const m = /cubic-bezier\(([^)]+)\)/.exec(value);
  const n = m ? m[1].split(',').map(Number) : [];
  return n.length === 4 && n.every(Number.isFinite) ? bezier(n[0], n[1], n[2], n[3]) : clamp01;
}

/** A keyframe track like a CSS animation's: the easing applies between each pair of stops. */
function track(stops: readonly (readonly [number, number])[], ease: Ease): Ease {
  return (u) => {
    if (u <= stops[0][0]) return stops[0][1];
    for (let i = 1; i < stops.length; i++) {
      const [o1, v1] = stops[i];
      if (u <= o1) {
        const [o0, v0] = stops[i - 1];
        return v0 + (v1 - v0) * ease((u - o0) / (o1 - o0));
      }
    }
    return stops[stops.length - 1][1];
  };
}

export interface Theme2D {
  bg: string;
  text: string;
  muted: string;
  halo: string;
  kes: string;
  ash: string;
  onKes: string;
  onAsh: string;
  space: string;
  spaceFill: string;
  ball: string;
  ballEdge: string;
  contour: string;
  focus: string;
  font: string;
  mono: string;
}

export interface Motion2D {
  dur: {
    quick: number;
    base: number;
    smooth: number;
    draw: number;
    hero: number;
    pop: number;
    fill: number;
    pulse: number;
    stagger: number;
  };
  ease: { standard: Ease; pop: Ease; live: Ease };
  /** The keyframes in motion.css: ob-pop, ob-pulse and ob-shake. */
  popScale: Ease;
  popOpacity: Ease;
  pulse: Ease;
  shake: Ease;
}

export interface FieldColours {
  kes: readonly number[];
  ash: readonly number[];
  max: number;
}

const DUR_TOKENS = {
  quick: 150,
  base: 220,
  smooth: 340,
  draw: 600,
  hero: 900,
  pop: 450,
  fill: 500,
  pulse: 1600,
} as const;

function msOf(raw: string, fallback: number): number {
  const v = raw.trim();
  if (v.endsWith('ms')) return parseFloat(v);
  if (v.endsWith('s')) return parseFloat(v) * 1000;
  return fallback;
}

/** The theme's colours, motion and field colours, read from the tokens in effect on an element (PRD 16.3, 16.10). */
export function readStyle(el: Element): {
  theme: Theme2D;
  motion: Motion2D;
  field: FieldColours;
} {
  const cs = getComputedStyle(el);
  const v = (name: string, fallback: string) => cs.getPropertyValue(name).trim() || fallback;
  const rgb = (name: string, fallback: string) => v(name, fallback).split(/\s+/).map(Number);
  const dur = Object.fromEntries(Object.entries(DUR_TOKENS).map(([k, f]) => [k, msOf(cs.getPropertyValue(`--dur-${k}`), f)])) as Record<keyof typeof DUR_TOKENS, number>;
  const standard = parseEasing(v('--ease-standard', 'cubic-bezier(0.2, 0, 0, 1)'));
  const pop = parseEasing(v('--ease-pop', 'cubic-bezier(0.34, 1.56, 0.64, 1)'));
  const live = parseEasing(v('--ease-live', 'cubic-bezier(0.4, 0, 0.6, 1)'));
  return {
    theme: {
      bg: v('--bg', '#0b1110'),
      text: v('--text', '#ecf1ec'),
      muted: v('--muted', '#9eb0a6'),
      halo: v('--halo', 'rgb(9 16 13 / 0.88)'),
      kes: v('--kes', '#7cc0ff'),
      ash: v('--ash', '#e2733a'),
      onKes: v('--on-kes', '#06121f'),
      onAsh: v('--on-ash', '#1e0c02'),
      space: v('--space', '#d7f25c'),
      spaceFill: v('--space-fill', 'rgb(215 242 92 / 0.12)'),
      ball: v('--ball', '#ffffff'),
      ballEdge: v('--ball-edge', '#0b1110'),
      contour: v('--contour', 'rgb(236 241 236 / 0.55)'),
      focus: v('--focus', '#d7f25c'),
      font: v('--font-body', 'system-ui, sans-serif'),
      mono: v('--font-mono', 'ui-monospace, monospace'),
    },
    motion: {
      dur: { ...dur, stagger: msOf(cs.getPropertyValue('--stagger'), 40) },
      ease: { standard, pop, live },
      popScale: track(
        [
          [0, 0.55],
          [0.6, 1.1],
          [1, 1],
        ],
        pop,
      ),
      popOpacity: track(
        [
          [0, 0],
          [0.6, 1],
          [1, 1],
        ],
        pop,
      ),
      pulse: track(
        [
          [0, 1],
          [0.5, 1.08],
          [1, 1],
        ],
        live,
      ),
      shake: track(
        [
          [0, 0],
          [0.2, -6],
          [0.4, 6],
          [0.6, -4],
          [0.8, 3],
          [1, 0],
        ],
        standard,
      ),
    },
    field: {
      kes: rgb('--kes-rgb', '124 192 255'),
      ash: rgb('--ash-rgb', '226 115 58'),
      max: Number(v('--field-max', '0.55')) || 0.55,
    },
  };
}

/**
 * The control field: Kestrel Bay's colour where they control space and Ashmoor's where Ashmoor do, fading through
 * transparent where it's contested, so the neutral midpoint is the pitch itself (PRD 16.3). One pixel per cell; the
 * browser's smooth scaling turns the grid into a continuous surface.
 */
export function paintField(ctx: CanvasRenderingContext2D, img: ImageData, field: ArrayLike<number>, grid: Grid, strength: number, o: Orientation, c: FieldColours): void {
  const data = img.data;
  const w = img.width;
  for (let r = 0; r < grid.rows; r++) {
    for (let col = 0; col < grid.cols; col++) {
      const p = field[r * grid.cols + col];
      const a = Math.min(1, Math.abs(p - 0.5) * 2 * strength) * c.max;
      const rgb = p >= 0.5 ? c.kes : c.ash;
      // Vertical: x becomes the row from the bottom, y the column from the left.
      const px = o === 'h' ? col : r;
      const py = o === 'h' ? r : grid.cols - 1 - col;
      const i = (py * w + px) * 4;
      data[i] = rgb[0];
      data[i + 1] = rgb[1];
      data[i + 2] = rgb[2];
      data[i + 3] = Math.round(a * 255);
    }
  }
  ctx.putImageData(img, 0, 0);
}

export interface DrawPlayer {
  id: string;
  team: Team;
  num: number;
  at: XY;
  dim: boolean;
  /** The followed player in Player focus: a ring with a live ripple. */
  follow: boolean;
  /** Hovered or focused: the dot grows to 132% (PRD 16.10). */
  highlight: boolean;
  /** Keyboard focus: the dot's edge takes the focus colour. */
  focusRing: boolean;
  /** Their decision can be changed, while the viewer picks one (PRD 15.12). */
  pickable?: boolean;
  pattern?: Pattern;
  colour?: string;
}

export interface Scene2D {
  o: Orientation;
  /** Wall-clock milliseconds, for entrances and live indicators. */
  now: number;
  /** Moment time in seconds. */
  t: number;
  reduced: boolean;
  theme: Theme2D;
  motion: Motion2D;
  players: readonly DrawPlayer[];
  pos: Readonly<Record<string, XY>>;
  ball: XY;
  trail: readonly XY[];
  items: readonly ActiveOverlay[];
  ahead: (id: string, lead: number) => XY;
  /** Metres from Ashmoor's back line to their goal. */
  depth: number;
  density: Density;
  goal: boolean;
  /**
   * Ground only: the overlays, the rings around followed and focused players, and the goal burst, without the dots or
   * the ball. The 3D view paints this onto the grass, as broadcast virtual graphics are.
   */
  groundOnly?: boolean;
  /**
   * A still, for snapshots: every entrance finished, no live ripple or goal burst, and shirt numbers drawn as text, so
   * an SVG export keeps them as words.
   */
  still?: boolean;
  /** How much larger than normal to draw players: above 1 on small pitches, so shirt numbers stay readable. */
  dotScale?: number;
}

interface Glyph {
  img: CanvasImageSource;
  /** Size and baseline in pitch units. */
  w: number;
  h: number;
  baseline: number;
}

export interface DrawState {
  /** When each entrance started, so it runs once per appearance. */
  seen: Map<string, number>;
  tweens: Map<string, { from: number; to: number; start: number; dur: number }>;
  contours: { key: string; lines: XY[][][] } | null;
  /** Shirt numbers, drawn once per size and colour. */
  glyphs: { k: number; font: string; map: Map<string, Glyph> };
}

export const newDrawState = (): DrawState => ({
  seen: new Map(),
  tweens: new Map(),
  contours: null,
  glyphs: { k: 0, font: '', map: new Map() },
});

const makeCanvas = (w: number, h: number): OffscreenCanvas | HTMLCanvasElement =>
  typeof OffscreenCanvas !== 'undefined' ? new OffscreenCanvas(w, h) : Object.assign(document.createElement('canvas'), { width: w, height: h });

/**
 * A shirt number as a small bitmap at the canvas's resolution. Drawing text straight into a canvas on the page makes
 * the browser bring every style up to date first, every frame; a bitmap drawn once costs a copy.
 */
function glyph(st: DrawState, text: string, colour: string, font: string, k: number): Glyph | null {
  if (st.glyphs.k !== k || st.glyphs.font !== font) st.glyphs = { k, font, map: new Map() };
  const key = `${text}|${colour}`;
  const cached = st.glyphs.map.get(key);
  if (cached) return cached;
  const css = `700 13px ${font}`;
  const probe = makeCanvas(1, 1).getContext('2d') as CanvasRenderingContext2D | null;
  if (!probe) return null;
  probe.font = css;
  const m = probe.measureText(text);
  const pad = 2;
  const ascent = m.actualBoundingBoxAscent || 10;
  const descent = m.actualBoundingBoxDescent || 3;
  const canvas = makeCanvas(Math.ceil((m.width + pad * 2) * k), Math.ceil((ascent + descent + pad * 2) * k));
  const c = canvas.getContext('2d') as CanvasRenderingContext2D | null;
  if (!c) return null;
  const w = canvas.width / k;
  c.scale(k, k);
  c.font = css;
  c.fillStyle = colour;
  c.textAlign = 'center';
  c.textBaseline = 'alphabetic';
  c.fillText(text, w / 2, pad + ascent);
  const g = { img: canvas, w, h: canvas.height / k, baseline: pad + ascent };
  st.glyphs.map.set(key, g);
  return g;
}

/** Sets up a canvas to draw in pitch units: (0, 0) is the corner flag, 10 units a metre. */
function begin(ctx: CanvasRenderingContext2D, o: Orientation, view: { w: number; dpr: number }): number {
  const k = (view.w / SIZE[o][0]) * view.dpr;
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.globalAlpha = 1;
  ctx.clearRect(0, 0, ctx.canvas.width, ctx.canvas.height);
  ctx.setTransform(k, 0, 0, k, 30 * k, 30 * k);
  ctx.lineJoin = 'round';
  ctx.lineCap = 'butt';
  return k;
}

/**
 * Contours at 25%, 50% and 75% control, so the field reads without colour (PRD 10.1). They have their own canvas and
 * are traced once per 25 Hz data frame, not every display frame.
 */
export function drawContours(
  ctx: CanvasRenderingContext2D,
  view: { w: number; dpr: number },
  o: Orientation,
  field: ArrayLike<number> | null,
  grid: Grid,
  levels: readonly number[],
  theme: Theme2D,
  st: DrawState,
  key: string,
): void {
  begin(ctx, o, view);
  if (!field || !levels.length) return;
  if (st.contours?.key !== key)
    st.contours = {
      key,
      lines: levels.map((level) => chains(contours(field, grid, level))),
    };
  const lines = st.contours.lines;
  ctx.strokeStyle = theme.contour;
  levels.forEach((level, i) => {
    const mid = level === 0.5;
    ctx.globalAlpha = mid ? 0.8 : 0.55;
    ctx.lineWidth = mid ? 2.2 : 1.5;
    ctx.setLineDash(mid ? [] : [4, 6]);
    ctx.beginPath();
    for (const line of lines[i] ?? []) smoothLine(ctx, line.map((p) => project(o, p[0], p[1])));
    ctx.stroke();
  });
  ctx.setLineDash([]);
  ctx.globalAlpha = 1;
}

/**
 * A contour as one smooth curve: each traced point becomes the control point of a curve between the midpoints either
 * side of it, so the 2 m grid's corners round off and the line still passes within a cell of the true contour.
 */
function smoothLine(ctx: CanvasRenderingContext2D, pts: readonly XY[]) {
  const n = pts.length;
  if (n < 2) return;
  const mid = (a: XY, b: XY): XY => [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
  const closed = n > 3 && pts[0][0] === pts[n - 1][0] && pts[0][1] === pts[n - 1][1];
  if (n === 2) {
    ctx.moveTo(pts[0][0], pts[0][1]);
    ctx.lineTo(pts[1][0], pts[1][1]);
    return;
  }
  if (closed) {
    // The loop's last point repeats its first: curve through every point and back to where it began.
    const ring = pts.slice(0, -1);
    const start = mid(ring[ring.length - 1], ring[0]);
    ctx.moveTo(start[0], start[1]);
    ring.forEach((p, i) => {
      const m = mid(p, ring[(i + 1) % ring.length]);
      ctx.quadraticCurveTo(p[0], p[1], m[0], m[1]);
    });
    ctx.closePath();
    return;
  }
  ctx.moveTo(pts[0][0], pts[0][1]);
  for (let i = 1; i < n - 1; i++) {
    const m = mid(pts[i], pts[i + 1]);
    ctx.quadraticCurveTo(pts[i][0], pts[i][1], m[0], m[1]);
  }
  ctx.lineTo(pts[n - 1][0], pts[n - 1][1]);
}

function line(ctx: CanvasRenderingContext2D, a: XY, b: XY) {
  ctx.beginPath();
  ctx.moveTo(a[0], a[1]);
  ctx.lineTo(b[0], b[1]);
  ctx.stroke();
}

function disc(ctx: CanvasRenderingContext2D, x: number, y: number, r: number) {
  ctx.beginPath();
  ctx.arc(x, y, r, 0, Math.PI * 2);
}

/** Arrowhead for a line from a to b, in pitch units: the same triangle as geometry.ts's arrowHead. */
function arrowHead(ctx: CanvasRenderingContext2D, a: XY, b: XY, size = 20) {
  const len = Math.hypot(b[0] - a[0], b[1] - a[1]) || 1;
  const ux = (b[0] - a[0]) / len;
  const uy = (b[1] - a[1]) / len;
  const bx = b[0] - ux * size;
  const by = b[1] - uy * size;
  const half = size / 2;
  ctx.beginPath();
  ctx.moveTo(b[0], b[1]);
  ctx.lineTo(bx - uy * half, by + ux * half);
  ctx.lineTo(bx + uy * half, by - ux * half);
  ctx.closePath();
  ctx.fill();
}

/**
 * Draws one frame and reports whether anything is still animating, so the caller can stop redrawing a paused
 * picture. `view` is the canvas's CSS size and pixel ratio; everything else is in pitch units.
 */
export function drawScene(ctx: CanvasRenderingContext2D, view: { w: number; dpr: number }, s: Scene2D, st: DrawState): boolean {
  const k = begin(ctx, s.o, view);
  const { theme: T, motion: M, reduced } = s;
  const P = (p: XY) => project(s.o, p[0], p[1]);
  let animating = false;
  const live = new Set<string>();

  /** Progress through an entrance, from the first frame it was asked for. */
  const enter = (key: string, dur: number, delay = 0) => {
    live.add(key);
    if (s.still) return 1;
    let first = st.seen.get(key);
    if (first === undefined) {
      first = s.now;
      st.seen.set(key, first);
    }
    const u = clamp01((s.now - first - delay) / dur);
    if (u < 1) animating = true;
    return u;
  };
  /** anim-fade: opacity over --dur-base (a short fade with reduced motion). */
  const fadeIn = (key: string) => M.ease.standard(enter(`${key}:fade`, reduced ? M.dur.quick : M.dur.base));
  /** anim-pop: scale and opacity on the pop curve, or a short fade with reduced motion. */
  const popIn = (key: string) => {
    if (reduced)
      return {
        scale: 1,
        alpha: M.ease.standard(enter(`${key}:pop`, M.dur.quick)),
      };
    const u = enter(`${key}:pop`, M.dur.pop);
    return { scale: M.popScale(u), alpha: M.popOpacity(u) };
  };
  /** A transition between values, like a CSS transition on the same property. */
  const tween = (key: string, target: number, dur: number) => {
    live.add(key);
    if (s.still) return target;
    const tw = st.tweens.get(key);
    if (!tw) {
      st.tweens.set(key, { from: target, to: target, start: s.now, dur });
      return target;
    }
    const u = reduced ? 1 : clamp01((s.now - tw.start) / tw.dur);
    const value = tw.from + (tw.to - tw.from) * M.ease.standard(u);
    if (tw.to !== target) {
      st.tweens.set(key, { from: value, to: target, start: s.now, dur });
      animating = true;
    } else if (u < 1) animating = true;
    return value;
  };

  // The pitch layer, under the players: the back line, rings, runs, passes and ghosts.
  for (const { overlay: o, retraction } of s.items) {
    const d = (o.data ?? {}) as Record<string, unknown>;
    const id = `${o.overlay_id}:${o.rev}`;
    // A retracted graphic fades back to 35% while its Correction tag shows (PRD 15.2).
    const base = tween(`${id}:retract`, retraction ? 0.35 : 1, M.dur.smooth);
    ctx.globalAlpha = base;
    switch (o.kind) {
      case 'offside_line': {
        if (s.density === 'minimal') break;
        const x = 105 - s.depth;
        ctx.globalAlpha = base * 0.6 * fadeIn(id);
        ctx.strokeStyle = T.text;
        ctx.lineWidth = 2;
        ctx.setLineDash([10, 8]);
        line(ctx, P([x, 0]), P([x, 68]));
        ctx.setLineDash([]);
        break;
      }
      case 'gap_ring': {
        const c = o.anchors.centre_xy;
        if (!c) break;
        const [cx, cy] = P(c);
        const rx = Number(d.rx_m ?? 5.4) * 10;
        const ry = Number(d.ry_m ?? 6.8) * 10;
        // Radii swap on the vertical pitch, so the ellipse stays on the same patch of grass.
        const [ex, ey] = s.o === 'h' ? [rx, ry] : [ry, rx];
        if (d.shut) {
          // The gap that never opened: dashed, crossed through, with one shake.
          const dx = reduced ? 0 : M.shake(enter(`${id}:shake`, M.dur.fill));
          ctx.strokeStyle = T.muted;
          ctx.lineWidth = 3;
          ctx.setLineDash([8, 7]);
          ctx.beginPath();
          ctx.ellipse(cx + dx, cy, ex, ey, 0, 0, Math.PI * 2);
          ctx.stroke();
          ctx.setLineDash([]);
          ctx.lineCap = 'round';
          line(ctx, [cx + dx - 40, cy - 40], [cx + dx + 40, cy + 40]);
          ctx.lineCap = 'butt';
          break;
        }
        ctx.globalAlpha = base * fadeIn(id);
        ctx.fillStyle = T.spaceFill;
        ctx.beginPath();
        ctx.ellipse(cx, cy, ex, ey, 0, 0, Math.PI * 2);
        ctx.fill();
        // ring-draw: the stroke draws from the top, then pulses once (the only bounce on the pitch, PRD 16.10).
        let drawn = 1;
        let scale = 1;
        if (reduced) ctx.globalAlpha = base * M.ease.standard(enter(`${id}:ring`, M.dur.quick));
        else {
          ctx.globalAlpha = base;
          drawn = M.ease.standard(enter(`${id}:ring`, M.dur.draw));
          scale = M.pulse(enter(`${id}:pulse`, M.dur.pulse, M.dur.draw));
        }
        ctx.strokeStyle = T.space;
        ctx.lineWidth = 4;
        ctx.beginPath();
        ctx.ellipse(cx, cy, ex * scale, ey * scale, 0, -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * drawn);
        ctx.stroke();
        // In one-overlay-at-a-time modes the pass into the gap is part of the ring.
        if (d.with_pass === true && s.t >= 4.2 && s.t < 6.4) {
          const from = P(PASS_FROM);
          const ball = P(s.ball);
          ctx.strokeStyle = T.text;
          ctx.lineCap = 'round';
          ctx.globalAlpha = base * 0.85;
          ctx.lineWidth = 4;
          line(ctx, from, ball);
          ctx.globalAlpha = base * 0.7;
          ctx.lineWidth = 3;
          ctx.lineCap = 'butt';
          ctx.setLineDash([9, 8]);
          line(ctx, ball, [cx, cy]);
          ctx.setLineDash([]);
        }
        break;
      }
      case 'run_arrow': {
        const pid = o.anchors.player_id;
        if (!pid || !s.pos[pid]) break;
        ctx.globalAlpha = base * fadeIn(id);
        if (d.style === 'displacement') {
          // How far a defender was pulled: dashed in his team's colour from where he started.
          const from = P(o.anchors.from_xy ?? s.pos[pid]);
          ctx.strokeStyle = T.ash;
          ctx.fillStyle = T.ash;
          ctx.lineWidth = 3;
          ctx.setLineDash([6, 6]);
          line(ctx, from, P(s.pos[pid]));
          ctx.setLineDash([]);
          disc(ctx, from[0], from[1], 5);
          ctx.fill();
          break;
        }
        // Solid from the start of the run to the runner, dashed for the path ahead, the head ~0.8 s ahead.
        const colour = pid.startsWith('ash') ? T.ash : T.kes;
        const a = P(o.anchors.from_xy ?? s.pos[pid]);
        const r = P(s.pos[pid]);
        const h = P(s.ahead(pid, Number(d.lead_s ?? 0.8)));
        const going = Math.hypot(h[0] - r[0], h[1] - r[1]) > 8;
        ctx.strokeStyle = colour;
        ctx.fillStyle = colour;
        ctx.lineCap = 'round';
        ctx.lineWidth = 5;
        line(ctx, a, r);
        if (going) {
          ctx.lineWidth = 4;
          ctx.setLineDash([8, 7]);
          line(ctx, r, h);
          ctx.setLineDash([]);
        }
        ctx.lineCap = 'butt';
        arrowHead(ctx, going ? r : a, going ? h : r);
        break;
      }
      case 'pass_line': {
        const from = o.anchors.from_xy;
        const to = o.anchors.to_xy;
        if (!from || !to) break;
        if (d.planned === true) {
          // A pass that wasn't played (PRD 15.2): dashed all the way, its weight still carrying the difficulty.
          const a = P(from);
          const c = P(to);
          ctx.globalAlpha = base * fadeIn(id) * 0.9;
          ctx.strokeStyle = T.text;
          ctx.fillStyle = T.text;
          ctx.lineWidth = 1.5 + Number(d.difficulty ?? 6) * 0.35;
          ctx.setLineDash([10, 8]);
          line(ctx, a, c);
          ctx.setLineDash([]);
          arrowHead(ctx, a, c);
          break;
        }
        // Solid behind the ball, dashed ahead; weight carries difficulty; the head pops on arrival.
        const arrived = Math.hypot(s.ball[0] - to[0], s.ball[1] - to[1]) < 1.2 || s.t >= 5.6;
        const a = P(from);
        const c = P(to);
        const b = arrived ? c : P(s.ball);
        ctx.strokeStyle = T.text;
        ctx.fillStyle = T.text;
        ctx.lineCap = 'round';
        ctx.lineWidth = 2 + Number(d.difficulty ?? 6) * 0.5;
        line(ctx, a, b);
        ctx.lineCap = 'butt';
        if (!arrived) {
          ctx.globalAlpha = base * 0.8;
          ctx.lineWidth = 3;
          ctx.setLineDash([9, 8]);
          line(ctx, b, c);
          ctx.setLineDash([]);
        } else {
          const { scale, alpha } = popIn(`${id}:head`);
          ctx.save();
          ctx.globalAlpha = base * alpha;
          ctx.translate(c[0], c[1]);
          ctx.scale(scale, scale);
          ctx.translate(-c[0], -c[1]);
          arrowHead(ctx, a, c);
          ctx.restore();
        }
        break;
      }
      case 'ghost': {
        const pid = o.anchors.player_id;
        const path = d.track as Key[] | undefined;
        if (!pid || !path) break;
        // Where a player would have been: a dashed outline over a faint fill, never solid (PRD 15.2).
        const [gx, gy] = P(along(path, s.t));
        const colour = pid.startsWith('ash') ? T.ash : T.kes;
        const { scale, alpha } = popIn(id);
        // A changed decision's path (PRD 15.12), dashed as anything planned or counterfactual: the way ahead while
        // previewing, with a head where it ends, or the way already gone as the changed world plays out.
        const from = Number(d.from ?? 0);
        const end = path[path.length - 1][0];
        const way = d.path === 'ahead' ? [Math.max(from, s.t), end] : d.path === 'trail' ? [from, s.t] : null;
        const sample = (keys: readonly Key[], t0: number, t1: number) => {
          const pts: XY[] = [];
          for (let tt = t0; tt < t1; tt += 0.1) pts.push(P(along(keys, tt)));
          pts.push(P(along(keys, t1)));
          return pts;
        };
        const stroke = (pts: readonly XY[]) => {
          ctx.beginPath();
          pts.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)));
          ctx.stroke();
        };
        if (way && way[1] - way[0] > 0.05) {
          ctx.strokeStyle = colour;
          ctx.fillStyle = colour;
          ctx.lineCap = 'round';
          // While previewing, what really happened next runs faint and solid beside the changed path, so a change
          // that keeps a player still still reads as a change.
          const real = d.path === 'ahead' ? (d.real as Key[] | undefined) : undefined;
          if (real) {
            ctx.globalAlpha = base * alpha * 0.35;
            ctx.lineWidth = 2;
            stroke(sample(real, way[0], real[real.length - 1][0]));
          }
          const pts = sample(path, way[0], way[1]);
          ctx.globalAlpha = base * alpha * 0.85;
          ctx.lineWidth = 3;
          ctx.setLineDash([7, 7]);
          stroke(pts);
          ctx.setLineDash([]);
          ctx.lineCap = 'butt';
          if (d.path === 'ahead') {
            const [ex, ey] = pts[pts.length - 1];
            const [sx, sy] = pts[0];
            // Under 2 m from where they are: they hold. A dashed ring says so; an arrow says where they go.
            if (Math.hypot(ex - sx, ey - sy) < 20) {
              ctx.setLineDash([5, 5]);
              ctx.lineWidth = 2.5;
              disc(ctx, ex, ey, 21);
              ctx.stroke();
              ctx.setLineDash([]);
            } else if (pts.length > 2) arrowHead(ctx, pts[pts.length - 3], pts[pts.length - 1]);
          }
        }
        ctx.save();
        ctx.translate(gx, gy);
        ctx.scale(scale, scale);
        ctx.fillStyle = colour;
        ctx.strokeStyle = colour;
        ctx.globalAlpha = base * alpha * 0.18;
        disc(ctx, 0, 0, 13 * (s.dotScale ?? 1));
        ctx.fill();
        ctx.globalAlpha = base * alpha * 0.9;
        ctx.lineWidth = 3;
        ctx.setLineDash([5, 4]);
        ctx.stroke();
        ctx.setLineDash([]);
        ctx.restore();
        break;
      }
    }
  }
  ctx.globalAlpha = 1;

  // Players. On a small pitch every dot, ring and number is drawn larger (dotScale), so shirt numbers stay readable.
  const ds = s.dotScale ?? 1;
  for (const p of s.players) {
    const [x, y] = P(p.at);
    // Dimmed players (Player focus) step back but stay legible against a field in their own colour.
    const alpha = tween(`p:${p.id}:dim`, p.dim ? 0.62 : 1, M.dur.smooth);
    const grow = tween(`p:${p.id}:grow`, p.highlight ? 1.32 : 1, M.dur.quick) * ds;
    // A player whose decision can be changed (PRD 15.12): a dashed lime ring that grows in, and never loops.
    const pick = tween(`p:${p.id}:pick`, p.pickable ? 1 : 0, M.dur.base);
    if (pick > 0.01) {
      ctx.globalAlpha = alpha * pick;
      ctx.strokeStyle = T.space;
      ctx.lineWidth = 3;
      ctx.setLineDash([6, 5]);
      disc(ctx, x, y, (17 + 5 * pick) * ds);
      ctx.stroke();
      ctx.setLineDash([]);
    }
    ctx.globalAlpha = alpha;
    if (p.follow) {
      ctx.strokeStyle = T.space;
      ctx.lineWidth = 3;
      disc(ctx, x, y, 22 * ds);
      ctx.stroke();
      // A live indicator, the only motion that loops; reduced motion shows the steady ring alone (PRD 16.10).
      if (!reduced && !s.still) {
        const e = M.ease.standard((s.now % M.dur.pulse) / M.dur.pulse);
        ctx.globalAlpha = alpha * 0.85 * (1 - e);
        disc(ctx, x, y, 22 * ds * (1 + 1.2 * e));
        ctx.stroke();
        ctx.globalAlpha = alpha;
        animating = true;
      }
    }
    if (s.groundOnly) {
      // The focus ring and the hover highlight go on the grass around the player's feet.
      if (p.focusRing || p.highlight) {
        ctx.strokeStyle = p.focusRing ? T.focus : T.text;
        ctx.lineWidth = p.focusRing ? 4 : 2.5;
        disc(ctx, x, y, 13 * grow);
        ctx.stroke();
      }
      continue;
    }
    const r = 13 * grow;
    ctx.fillStyle = p.colour ?? (p.team === 'kes' ? T.kes : T.ash);
    ctx.strokeStyle = p.focusRing ? T.focus : T.halo;
    ctx.lineWidth = p.focusRing ? 4 : 2.5;
    disc(ctx, x, y, r);
    ctx.fill();
    ctx.stroke();
    // A kit pattern where two teams' colours clash for colour-blind viewers (PRD 16.3).
    if (p.pattern === 'hoops') {
      ctx.strokeStyle = T.halo;
      ctx.lineWidth = 2.5;
      disc(ctx, x, y, 8.5 * grow);
      ctx.stroke();
    } else if (p.pattern === 'stripes') {
      ctx.strokeStyle = T.halo;
      ctx.lineWidth = 2.2;
      line(ctx, [x - 4 * grow, y - 12 * grow], [x - 4 * grow, y + 12 * grow]);
      line(ctx, [x + 4 * grow, y - 12 * grow], [x + 4 * grow, y + 12 * grow]);
    }
    const ink = p.colour ? T.bg : p.team === 'kes' ? T.onKes : T.onAsh;
    if (s.still) {
      ctx.font = `700 ${13 * ds}px ${T.font}`;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'alphabetic';
      ctx.fillStyle = ink;
      ctx.fillText(String(p.num), x, y + 4.5 * ds);
      continue;
    }
    // The bitmap is made at the scaled size, so a larger number stays as sharp as a normal one.
    const g = glyph(st, String(p.num), ink, T.font, k * ds);
    if (g) ctx.drawImage(g.img, x - (g.w * ds) / 2, y + (4.5 - g.baseline) * ds, g.w * ds, g.h * ds);
  }
  ctx.globalAlpha = 1;

  // The ball, with a fading trail during passes and shots.
  if (!s.groundOnly) {
    ctx.fillStyle = T.ball;
    s.trail.forEach((p, i) => {
      const [x, y] = P(p);
      ctx.globalAlpha = 0.42 - i * 0.09;
      disc(ctx, x, y, 5 - i);
      ctx.fill();
    });
    ctx.globalAlpha = 1;
    const [bx, by] = P(s.ball);
    ctx.strokeStyle = T.ballEdge;
    ctx.lineWidth = 2;
    disc(ctx, bx, by, 6.5);
    ctx.fill();
    ctx.stroke();
  }

  // Fourteen particles from the ball, once per goal; they end invisible, and reduced motion drops them.
  if (s.goal && s.t >= T_GOAL && !reduced && !s.still) {
    const [gx, gy] = P(GOAL_AT);
    const started = enter('goal-burst', M.dur.hero + 3 * M.dur.stagger);
    const elapsed = started * (M.dur.hero + 3 * M.dur.stagger);
    for (let i = 0; i < 14; i++) {
      const u = clamp01((elapsed - ((i % 4) * M.dur.stagger) / 1.33) / M.dur.hero);
      if (u >= 1) continue;
      const e = M.ease.standard(u);
      const angle = (i / 14) * Math.PI * 2;
      const dist = (70 + (i % 3) * 26) * e;
      ctx.globalAlpha = 1 - e;
      ctx.fillStyle = i % 2 ? T.space : T.kes;
      disc(ctx, gx + Math.cos(angle) * dist, gy + Math.sin(angle) * dist, (3 + (i % 3)) * (1 - 0.7 * e));
      ctx.fill();
    }
    ctx.globalAlpha = 1;
  }

  // Forget what has left the picture, so it enters again next time it appears.
  for (const key of st.seen.keys()) if (!live.has(key)) st.seen.delete(key);
  for (const key of st.tweens.keys()) if (!live.has(key)) st.tweens.delete(key);
  return animating;
}
