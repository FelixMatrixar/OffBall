import { useEffect, useRef, type CSSProperties, type ReactNode } from 'react';
import type { ActiveOverlay } from '../../lib/feed';
import type { Overlay } from '../../lib/feed/types';
import { FIELD_GRID, controlField, type Body } from '../../lib/field';
import { PRIO, onFrame } from '../../lib/frame-loop';
import type { Pattern } from '../../lib/kits';
import type { Team, XY } from '../../lib/match';
import type { Position } from '../../lib/player/clock';
import type { MatchFrames } from '../../lib/player/frames';
import type { WhatIf } from '../../lib/player/api';
import { whatIfItems } from '../../lib/player/whatif';
import { Pitch, SIZE, project, type Orientation } from '../pitch';
import { drawContours, drawScene, newDrawState, paintField, readStyle, type DrawPlayer, type Scene2D } from '../pitch/render2d';
import { dodge, dotScaleFor } from '../match/Stage2D';

const MAX_DPR = 2;

/** A word on the pitch: over a player, who it follows every frame, or at a fixed spot such as a ring. */
export interface PitchWord {
  id: string;
  text: string;
  player_id?: string;
  at?: XY;
  tone?: 'text' | 'space';
}

export interface PlayerPitchProps {
  frames: MatchFrames;
  /** Match time now, read every frame. */
  now: () => number;
  toPosition: (g: number) => Position;
  sideOf: (id: string) => Team;
  numOf: (id: string) => number;
  /** Pitch graphics in the viewer's mode, every period. */
  overlays: readonly Overlay[];
  /** A what-if shown on the pitch: the ghosts of the players free to react, and the gap. */
  whatIf: WhatIf | null;
  patterns: { kes: Pattern; ash: Pattern };
  orientation: Orientation;
  fieldStrength: number;
  /** Control levels traced as contour lines. */
  levels: readonly number[];
  reduced: boolean;
  words: readonly PitchWord[];
  label: string;
  scrim?: ReactNode;
  chips?: ReactNode;
  corner?: ReactNode;
  dim?: boolean;
  style?: CSSProperties;
}

/**
 * One 2D pitch for a whole match (PRD 10.1), drawn as the showcase's is: the control field and its contours, the
 * crew's graphics and the players, every display frame from the frames around the clock, with the words on the pitch
 * kept in place in the DOM so they stay sharp and readable.
 */
export function PlayerPitch({ frames, now, toPosition, sideOf, numOf, overlays, whatIf, patterns, orientation, fieldStrength, levels, reduced, words, label, scrim, chips, corner, dim, style }: PlayerPitchProps) {
  const stageRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const contourRef = useRef<HTMLCanvasElement>(null);
  const fieldRef = useRef<HTMLCanvasElement>(null);
  const wordRefs = useRef(new Map<string, HTMLSpanElement>());
  const latest = useRef({ overlays, whatIf, patterns, fieldStrength, levels, reduced, words, sideOf, numOf, toPosition, now });
  latest.current = { overlays, whatIf, patterns, fieldStrength, levels, reduced, words, sideOf, numOf, toPosition, now };
  const dirty = useRef(true);

  useEffect(() => {
    dirty.current = true;
  });

  useEffect(() => {
    const o = orientation;
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
    let view = { w: 0, u: 0 };
    let lastG = Number.NaN;
    let lastFrame = '';
    let field: Float32Array | null = null;
    let animating = true;
    const ro = new ResizeObserver(([entry]) => {
      view = { w: entry.contentRect.width, u: entry.contentRect.width / SIZE[o][0] };
      stage.style.setProperty('--u', view.u.toFixed(4));
      lastFrame = '';
      dirty.current = true;
    });
    ro.observe(stage);
    // The theme or the fixture's colours changed: read the tokens again.
    const mo = new MutationObserver(() => {
      style = readStyle(stage);
      lastFrame = '';
      dirty.current = true;
    });
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme', 'class', 'style'] });
    const host = stage.closest('.whole-match');
    if (host) mo.observe(host, { attributes: true, attributeFilter: ['style'] });

    const stop = onFrame((wall) => {
      const L = latest.current;
      if (!view.w) return;
      const g = L.now();
      if (g === lastG && !dirty.current && !animating) return;
      lastG = g;
      const changed = dirty.current;
      dirty.current = false;
      const dpr = Math.min(MAX_DPR, window.devicePixelRatio || 1);
      const bw = Math.round(view.w * dpr);
      const bh = Math.round(((view.w * SIZE[o][1]) / SIZE[o][0]) * dpr);
      if (canvas.width !== bw || canvas.height !== bh) {
        canvas.width = contourCanvas.width = bw;
        canvas.height = contourCanvas.height = bh;
        lastFrame = '';
      }
      const { period, t_ms } = L.toPosition(g);
      const s = frames.sample(period, t_ms);
      if (!s) {
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        cctx.clearRect(0, 0, contourCanvas.width, contourCanvas.height);
        fctx.clearRect(0, 0, fieldCanvas.width, fieldCanvas.height);
        lastFrame = '';
        return;
      }
      const ds = dotScaleFor(view.u);
      const pos = dodge(s.pos, 2.3 * ds);
      // The field and its contours follow the 25 Hz data, so they're worked out once per data frame.
      const frameKey = `${period}:${Math.round(t_ms / 40)}:${L.levels.join()}:${bw}`;
      if (frameKey !== lastFrame || changed) {
        lastFrame = frameKey;
        const bodies: Body[] = Object.entries(s.pos).map(([id, [x, y]]) => ({ team: L.sideOf(id), x, y }));
        field = controlField(bodies, FIELD_GRID);
        if (L.fieldStrength > 0) paintField(fctx, img, field, FIELD_GRID, L.fieldStrength, o, style.field);
        else fctx.clearRect(0, 0, fieldCanvas.width, fieldCanvas.height);
        drawContours(cctx, { w: view.w, dpr }, o, L.fieldStrength > 0 ? field : null, FIELD_GRID, L.levels, style.theme, state, frameKey);
      }
      const extra = L.whatIf && L.whatIf.period === period ? whatIfItems(L.whatIf) : [];
      const items: ActiveOverlay[] = [...extra, ...L.overlays].filter((ov) => ov.period === period && ov.t_start_ms <= t_ms && t_ms < ov.t_end_ms).map((overlay) => ({ overlay }));
      const players: DrawPlayer[] = Object.keys(s.pos).map((id) => {
        const team = L.sideOf(id);
        return { id, team, num: L.numOf(id), at: pos[id], dim: false, follow: false, highlight: false, focusRing: false, pattern: L.patterns[team] };
      });
      const scene: Scene2D = {
        o,
        now: wall,
        t: t_ms / 1000,
        reduced: L.reduced,
        theme: style.theme,
        motion: style.motion,
        players,
        pos,
        ball: [s.ball[0], s.ball[1]],
        trail: frames.trail(period, t_ms),
        items,
        ahead: (id, lead) => frames.ahead(period, t_ms, id, lead) ?? pos[id],
        depth: 0,
        density: 'standard',
        goal: false,
        dotScale: ds,
        teamOf: L.sideOf,
        scripted: false,
      };
      animating = drawScene(ctx, { w: view.w, dpr }, scene, state);
      // Words ride with their players, placed here every frame without a React render.
      for (const word of L.words) {
        const el = wordRefs.current.get(word.id);
        if (!el) continue;
        const at: XY | undefined = word.player_id ? pos[word.player_id] : word.at;
        if (!at) {
          el.style.opacity = '0';
          continue;
        }
        const [px, py] = project(o, at[0], at[1]);
        // A word over a player sits above the dot; one on a ring sits on its top edge.
        const lift = word.player_id ? 22 * ds : 0;
        el.style.opacity = '1';
        el.style.transform = `translate(${((px + 30) * view.u).toFixed(1)}px, ${((py + 30 - lift) * view.u).toFixed(1)}px)`;
      }
    }, PRIO.draw);
    return () => {
      stop();
      ro.disconnect();
      mo.disconnect();
    };
  }, [frames, orientation]);

  const [fw, fh] = orientation === 'h' ? [FIELD_GRID.cols, FIELD_GRID.rows] : [FIELD_GRID.rows, FIELD_GRID.cols];
  return (
    <Pitch
      label={label}
      orientation={orientation}
      style={style}
      dim={dim}
      field={<canvas key={orientation} ref={fieldRef} className="field-canvas" width={fw} height={fh} />}
      layers={
        <div ref={stageRef} className="pitch-stage">
          <canvas ref={contourRef} className="pitch-canvas" aria-hidden="true" />
          <canvas ref={canvasRef} className="pitch-canvas" aria-hidden="true" />
          <div className="pitch-labels" aria-hidden="true">
            {words.map((word) => (
              <span
                key={word.id}
                className="pitch-label"
                style={{ opacity: 0 }}
                ref={(el) => {
                  if (el) wordRefs.current.set(word.id, el);
                  else wordRefs.current.delete(word.id);
                }}
              >
                <span className={`pitch-label-text anim-pop${word.tone === 'space' ? ' tone-space' : ''}`} style={{ ['--size' as string]: word.player_id ? 18 : 20 }}>
                  {word.text}
                </span>
              </span>
            ))}
          </div>
        </div>
      }
      scrim={scrim}
      chips={chips}
      corner={corner}
    />
  );
}
