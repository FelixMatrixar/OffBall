import { useEffect, useLayoutEffect, useRef, type MouseEvent, type MutableRefObject, type PointerEvent, type ReactNode } from 'react';
import type { Scenario } from '../../lib/decisions';
import { withoutHidden, type OverlayGroup } from '../../lib/density';
import { frameState, ms, type ActiveOverlay, type FeedStore, type TimeSource } from '../../lib/feed';
import { FIELD_GRID } from '../../lib/field';
import { PRIO, onFrame } from '../../lib/frame-loop';
import type { useI18n } from '../../lib/i18n';
import { COUNTERFACTUAL, PLAYERS, T_GOAL, at, type Key, type XY } from '../../lib/match';
import { usePrefs, type Density, type Mode, type Theme } from '../../lib/prefs';
import { Pitch, SIZE, project, type Orientation } from '../pitch';
import { clearTextWidths } from '../pitch/labels';
import { PitchLabels, PlayerTargets, buildLabels, hintText, ringSpots, usePitchLayer, type Anchor, type Resolved } from '../pitch/PitchLayer';
import { drawContours, drawScene, newDrawState, paintField, readStyle, type DrawPlayer, type Scene2D } from '../pitch/render2d';
import { SvgContext, drawSvgMarkup, paintDomToCanvas, paintDomToSvg, smoothCopy, svgCopy, type Snapshotter, type StageShot } from '../pitch/snapshot';

/**
 * How strongly each mode shows the control field, and how density scales it. Casual, Learn and Audio keep it a quiet
 * wash under the one overlay they show; Analyst reads it at full strength.
 */
export const FIELD_WEIGHT: Record<Mode, number> = { casual: 0.3, learn: 0.3, analyst: 1, player: 0.7, audio: 0.3, broadcaster: 0.8 };
export const DENSITY_WEIGHT: Record<Density, number> = { minimal: 0.5, standard: 1, rich: 1.35 };
/** Device pixels per CSS pixel, capped: beyond 2x the canvas costs more than it shows. */
const MAX_DPR = 2;
const NONE: readonly string[] = [];
export const NO_GROUPS: readonly OverlayGroup[] = [];
export const EMPTY_SET: ReadonlySet<OverlayGroup> = new Set();

/**
 * The counterfactual world moves No. 9 and No. 5 to where they would have been; a changed decision (`tracks`) moves
 * every player it changed (PRD 10.10).
 */
export function withCounterfactual(pos: Record<string, XY>, t: number, on: boolean, tracks?: Readonly<Record<string, readonly Key[]>> | null): Record<string, XY> {
  if (!on) return pos;
  const changed = tracks ?? COUNTERFACTUAL;
  const out = { ...pos };
  for (const id of Object.keys(changed)) out[id] = at(changed[id], t);
  return out;
}

/** The story graphics a what-if replaces: its own ring, run, pass and caption tell the other world's story. */
const STORY = new Set(['gap_ring', 'run_arrow', 'pass_line', 'caption']);

/**
 * What a stage draws at a moment. Without a changed decision, the feed's overlays for this viewer, with the ghosts left
 * out where the players themselves are moved. With one (PRD 15.12), the real players' tags stay, the real story makes
 * way for the changed world's ring and pass in a result, and the scenario's ghosts are added; a preview keeps the real
 * story, so the path ahead reads against what happened.
 */
export function itemsAt(store: FeedStore, t_ms: number, opts: { mode: Mode; whatIf: boolean; fav: string }, cf: boolean, ghosts: boolean, scenario: Scenario | null | undefined): ActiveOverlay[] {
  if (!scenario) return store.active(t_ms, opts).filter((a) => !(cf && !ghosts && a.overlay.kind === 'ghost'));
  const real = store.active(t_ms, { ...opts, whatIf: false });
  const kept = scenario.phase === 'preview' ? real : real.filter((a) => !STORY.has(a.overlay.kind));
  const own = scenario.overlays.filter((o) => o.t_start_ms <= t_ms && t_ms < o.t_end_ms && !(cf && !ghosts && o.kind === 'ghost')).map((overlay) => ({ overlay }));
  return [...own, ...kept];
}

/** Where the ball goes in a changed world, where the change moved it: along the pass not played, or with the carrier. */
export function scenarioBall(scenario: Scenario | null | undefined, t: number, real: XY): XY {
  const keys = scenario?.phase === 'result' ? scenario.ball : undefined;
  return keys && t >= keys[0][0] ? at(keys, t, false) : real;
}

/** Where a label hangs on the 2D pitch, in pitch units (10 per metre). */
function resolve2D(a: Anchor, o: Orientation, pos: Record<string, XY>, t: number, depth: number): Resolved | null {
  const P = (p: XY) => project(o, p[0], p[1]);
  switch (a.kind) {
    case 'player':
      return pos[a.id] ? { at: P(pos[a.id]) } : null;
    case 'point':
      return { at: P(a.at) };
    case 'ring': {
      const [cx, cy] = P(a.centre);
      // The ellipse's screen radii: ry is vertical on the horizontal pitch, rx on the vertical one.
      const ey = (o === 'h' ? a.ry : a.rx) * 10;
      const ex = (o === 'h' ? a.rx : a.ry) * 10;
      // Above the ring; nudged along or up, below it, or beside it when a player stands where the label would go.
      return { at: [cx, cy - ey - 16], alts: ringSpots([cx, cy - ey - 16], [cx, cy + ey + 36], cx + ex + 12, cx - ex - 12, cy + 7, ex) };
    }
    case 'backline': {
      const x = 105 - depth;
      if (o === 'h') {
        const [lx, ly] = P([x, 68]);
        return { at: [lx, ly - 8] };
      }
      const [lx, ly] = P([x, 0]);
      return { at: [lx + 8, ly - 8], align: 'end' };
    }
    case 'pulled': {
      if (!pos[a.id]) return null;
      const s = P(a.from ?? pos[a.id]);
      const e = P(pos[a.id]);
      return { at: [(s[0] + e[0]) / 2, (s[1] + e[1]) / 2] };
    }
    case 'ghost':
      return { at: P(at(a.track, t)) };
  }
}

interface Stage2DProps {
  store: FeedStore;
  /** The clock to follow: `t` for labels and text, `now()` read every display frame for drawing. */
  time: TimeSource;
  mode: Mode;
  density: Density;
  theme: Theme;
  fav: string;
  i18n: ReturnType<typeof useI18n>;
  orientation: Orientation;
  /** 'cf' draws the world without No. 9's run: the counterfactual field, and No. 9 and No. 5 where they would have been. */
  variant: 'real' | 'cf';
  /** The single-pitch "what if" view: real players with ghosts over them. */
  ghosts: boolean;
  onFollow: (id: string) => void;
  chips?: ReactNode;
  corner?: ReactNode;
  scrim?: ReactNode;
  dim?: boolean;
  /** Filled with this stage's snapshot, while it shows (PRD 16.8). */
  snapshot?: MutableRefObject<Snapshotter | null>;
  /** One side of the side-by-side what-if: the field at full strength, as on the other side, so the two compare. */
  compare?: boolean;
  /** A changed decision on show (PRD 15.12): its preview, or its result in this stage's world. */
  scenario?: Scenario | null;
  /** Players whose decision can be changed: each gets a dashed ring while the viewer picks. */
  pickable?: readonly string[];
  /** A click or tap on a player, while picking one. */
  onPlayerClick?: (id: string) => void;
  /** Groups of pitch graphics the viewer has hidden in this mode (PRD 8.2). */
  hide?: readonly OverlayGroup[];
}

/** What the frame loop reads: the latest props, refreshed on every render. */
interface Inputs {
  store: FeedStore;
  time: TimeSource;
  opts: { mode: Mode; whatIf: boolean; fav: string };
  cf: boolean;
  ghosts: boolean;
  strength: number;
  levels: number[];
  density: Density;
  mode: Mode;
  fav: string;
  reduced: boolean;
  hidden: ReadonlySet<OverlayGroup>;
  hint: string | null;
  ring: string | null;
  o: Orientation;
  scenario: Scenario | null;
  pickable: readonly string[];
}

/** How much larger to draw players on a pitch `u` CSS pixels per unit across: dots at least 9 px in radius, up to 1.7x. */
export const dotScaleFor = (u: number) => (u > 0 ? Math.min(1.7, Math.max(1, 9 / (13 * u))) : 1);

/**
 * Two players closer than their dots are wide would hide one shirt number under the other, so they're drawn just far
 * enough apart to read: each moves half the overlap along the line between them, about a metre at most. Display only:
 * the field, the metrics and every number come from where the players really are.
 */
export function dodge(pos: Record<string, XY>, minGap: number): Record<string, XY> {
  const ids = Object.keys(pos);
  let out: Record<string, XY> | null = null;
  for (let i = 0; i < ids.length; i++) {
    for (let j = i + 1; j < ids.length; j++) {
      const now = out ?? pos;
      const a = now[ids[i]];
      const b = now[ids[j]];
      if (!a || !b) continue;
      const dx = b[0] - a[0];
      const dy = b[1] - a[1];
      const d = Math.hypot(dx, dy);
      if (d >= minGap) continue;
      out ??= { ...pos };
      const ux = d > 1e-3 ? dx / d : 1;
      const uy = d > 1e-3 ? dy / d : 0;
      const push = (minGap - d) / 2;
      out[ids[i]] = [a[0] - ux * push, a[1] - uy * push];
      out[ids[j]] = [b[0] + ux * push, b[1] + uy * push];
    }
  }
  return out ?? pos;
}

/** Everything one frame of a 2D stage draws at moment time `t`. A still is for snapshots: see Scene2D. */
function frameScene(L: Inputs, t: number, now: number, style: ReturnType<typeof readStyle>, still = false, ds = 1) {
  // The loop draws straight away from shared buffers; a still may wait on other work, so it takes copies.
  const alt = L.cf && L.scenario ? L.scenario.id : null;
  const fs = frameState(L.store, t, { cf: L.cf, alt, copy: still });
  const moved = L.cf && !L.ghosts;
  // Where the dots are drawn: kept far enough apart to read both numbers (2.3 m is two dot radii less a little halo).
  const pos = dodge(withCounterfactual(fs.pos, t, moved, L.scenario?.tracks), 2.3 * ds);
  const field = L.cf ? fs.cfField : fs.field;
  const items = withoutHidden(itemsAt(L.store, fs.t_ms, L.opts, L.cf, L.ghosts, L.scenario), L.hidden);
  const anchored = new Set(items.map((a) => a.overlay.anchors.player_id).filter(Boolean));
  const players: DrawPlayer[] = PLAYERS.map((p) => ({
    id: p.id,
    team: p.team,
    num: p.num,
    at: pos[p.id],
    dim: L.mode === 'player' && p.id !== L.fav && !anchored.has(p.id),
    follow: L.mode === 'player' && p.id === L.fav,
    highlight: !still && p.id === L.hint,
    focusRing: !still && p.id === L.ring,
    pickable: L.pickable.includes(p.id),
  }));
  // The changed world's ball, on the side of the side-by-side where its players are moved too.
  const ball = moved ? scenarioBall(L.scenario, t, fs.ballXY) : fs.ballXY;
  const trail = ball === fs.ballXY ? fs.trail : [];
  const scene: Scene2D = { o: L.o, now, t, reduced: L.reduced, theme: style.theme, motion: style.motion, players, pos, ball, trail, items, ahead: fs.ahead, depth: fs.depth, density: L.density, goal: !L.cf, still, dotScale: ds };
  return { fs, pos, field, scene };
}

/**
 * One 2D pitch, drawn from the feed for one viewer (PRD 10.1, 15.2) as tier C: shapes, players and ball on a canvas
 * every display frame, and the DOM layer above for labels and the players' focus targets (PRD 16.2). React renders
 * the text ten times a second; the frame loop moves everything every frame without re-rendering.
 */
export function Stage2D({ store, time, mode, density, theme, fav, i18n, orientation, variant, ghosts, onFollow, chips, corner, scrim, dim, snapshot, compare = false, scenario = null, pickable = NONE, onPlayerClick, hide = NO_GROUPS }: Stage2DProps) {
  const { reducedMotion } = usePrefs();
  const { lang, num, pack } = i18n;
  const cf = variant === 'cf';
  const t = time.t;
  const opts = { mode, whatIf: cf || ghosts, fav };
  const coarse = frameState(store, t, { cf, alt: cf && scenario ? scenario.id : null, copy: false });
  // What the viewer hid applies to the real world only: a what-if or a changed decision shows everything.
  const hidden: ReadonlySet<OverlayGroup> = cf || ghosts || compare || scenario ? EMPTY_SET : new Set(hide);
  const items = withoutHidden(itemsAt(store, ms(t), opts, cf, ghosts, scenario), hidden);
  const strength = hidden.has('field') ? 0 : cf || ghosts || compare ? 1 : Math.min(1, FIELD_WEIGHT[mode] * DENSITY_WEIGHT[density]);
  const levels = hidden.has('field') ? [] : mode === 'analyst' || density === 'rich' ? [0.25, 0.5, 0.75] : [0.5];
  const vbh = SIZE[orientation][1];

  const layer = usePitchLayer();
  const { hintId, ringId } = layer;
  const hint = hintId ? { id: hintId, text: hintText(hintId, lang, num, coarse.speedOf(hintId)) } : null;
  const { labels, pins } = buildLabels(items, coarse, lang, num, density, hint);

  const stageRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const contourRef = useRef<HTMLCanvasElement>(null);
  const fieldRef = useRef<HTMLCanvasElement>(null);
  const view = useRef({ w: 0, h: 0, u: 0 });
  const dirty = useRef(true);
  const styleStale = useRef(true);

  // Everything the frame loop reads, refreshed on every render.
  const inputs: Inputs = { store, time, opts, cf, ghosts, strength, levels, density, mode, fav, reduced: reducedMotion, hidden, hint: hintId, ring: ringId, o: orientation, scenario, pickable };
  const latest = useRef(inputs);
  latest.current = inputs;
  /** The moment time of the picture on screen, which its labels were placed for. */
  const drawnT = useRef(0);

  // After every render: labels that just mounted get their place before they paint, and the loop redraws.
  useLayoutEffect(() => {
    dirty.current = true;
    if (layer.last.current) layer.place(layer.last.current);
  });

  useEffect(() => {
    styleStale.current = true;
    dirty.current = true;
  }, [theme, reducedMotion]);

  // The frame loop: draws the field and the scene whenever time moves or an animation is running.
  useEffect(() => {
    const stage = stageRef.current;
    const canvas = canvasRef.current;
    const contourCanvas = contourRef.current;
    const fieldCanvas = fieldRef.current;
    const ctx = canvas?.getContext('2d');
    const cctx = contourCanvas?.getContext('2d');
    const fctx = fieldCanvas?.getContext('2d');
    if (!stage || !canvas || !contourCanvas || !fieldCanvas || !ctx || !cctx || !fctx) return;
    const state = newDrawState();
    const img = fctx.createImageData(fieldCanvas.width, fieldCanvas.height);
    let style = readStyle(stage);
    layer.fonts.current = { body: style.theme.font, mono: style.theme.mono };
    let lastT = Number.NaN;
    let lastContours = '';
    let animating = true;
    layer.reset();
    // Web fonts arriving late: redraw the shirt numbers in them, and measure labels again.
    const fontsLoaded = () => {
      state.glyphs.map.clear();
      clearTextWidths();
      dirty.current = true;
    };
    document.fonts?.addEventListener('loadingdone', fontsLoaded);

    const ro = new ResizeObserver(([entry]) => {
      const { width: w, height: h } = entry.contentRect;
      view.current = { w, h, u: w / SIZE[orientation][0] };
      stage.style.setProperty('--u', view.current.u.toFixed(4));
      // The players' focus targets grow with their dots on a small pitch.
      stage.style.setProperty('--dot-scale', dotScaleFor(view.current.u).toFixed(3));
      layer.reset();
      dirty.current = true;
    });
    ro.observe(stage);

    const stop = onFrame((now) => {
      const L = latest.current;
      const { w, h, u } = view.current;
      if (!w) return;
      let styleChanged = false;
      if (styleStale.current) {
        // Read lazily, a frame after the theme changed, once the new tokens are in effect.
        style = readStyle(stage);
        layer.fonts.current = { body: style.theme.font, mono: style.theme.mono };
        styleStale.current = false;
        styleChanged = true;
        dirty.current = true;
      }
      const dpr = Math.min(MAX_DPR, window.devicePixelRatio || 1);
      const bw = Math.round(w * dpr);
      const bh = Math.round(h * dpr);
      if (canvas.width !== bw || canvas.height !== bh) {
        canvas.width = contourCanvas.width = bw;
        canvas.height = contourCanvas.height = bh;
        lastContours = '';
        dirty.current = true;
      }
      const t = L.time.now();
      const moved = t !== lastT || dirty.current;
      if (!moved && !animating) return;
      lastT = t;
      dirty.current = false;

      const ds = dotScaleFor(u);
      const { fs, pos, field, scene } = frameScene(L, t, L.time.wall?.() ?? now, style, false, ds);
      drawnT.current = t;
      if (moved) {
        if (field) paintField(fctx, img, field, FIELD_GRID, L.strength, L.o, style.field);
        else fctx.clearRect(0, 0, fieldCanvas.width, fieldCanvas.height);
        // Contours follow the 25 Hz data, so they're traced once per data frame.
        const contourKey = `${L.cf}:${Math.floor(fs.t_ms / 40)}:${L.levels.join()}:${L.o}:${bw}`;
        if (contourKey !== lastContours || styleChanged) {
          drawContours(cctx, { w, dpr }, L.o, field, FIELD_GRID, L.levels, style.theme, state, contourKey);
          lastContours = contourKey;
        }
      }
      animating = drawScene(ctx, { w, dpr }, scene, state);
      // Says when the picture is at rest (nothing entering or looping), for tests and for anything waiting on it.
      const resting = animating ? 'false' : 'true';
      if (stage.dataset.resting !== resting) stage.dataset.resting = resting;
      const [vw, vh] = SIZE[L.o];
      layer.place({
        u,
        resolve: (a) => resolve2D(a, L.o, pos, t, fs.depth),
        players: PLAYERS.map((p) => project(L.o, pos[p.id][0], pos[p.id][1])),
        bounds: { x0: -30, y0: -30, x1: vw - 30, y1: vh - 30 },
        dotScale: ds,
      });
    }, PRIO.draw);

    return () => {
      stop();
      ro.disconnect();
      document.fonts?.removeEventListener('loadingdone', fontsLoaded);
    };
    // The layer's functions read refs, so they work the same across renders; only a new orientation restarts the loop.
  }, [orientation]);

  // The snapshot (PRD 16.8): the picture on screen as a still, every graphic fully drawn, with its labels where they
  // are. PNG composites the layers at the export scale; SVG keeps the markings, shapes and words as vectors.
  useEffect(() => {
    if (!snapshot) return;
    const take = async (format: 'png' | 'svg', scale: number): Promise<StageShot> => {
      const stage = stageRef.current;
      const pitch = stage?.closest<HTMLElement>('.pitch');
      const fieldCanvas = fieldRef.current;
      if (!stage || !pitch || !fieldCanvas) throw new Error('The pitch isn’t showing');
      const L = latest.current;
      const style = readStyle(stage);
      // The dots at the size they're drawn on screen, which the stage keeps in --dot-scale.
      const { field, scene } = frameScene(L, drawnT.current, performance.now(), style, true, Number(stage.style.getPropertyValue('--dot-scale')) || 1);
      const box = pitch.getBoundingClientRect();
      const rel = (r: DOMRect) => ({ x: r.left - box.left, y: r.top - box.top, w: r.width, h: r.height });
      const markings = pitch.querySelector<SVGSVGElement>('svg.pitch-layer');
      const markBox = markings ? rel(markings.getBoundingClientRect()) : null;
      const fieldBox = rel(fieldCanvas.getBoundingClientRect());
      const stageBox = rel(stage.getBoundingClientRect());
      const labels = Array.from(stage.querySelectorAll('.pitch-labels, .goal-banner'));
      if (format === 'svg') {
        const sc = new SvgContext(stageBox.w, stageBox.h);
        const vector = sc as unknown as CanvasRenderingContext2D;
        drawContours(vector, { w: stageBox.w, dpr: 1 }, L.o, field, FIELD_GRID, L.levels, style.theme, newDrawState(), 'still');
        drawScene(vector, { w: stageBox.w, dpr: 1 }, scene, newDrawState());
        const surface = smoothCopy(fieldCanvas, fieldBox.w, fieldBox.h).toDataURL('image/png');
        const parts = [
          markings && markBox ? svgCopy(markings, markBox) : '',
          `<image href="${surface}" x="${fieldBox.x}" y="${fieldBox.y}" width="${fieldBox.w}" height="${fieldBox.h}" preserveAspectRatio="none"/>`,
          `<g transform="translate(${stageBox.x} ${stageBox.y})">${sc.markup()}</g>`,
          paintDomToSvg(labels, pitch.getBoundingClientRect()),
        ];
        return { width: box.width, height: box.height, svg: parts.join('') };
      }
      // Each layer begins by clearing its canvas, so contours and shapes are drawn apart, then stacked.
      const layer = (w: number, h: number, paint?: (ctx: CanvasRenderingContext2D) => void) => {
        const c = document.createElement('canvas');
        c.width = Math.round(w * scale);
        c.height = Math.round(h * scale);
        const ctx = c.getContext('2d');
        if (ctx && paint) paint(ctx);
        return c;
      };
      const view = { w: stageBox.w, dpr: scale };
      const contours = layer(stageBox.w, stageBox.h, (ctx) => drawContours(ctx, view, L.o, field, FIELD_GRID, L.levels, style.theme, newDrawState(), 'still'));
      const shapes = layer(stageBox.w, stageBox.h, (ctx) => drawScene(ctx, view, scene, newDrawState()));
      const words = layer(box.width, box.height, (ctx) => paintDomToCanvas(ctx, labels, pitch.getBoundingClientRect(), scale));
      const out = layer(box.width, box.height);
      const ctx = out.getContext('2d');
      if (!ctx) throw new Error('No canvas for the snapshot');
      ctx.scale(scale, scale);
      if (markings && markBox) await drawSvgMarkup(ctx, svgCopy(markings, markBox), markBox);
      ctx.imageSmoothingEnabled = true;
      ctx.imageSmoothingQuality = 'high';
      ctx.drawImage(fieldCanvas, fieldBox.x, fieldBox.y, fieldBox.w, fieldBox.h);
      ctx.drawImage(contours, stageBox.x, stageBox.y, stageBox.w, stageBox.h);
      ctx.drawImage(shapes, stageBox.x, stageBox.y, stageBox.w, stageBox.h);
      ctx.drawImage(words, 0, 0, box.width, box.height);
      return { width: box.width, height: box.height, canvas: out };
    };
    const shooter: Snapshotter = { formats: ['png', 'svg'], take };
    snapshot.current = shooter;
    return () => {
      if (snapshot.current === shooter) snapshot.current = null;
    };
  }, [snapshot]);

  const onPointerMove = (e: PointerEvent<HTMLDivElement>) => {
    const i = layer.hit(e, e.currentTarget.getBoundingClientRect());
    layer.setHovered(i >= 0 ? PLAYERS[i].id : null);
    e.currentTarget.style.cursor = i >= 0 ? 'pointer' : '';
  };
  // A click or tap on a player focuses them, which shows their name and speed; while picking, it also picks them.
  const onClick = (e: MouseEvent<HTMLDivElement>) => {
    const i = layer.hit(e, e.currentTarget.getBoundingClientRect());
    if (i < 0) return;
    layer.buttons.current[i]?.focus({ preventScroll: true });
    onPlayerClick?.(PLAYERS[i].id);
  };

  const caption = items.find((a) => a.overlay.kind === 'caption');
  const sceneLabel = `2D pitch, ${orientation === 'v' ? 'Kestrel Bay attacking upwards' : 'Kestrel Bay attacking left to right'}${cf && !ghosts ? ', without No. 9’s run' : ''}. ${caption ? (caption.overlay.a11y_text[lang] ?? caption.overlay.text[lang] ?? '') : ''}`;
  const [fw, fh] = orientation === 'h' ? [FIELD_GRID.cols, FIELD_GRID.rows] : [FIELD_GRID.rows, FIELD_GRID.cols];

  return (
    <Pitch
      label={sceneLabel}
      orientation={orientation}
      dim={dim}
      field={<canvas ref={fieldRef} className="field-canvas" width={fw} height={fh} />}
      layers={
        <div ref={stageRef} className="pitch-stage" onPointerMove={onPointerMove} onPointerLeave={() => layer.setHovered(null)} onClick={onClick}>
          <canvas ref={contourRef} className="pitch-canvas" aria-hidden="true" />
          <canvas ref={canvasRef} className="pitch-canvas" aria-hidden="true" />
          <PitchLabels layer={layer} labels={labels} pins={pins} lang={lang} />
          {!cf && t >= T_GOAL && (
            <div className="goal-banner anim-pop" aria-hidden="true" style={{ top: orientation === 'h' ? `calc(${(44 / vbh) * 100}% + 30px)` : `${(44 / vbh) * 100}%` }}>
              {pack.ui.goal}
            </div>
          )}
          <PlayerTargets layer={layer} mode={mode} fav={fav} onFollow={onFollow} />
        </div>
      }
      chips={chips}
      corner={corner}
      scrim={scrim}
    />
  );
}
