import { useEffect, useRef, type PointerEvent, type ReactNode } from 'react';
import { FIELD_GRID, controlField, type Body } from '../../lib/field';
import { PRIO, onFrame } from '../../lib/frame-loop';
import type { Pattern } from '../../lib/kits';
import type { Team, XY } from '../../lib/match';
import type { Order, PlayRun } from '../../lib/player/api';
import { Pitch, SIZE, project } from '../pitch';
import { drawContours, drawScene, newDrawState, paintField, readStyle, type DrawPlayer, type Scene2D, type Theme2D } from '../pitch/render2d';
import { dotScaleFor } from '../match/Stage2D';

const MAX_DPR = 2;
const HIT_M = 2.6;
const DRAG_PX = 6;

/** A run being played back on the board: its frames, and when playback started (performance.now()). */
export interface Playback {
  run: PlayRun;
  ids: readonly string[];
  stepMs: number;
  startedAt: number;
}

/** Where a tap landed: on a player, in front of the goal being attacked, or on open grass. */
export interface Tap {
  player: string | null;
  xy: XY;
  goal: boolean;
}

export interface PlayBoardProps {
  positions: Readonly<Record<string, XY>>;
  ballOwner: string;
  orders: readonly Order[];
  sideOf: (id: string) => Team;
  numOf: (id: string) => number;
  /** Players the viewer is giving orders to: a dashed ring says they can be picked. */
  commandable: (id: string) => boolean;
  selected: string | null;
  /** The x of the goal the side on the ball attacks. */
  goalX: number;
  /** The defence's offside line, drawn dashed while setting up. */
  offsideX: number | null;
  playback: Playback | null;
  editable: boolean;
  patterns: { kes: Pattern; ash: Pattern };
  reduced: boolean;
  label: string;
  banner?: ReactNode;
  chips?: ReactNode;
  onMove: (id: string, xy: XY) => void;
  onTap: (tap: Tap) => void;
}

const sampleRun = (p: Playback, now: number): { pos: Record<string, XY>; ball: XY; done: boolean } => {
  const n = p.run.frames.length;
  const f = Math.max(0, (now - p.startedAt) / p.stepMs);
  const i = Math.min(n - 1, Math.floor(f));
  const j = Math.min(n - 1, i + 1);
  const u = Math.min(1, f - i);
  const a = p.run.frames[i];
  const b = p.run.frames[j];
  const pos: Record<string, XY> = {};
  p.ids.forEach((id, k) => {
    pos[id] = [a[2 * k] + (b[2 * k] - a[2 * k]) * u, a[2 * k + 1] + (b[2 * k + 1] - a[2 * k + 1]) * u];
  });
  const ba = p.run.ball[i];
  const bb = p.run.ball[j];
  return { pos, ball: [ba[0] + (bb[0] - ba[0]) * u, ba[1] + (bb[1] - ba[1]) * u], done: f >= n - 1 };
};

function arrow(ctx: CanvasRenderingContext2D, a: XY, b: XY, size = 16) {
  const ang = Math.atan2(b[1] - a[1], b[0] - a[0]);
  ctx.beginPath();
  ctx.moveTo(a[0], a[1]);
  ctx.lineTo(b[0], b[1]);
  ctx.stroke();
  ctx.setLineDash([]);
  ctx.beginPath();
  ctx.moveTo(b[0], b[1]);
  ctx.lineTo(b[0] - size * Math.cos(ang - 0.45), b[1] - size * Math.sin(ang - 0.45));
  ctx.lineTo(b[0] - size * Math.cos(ang + 0.45), b[1] - size * Math.sin(ang + 0.45));
  ctx.closePath();
  ctx.fill();
}

/** Every order as the board's grammar draws it: runs solid, support dashed, carries dotted, passes white and
 * dashed, a shot in lime to the goal, pressing and marking as tethers, a held spot as a ring. */
function drawOrders(ctx: CanvasRenderingContext2D, orders: readonly Order[], pos: Readonly<Record<string, XY>>, ballOwner: string, goalX: number, T: Theme2D, colour: (id: string) => string, alpha: number) {
  const P = (p: XY) => project('h', p[0], p[1]);
  ctx.save();
  ctx.globalAlpha = alpha;
  ctx.lineCap = 'round';
  for (const o of orders) {
    const from = pos[o.player_id];
    if (!from) continue;
    const a = P(from);
    const c = colour(o.player_id);
    ctx.strokeStyle = c;
    ctx.fillStyle = c;
    ctx.lineWidth = 4;
    ctx.setLineDash([]);
    const to = o.to_xy ? P(o.to_xy) : null;
    const target = o.target_id && pos[o.target_id] ? P(pos[o.target_id]) : null;
    switch (o.action) {
      case 'run':
        if (to) arrow(ctx, a, to);
        break;
      case 'support':
        ctx.setLineDash([10, 8]);
        if (to) arrow(ctx, a, to);
        break;
      case 'carry':
        ctx.strokeStyle = ctx.fillStyle = T.ball;
        ctx.setLineDash([3, 7]);
        if (to) arrow(ctx, a, to);
        break;
      case 'pass':
        ctx.strokeStyle = ctx.fillStyle = T.text;
        ctx.lineWidth = 3;
        ctx.setLineDash([12, 8]);
        if (target) arrow(ctx, o.player_id === ballOwner ? a : a, target);
        break;
      case 'shoot':
        ctx.strokeStyle = ctx.fillStyle = T.space;
        ctx.lineWidth = 5;
        arrow(ctx, a, P([goalX, 34]), 20);
        break;
      case 'press':
        if (pos[ballOwner]) arrow(ctx, a, P(pos[ballOwner]));
        break;
      case 'mark':
      case 'track':
      case 'cover':
        ctx.setLineDash(o.action === 'mark' ? [2, 6] : [8, 6]);
        if (target) {
          ctx.beginPath();
          ctx.moveTo(a[0], a[1]);
          ctx.lineTo(target[0], target[1]);
          ctx.stroke();
        }
        break;
      case 'hold':
        if (to) {
          ctx.setLineDash([6, 6]);
          ctx.beginPath();
          ctx.arc(to[0], to[1], 20, 0, Math.PI * 2);
          ctx.stroke();
          ctx.beginPath();
          ctx.moveTo(a[0], a[1]);
          ctx.lineTo(to[0], to[1]);
          ctx.stroke();
        }
        break;
    }
    if (o.at_s > 0) {
      // When the order starts, beside the player.
      ctx.setLineDash([]);
      ctx.font = `700 15px ${T.font}`;
      ctx.lineWidth = 4;
      ctx.strokeStyle = T.halo;
      ctx.fillStyle = T.text;
      ctx.strokeText(`${o.at_s.toFixed(1)}s`, a[0] + 16, a[1] - 16);
      ctx.fillText(`${o.at_s.toFixed(1)}s`, a[0] + 16, a[1] - 16);
    }
  }
  ctx.restore();
}

/**
 * Play it out's board: the pitch drawn as the match view draws it, where the viewer drags players, taps to give
 * orders and watches the engine's runs play back. Positions in, moves and taps out; it keeps no state of its own.
 */
export function PlayBoard(props: PlayBoardProps) {
  const { label, banner, chips } = props;
  const stageRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const contourRef = useRef<HTMLCanvasElement>(null);
  const fieldRef = useRef<HTMLCanvasElement>(null);
  const latest = useRef(props);
  latest.current = props;
  const dirty = useRef(true);
  const drag = useRef<{ id: string; x: number; y: number; moved: boolean } | null>(null);

  useEffect(() => {
    dirty.current = true;
  });

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
    let view = { w: 0, u: 0 };
    let animating = true;
    let lastKey = '';
    let lastPositions: unknown = null;
    let edits = 0;
    const ro = new ResizeObserver(([entry]) => {
      view = { w: entry.contentRect.width, u: entry.contentRect.width / SIZE.h[0] };
      stage.style.setProperty('--u', view.u.toFixed(4));
      dirty.current = true;
    });
    ro.observe(stage);
    const mo = new MutationObserver(() => {
      style = readStyle(stage);
      dirty.current = true;
    });
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme', 'class', 'style'] });
    const host = stage.closest('.whole-match');
    if (host) mo.observe(host, { attributes: true, attributeFilter: ['style'] });

    const stop = onFrame((wall) => {
      const L = latest.current;
      if (!view.w) return;
      const playing = !!L.playback;
      if (!dirty.current && !animating && !playing) return;
      dirty.current = false;
      const dpr = Math.min(MAX_DPR, window.devicePixelRatio || 1);
      const bw = Math.round(view.w * dpr);
      const bh = Math.round(((view.w * SIZE.h[1]) / SIZE.h[0]) * dpr);
      if (canvas.width !== bw || canvas.height !== bh) {
        canvas.width = contourCanvas.width = bw;
        canvas.height = contourCanvas.height = bh;
      }
      const shown = L.playback ? sampleRun(L.playback, performance.now()) : null;
      const pos = shown?.pos ?? L.positions;
      const ball: XY = shown?.ball ?? L.positions[L.ballOwner] ?? [52.5, 34];
      // The field and its contour follow the players: once per 80 ms of playback, or per edit.
      if (L.positions !== lastPositions) {
        lastPositions = L.positions;
        edits++;
      }
      const key = `${L.playback ? `${L.playback.startedAt}:${Math.floor((performance.now() - L.playback.startedAt) / L.playback.stepMs)}` : `e${edits}`}:${bw}`;
      if (key !== lastKey) {
        lastKey = key;
        const bodies: Body[] = Object.entries(pos).map(([id, [x, y]]) => ({ team: L.sideOf(id), x, y }));
        const field = controlField(bodies, FIELD_GRID);
        paintField(fctx, img, field, FIELD_GRID, 0.55, 'h', style.field);
        drawContours(cctx, { w: view.w, dpr }, 'h', field, FIELD_GRID, [0.5], style.theme, state, key);
      }
      const ds = dotScaleFor(view.u);
      const players: DrawPlayer[] = Object.keys(pos).map((id) => {
        const team = L.sideOf(id);
        return {
          id,
          team,
          num: L.numOf(id),
          at: pos[id],
          dim: false,
          follow: id === L.selected,
          highlight: false,
          focusRing: false,
          pickable: !L.playback && L.editable && L.commandable(id) && id !== L.selected,
          pattern: L.patterns[team],
        };
      });
      const scene: Scene2D = {
        o: 'h',
        now: wall,
        t: 0,
        reduced: L.reduced,
        theme: style.theme,
        motion: style.motion,
        players,
        pos,
        ball,
        trail: [],
        items: [],
        ahead: (id) => pos[id],
        depth: 0,
        density: 'standard',
        goal: false,
        dotScale: ds,
        teamOf: L.sideOf,
        scripted: false,
      };
      animating = drawScene(ctx, { w: view.w, dpr }, scene, state);
      // drawScene leaves the pitch's transform in place, so the orders and the offside line draw in pitch units.
      const T = style.theme;
      if (L.offsideX !== null && !L.playback) {
        const [x] = project('h', L.offsideX, 0);
        ctx.save();
        ctx.globalAlpha = 0.7;
        ctx.strokeStyle = T.text;
        ctx.lineWidth = 2;
        ctx.setLineDash([10, 8]);
        ctx.beginPath();
        ctx.moveTo(x, 0);
        ctx.lineTo(x, 680);
        ctx.stroke();
        ctx.restore();
      }
      drawOrders(ctx, L.orders, L.playback ? L.positions : pos, L.ballOwner, L.goalX, T, (id) => (L.sideOf(id) === 'ash' ? T.ash : T.kes), L.playback ? 0.28 : 0.95);
    }, PRIO.draw);
    return () => {
      stop();
      ro.disconnect();
      mo.disconnect();
    };
  }, []);

  /** A pointer on the board, in pitch metres. */
  const toPitch = (e: PointerEvent<HTMLDivElement>): XY => {
    const r = e.currentTarget.getBoundingClientRect();
    const vx = ((e.clientX - r.left) / r.width) * SIZE.h[0] - 30;
    const vy = ((e.clientY - r.top) / r.height) * SIZE.h[1] - 30;
    return [Math.max(0.5, Math.min(104.5, vx / 10)), Math.max(0.5, Math.min(67.5, 68 - vy / 10))];
  };
  const hit = (xy: XY): string | null => {
    let best: string | null = null;
    let d = HIT_M;
    for (const [id, p] of Object.entries(latest.current.positions)) {
      const dd = Math.hypot(p[0] - xy[0], p[1] - xy[1]);
      if (dd < d) {
        d = dd;
        best = id;
      }
    }
    return best;
  };
  const onDown = (e: PointerEvent<HTMLDivElement>) => {
    if (!latest.current.editable || latest.current.playback) return;
    const xy = toPitch(e);
    const id = hit(xy);
    drag.current = id ? { id, x: e.clientX, y: e.clientY, moved: false } : null;
    e.currentTarget.setPointerCapture(e.pointerId);
  };
  const onMove = (e: PointerEvent<HTMLDivElement>) => {
    const d = drag.current;
    if (!d) return;
    if (!d.moved && Math.hypot(e.clientX - d.x, e.clientY - d.y) < DRAG_PX) return;
    d.moved = true;
    latest.current.onMove(d.id, toPitch(e));
  };
  const onUp = (e: PointerEvent<HTMLDivElement>) => {
    const L = latest.current;
    if (!L.editable || L.playback) return;
    const d = drag.current;
    drag.current = null;
    if (d?.moved) return;
    const xy = toPitch(e);
    const goal = Math.abs(xy[0] - L.goalX) < 7 && Math.abs(xy[1] - 34) < 11;
    L.onTap({ player: d?.id ?? hit(xy), xy, goal });
  };

  return (
    <Pitch
      label={label}
      orientation="h"
      field={<canvas ref={fieldRef} className="field-canvas" width={FIELD_GRID.cols} height={FIELD_GRID.rows} />}
      layers={
        <div ref={stageRef} className="pitch-stage board-stage" onPointerDown={onDown} onPointerMove={onMove} onPointerUp={onUp} onPointerCancel={() => (drag.current = null)}>
          <canvas ref={contourRef} className="pitch-canvas" aria-hidden="true" />
          <canvas ref={canvasRef} className="pitch-canvas" aria-hidden="true" />
          {banner}
        </div>
      }
      chips={chips}
    />
  );
}
