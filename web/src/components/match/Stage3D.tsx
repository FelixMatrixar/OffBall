import { useEffect, useLayoutEffect, useRef, useState, type MouseEvent, type MutableRefObject, type PointerEvent, type ReactNode } from 'react';
import { cx } from '../../lib/cx';
import { frameState, ms, type FeedStore, type TimeSource } from '../../lib/feed';
import { PRIO, onFrame } from '../../lib/frame-loop';
import type { useI18n } from '../../lib/i18n';
import { PLAYERS, T_GOAL, at, type Key, type Team, type XY } from '../../lib/match';
import { usePrefs, type Density, type Mode, type Theme } from '../../lib/prefs';
import type { Frame3D, Scene3D, Theme3D, Tier3D, View3D } from '../../three/scene3d';
import { clearTextWidths } from '../pitch/labels';
import { PitchLabels, PlayerTargets, buildLabels, hintText, ringSpots, usePitchLayer, type Anchor, type Resolved } from '../pitch/PitchLayer';
import { drawScene, newDrawState, readStyle, type DrawPlayer } from '../pitch/render2d';
import { paintDomToCanvas, type Snapshotter } from '../pitch/snapshot';
import { Spinner } from '../ui';
import { DENSITY_WEIGHT, EMPTY_SET, FIELD_WEIGHT, NO_GROUPS, dodge, itemsAt, scenarioBall, withCounterfactual } from './Stage2D';
import { withoutHidden, type OverlayGroup } from '../../lib/density';
import type { Scenario } from '../../lib/decisions';

/** Device pixels per CSS pixel, capped: beyond 2x the scene costs more than it shows. */
const MAX_DPR = 2;
/** Labels and hit areas use the same units as the 2D pitch (1110 across), so text sizes match between views. */
const UNITS_ACROSS = 1110;
/** Where a player's label and focus target sit: around the chest, in metres. */
const BODY_Z = 1.1;
const HEAD_Z = 2.15;

export const VIEW_NAMES: Record<View3D, string> = {
  broadcast: '3D broadcast',
  tactical: '3D tactical',
  player: 'Player cam',
  goal: 'Behind the goal',
};

function readTheme3D(el: Element): Theme3D {
  const cs = getComputedStyle(el);
  const v = (name: string, fallback: string) => cs.getPropertyValue(name).trim() || fallback;
  return {
    pitch: v('--pitch', '#14301f'),
    stripe: v('--stripe', '#173624'),
    edge: v('--edge', '#0f2419'),
    chalk: v('--chalk', 'rgb(236 241 236 / 0.45)'),
    bg: v('--bg', '#0b1110'),
    surface: v('--surface', '#121b18'),
    surface2: v('--surface-2', '#19251f'),
    line: v('--line', '#27362f'),
    text: v('--text', '#ecf1ec'),
    muted: v('--muted', '#9eb0a6'),
    kes: v('--kes', '#7cc0ff'),
    ash: v('--ash', '#e2733a'),
    onKes: v('--on-kes', '#06121f'),
    onAsh: v('--on-ash', '#1e0c02'),
    ball: v('--ball', '#ffffff'),
    ballEdge: v('--ball-edge', '#0b1110'),
    contour: v('--contour', 'rgb(236 241 236 / 0.55)'),
    fieldMax: Number(v('--field-max', '0.55')) || 0.55,
    font: v('--font-body', 'system-ui, sans-serif'),
  };
}

interface Stage3DProps {
  store: FeedStore;
  time: TimeSource;
  mode: Mode;
  density: Density;
  theme: Theme;
  fav: string;
  i18n: ReturnType<typeof useI18n>;
  view: View3D;
  /** The tier to start: A asks for WebGPU and settles for WebGL2. */
  tier: Tier3D;
  variant: 'real' | 'cf';
  ghosts: boolean;
  onFollow: (id: string) => void;
  /** The 3D view couldn't start or lost its GPU: the match view falls back to 2D (PRD VIS-4). */
  onFail: (reason: string) => void;
  /** The tier actually running, which may be lower than asked for. */
  onTier?: (tier: Tier3D) => void;
  chips?: ReactNode;
  corner?: ReactNode;
  scrim?: ReactNode;
  dim?: boolean;
  portrait?: boolean;
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

const NONE: readonly string[] = [];

/**
 * One 3D view of the pitch (PRD 15.1, 16.2), tiers A and B: the scene from three/scene3d.ts, loaded on demand, with
 * the ground overlays painted by the same renderer as the 2D view and the same DOM layer above for labels and the
 * players' focus targets, placed by projecting each anchor every frame.
 */
export function Stage3D({ store, time, mode, density, theme, fav, i18n, view, tier, variant, ghosts, onFollow, onFail, onTier, chips, corner, scrim, dim, portrait, snapshot, compare = false, scenario = null, pickable = NONE, onPlayerClick, hide = NO_GROUPS }: Stage3DProps) {
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

  const layer = usePitchLayer();
  const { hintId, ringId } = layer;
  const hint = hintId ? { id: hintId, text: hintText(hintId, lang, num, coarse.speedOf(hintId)) } : null;
  const { labels, pins } = buildLabels(items, coarse, lang, num, density, hint);

  const [status, setStatus] = useState<'loading' | 'ready'>('loading');
  const boxRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const stageRef = useRef<HTMLDivElement>(null);
  const sceneRef = useRef<Scene3D | null>(null);
  const dirty = useRef(true);
  const themeStale = useRef(true);
  const failRef = useRef(onFail);
  failRef.current = onFail;
  const tierRef = useRef(onTier);
  tierRef.current = onTier;

  const inputs = { store, time, opts, cf, ghosts, strength, levels, density, mode, fav, reduced: reducedMotion, hidden, hint: hintId, ring: ringId, view, scenario, pickable };
  const latest = useRef(inputs);
  latest.current = inputs;

  useLayoutEffect(() => {
    dirty.current = true;
    if (layer.last.current) layer.place(layer.last.current);
  });

  useEffect(() => {
    themeStale.current = true;
    dirty.current = true;
  }, [theme, reducedMotion]);

  useEffect(() => {
    sceneRef.current?.setView(view);
    dirty.current = true;
  }, [view]);

  useEffect(() => {
    const box = boxRef.current;
    const canvas = canvasRef.current;
    const stage = stageRef.current;
    if (!box || !canvas || !stage) return;
    let disposed = false;
    let stop: (() => void) | null = null;
    let ro: ResizeObserver | null = null;
    const state = newDrawState();
    const fontsLoaded = () => {
      state.glyphs.map.clear();
      clearTextWidths();
      dirty.current = true;
    };

    const start = (scene: Scene3D) => {
      sceneRef.current = scene;
      scene.setView(latest.current.view);
      tierRef.current?.(scene.tier);
      let style = readStyle(stage);
      layer.fonts.current = { body: style.theme.font, mono: style.theme.mono };
      const octx = scene.overlayCanvas.getContext('2d');
      if (!octx) throw new Error('No 2D context for the ground overlays');
      let u = box.clientWidth / UNITS_ACROSS;
      let lastT = Number.NaN;
      let animating = true;
      let overlayHadContent = true;
      document.fonts?.addEventListener('loadingdone', fontsLoaded);
      ro = new ResizeObserver(() => {
        u = box.clientWidth / UNITS_ACROSS;
        stage.style.setProperty('--u', u.toFixed(4));
        scene.resize();
        layer.reset();
        dirty.current = true;
      });
      ro.observe(box);
      stage.style.setProperty('--u', u.toFixed(4));

      stop = onFrame((now) => {
        const L = latest.current;
        if (themeStale.current) {
          style = readStyle(stage);
          layer.fonts.current = { body: style.theme.font, mono: style.theme.mono };
          scene.setTheme(readTheme3D(box));
          themeStale.current = false;
          dirty.current = true;
        }
        const t = L.time.now();
        const wall = L.time.wall?.() ?? now;
        if (t === lastT && !dirty.current && !animating && !scene.moving()) return;
        lastT = t;
        dirty.current = false;

        const fs = frameState(L.store, t, { cf: L.cf, alt: L.cf && L.scenario ? L.scenario.id : null, copy: false });
        const moved = L.cf && !L.ghosts;
        // Two figures never stand inside each other: drawn at least 1.1 m apart (display only, as in 2D).
        const pos = dodge(withCounterfactual(fs.pos, t, moved, L.scenario?.tracks), 1.1);
        // The field is the other world's wherever one is shown, even with the real players on the pitch and ghosts
        // over them: tier A computes it from these positions.
        const fieldPos = L.cf && !moved ? withCounterfactual(fs.pos, t, true, L.scenario?.tracks) : pos;
        const frameItems = withoutHidden(itemsAt(L.store, fs.t_ms, L.opts, L.cf, L.ghosts, L.scenario), L.hidden);
        const anchored = new Set(frameItems.map((a) => a.overlay.anchors.player_id).filter(Boolean));
        const dim = new Set(L.mode === 'player' ? PLAYERS.filter((p) => p.id !== L.fav && !anchored.has(p.id)).map((p) => p.id) : []);
        const players: DrawPlayer[] = PLAYERS.map((p) => ({
          id: p.id,
          team: p.team,
          num: p.num,
          at: pos[p.id],
          dim: dim.has(p.id),
          follow: L.mode === 'player' && p.id === L.fav,
          highlight: p.id === L.hint,
          focusRing: p.id === L.ring,
          pickable: L.pickable.includes(p.id),
        }));
        const [bx, by] = moved ? scenarioBall(L.scenario, t, fs.ballXY) : fs.ballXY;
        // The ground overlays: the same grammar as the 2D view, painted onto the grass.
        const rings = players.some((p) => p.follow || p.highlight || p.focusRing);
        let overlayAnimating = false;
        if (frameItems.length || rings || overlayHadContent) {
          overlayAnimating = drawScene(
            octx,
            { w: scene.overlayCanvas.width, dpr: 1 },
            { o: 'h', now: wall, t, reduced: L.reduced, theme: style.theme, motion: style.motion, players, pos, ball: [bx, by], trail: [], items: frameItems, ahead: fs.ahead, depth: fs.depth, density: L.density, goal: !L.cf, groundOnly: true },
            state,
          );
          scene.overlayChanged();
          overlayHadContent = frameItems.length > 0 || rings || overlayAnimating;
        }
        // What the graphics are about, for the broadcast camera to keep in shot.
        const focus: XY[] = [];
        for (const { overlay: o } of frameItems) {
          if (o.anchors.centre_xy) focus.push(o.anchors.centre_xy);
          if (o.anchors.to_xy) focus.push(o.anchors.to_xy);
          const pid = o.anchors.player_id;
          if (pid && pos[pid] && o.layer !== 'dom') focus.push(pos[pid]);
        }
        const ghostFigures = frameItems.flatMap(({ overlay: o }) => {
          const track = (o.data as { track?: Key[] } | null)?.track;
          return o.kind === 'ghost' && track && o.anchors.player_id ? [{ team: (o.anchors.player_id.startsWith('ash') ? 'ash' : 'kes') as Team, at: at(track, t) }] : [];
        });
        const frame: Frame3D = {
          t,
          now: wall,
          pos,
          fieldPos,
          ball: bx === fs.ballXY[0] && by === fs.ballXY[1] ? fs.ball : [bx, by, 0.11],
          field: L.cf ? fs.cfField : fs.field,
          strength: L.strength,
          levels: L.levels,
          dim,
          highlight: L.hint,
          follow: L.fav,
          ghosts: ghostFigures,
          focus: [...focus, ...ghostFigures.map((g) => g.at)],
          reduced: L.reduced,
        };
        scene.render(frame);
        animating = overlayAnimating;
        const resting = animating || scene.moving() ? 'false' : 'true';
        if (stage.dataset.resting !== resting) stage.dataset.resting = resting;
        // Separate from resting: the scene is complete, even if something in it is mid-entrance (a clip's frozen frame).
        const complete = scene.ready() ? 'true' : 'false';
        if (stage.dataset.ready !== complete) stage.dataset.ready = complete;

        // Labels and focus targets, by projection. Layout units match the 2D pitch: px / u, from (−30, −30).
        const units = (p: XY | null, dx = 0, dy = 0): XY | null => (p ? [(p[0] + dx) / u - 30, (p[1] + dy) / u - 30] : null);
        const resolve = (a: Anchor): Resolved | null => {
          switch (a.kind) {
            case 'player': {
              const p = pos[a.id];
              return p ? wrap(units(scene.project(p[0], p[1], HEAD_Z))) : null;
            }
            case 'point':
              return wrap(units(scene.project(a.at[0], a.at[1], 0)));
            case 'ring': {
              // Above the ring as it appears on screen, from the extremes of its projected points; below it or beside
              // it when a player stands where the label would go.
              let top: XY | null = null;
              let bottom: XY | null = null;
              let left: XY | null = null;
              let right: XY | null = null;
              let cxs = 0;
              let cys = 0;
              let n = 0;
              for (let i = 0; i < 16; i++) {
                const ang = (i / 16) * Math.PI * 2;
                const q = scene.project(a.centre[0] + a.rx * Math.cos(ang), a.centre[1] + a.ry * Math.sin(ang), 0);
                if (!q) continue;
                cxs += q[0];
                cys += q[1];
                n++;
                if (!top || q[1] < top[1]) top = q;
                if (!bottom || q[1] > bottom[1]) bottom = q;
                if (!left || q[0] < left[0]) left = q;
                if (!right || q[0] > right[0]) right = q;
              }
              if (!top || !bottom || !left || !right || !n) return null;
              const above = units([cxs / n, top[1]], 0, -12);
              const below = units([cxs / n, bottom[1]], 0, 12 + 20 * u);
              const east = units([right[0], cys / n], 10, 7 * u);
              const west = units([left[0], cys / n], -10, 7 * u);
              if (!above || !below || !east || !west) return null;
              return { at: above, alts: ringSpots(above, below, east[0], west[0], east[1], (east[0] - west[0]) / 2) };
            }
            case 'backline':
              // On the line a few metres inside the far touchline, so the label stays on the grass, off the boards.
              return wrap(units(scene.project(105 - fs.depth, 61, 0), 0, -8));
            case 'pulled': {
              const p = pos[a.id];
              if (!p) return null;
              const from = a.from ?? p;
              return wrap(units(scene.project((from[0] + p[0]) / 2, (from[1] + p[1]) / 2, 0)));
            }
            case 'ghost': {
              const g = at(a.track, t);
              return wrap(units(scene.project(g[0], g[1], HEAD_Z)));
            }
          }
        };
        const w = box.clientWidth;
        const h = box.clientHeight;
        layer.place({
          u,
          resolve,
          players: PLAYERS.map((p) => (pos[p.id] ? units(scene.project(pos[p.id][0], pos[p.id][1], BODY_Z)) : null)),
          // Labels hang from the heads, and keep clear of whole figures: head, body and feet.
          dots: PLAYERS.flatMap((p) => (pos[p.id] ? [HEAD_Z, BODY_Z, 0].map((z) => units(scene.project(pos[p.id][0], pos[p.id][1], z))) : [])),
          bounds: { x0: -30, y0: -30, x1: w / u - 30, y1: h / u - 30 },
        });
      }, PRIO.draw);
    };

    void (async () => {
      try {
        const { createScene3D } = await import('../../three/scene3d');
        if (disposed) return;
        const scene = await createScene3D(canvas, { tier, dpr: Math.min(MAX_DPR, window.devicePixelRatio || 1), onLost: () => failRef.current('The 3D view lost its graphics device.') });
        if (disposed) {
          scene.dispose();
          return;
        }
        start(scene);
        setStatus('ready');
      } catch (err) {
        if (!disposed) failRef.current(err instanceof Error ? err.message : String(err));
      }
    })();

    return () => {
      disposed = true;
      stop?.();
      ro?.disconnect();
      document.fonts?.removeEventListener('loadingdone', fontsLoaded);
      sceneRef.current?.dispose();
      sceneRef.current = null;
    };
    // A new tier needs a new engine; everything else reaches the loop through `latest`.
  }, [tier]);

  // The snapshot (PRD 16.8): the scene drawn again and copied at once, with the labels where they are. PNG only: the
  // 3D picture is pixels.
  useEffect(() => {
    if (!snapshot) return;
    const shooter: Snapshotter = {
      formats: ['png'],
      take: async (_format, scale) => {
        const box = boxRef.current;
        const canvas = canvasRef.current;
        const stage = stageRef.current;
        const scene = sceneRef.current;
        if (!box || !canvas || !stage || !scene) throw new Error('The 3D view isn’t ready');
        const r = box.getBoundingClientRect();
        const c = canvas.getBoundingClientRect();
        const out = document.createElement('canvas');
        out.width = Math.round(r.width * scale);
        out.height = Math.round(r.height * scale);
        const ctx = out.getContext('2d');
        if (!ctx) throw new Error('No canvas for the snapshot');
        ctx.scale(scale, scale);
        ctx.imageSmoothingQuality = 'high';
        scene.capture(ctx, c.left - r.left, c.top - r.top, c.width, c.height);
        paintDomToCanvas(ctx, Array.from(stage.querySelectorAll('.pitch-labels, .goal-banner')), r, 1);
        return { width: r.width, height: r.height, canvas: out };
      },
    };
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
  const onClick = (e: MouseEvent<HTMLDivElement>) => {
    const i = layer.hit(e, e.currentTarget.getBoundingClientRect());
    if (i < 0) return;
    layer.buttons.current[i]?.focus({ preventScroll: true });
    onPlayerClick?.(PLAYERS[i].id);
  };

  const caption = items.find((a) => a.overlay.kind === 'caption');
  const sceneLabel = `${VIEW_NAMES[view]} view of the pitch, Kestrel Bay attacking ${view === 'goal' ? 'towards the camera' : 'left to right'}${cf && !ghosts ? ', without No. 9’s run' : ''}. ${caption ? (caption.overlay.a11y_text[lang] ?? caption.overlay.text[lang] ?? '') : ''}`;

  return (
    <div ref={boxRef} className={cx('pitch', 'pitch-3d', portrait && 'pitch-3d-portrait', dim && 'pitch-dim')} dir="ltr" data-view={view}>
      <canvas ref={canvasRef} className="pitch-3d-canvas" role="img" aria-label={sceneLabel} />
      {status === 'loading' && (
        <div className="pitch-3d-loading" role="status">
          <Spinner /> Loading the 3D view…
        </div>
      )}
      <div ref={stageRef} className="pitch-stage" hidden={status !== 'ready'} onPointerMove={onPointerMove} onPointerLeave={() => layer.setHovered(null)} onClick={onClick}>
        <PitchLabels layer={layer} labels={labels} pins={pins} lang={lang} />
        {!cf && t >= T_GOAL && (
          <div className="goal-banner anim-pop" aria-hidden="true" style={{ top: 'calc(4% + 30px)' }}>
            {pack.ui.goal}
          </div>
        )}
        <PlayerTargets layer={layer} mode={mode} fav={fav} onFollow={onFollow} />
      </div>
      {scrim}
      {chips && <div className="pitch-chips">{chips}</div>}
      {corner && <div className="pitch-corner">{corner}</div>}
    </div>
  );
}

const wrap = (at: XY | null): Resolved | null => (at ? { at } : null);
