// SVG overlays for the pitch (PRD 15.2). Positions are in metres; the pitch context projects them for either orientation.
import type { CSSProperties, KeyboardEvent, Ref } from 'react';
import type { Pattern } from '../../lib/kits';
import type { Team, XY } from '../../lib/match';
import { arrowHead, translate, usePitch } from './geometry';

const labelStyle = (fill: string, size = 20): CSSProperties => ({ fill, fontSize: size });

interface PlayerDotProps {
  at: XY;
  team: Team;
  num: number;
  /** Accessible name, e.g. "Kestrel Bay No. 9, J. Velmar". */
  label: string;
  /** Shown on hover and focus: the name and a live number. */
  hint?: string;
  dim?: boolean;
  focus?: boolean;
  /** A kit pattern added when two teams' colours clash for colour-blind viewers (PRD 16.3). */
  pattern?: Pattern;
  /** Team colour override, for fixtures other than the showcase. */
  colour?: string;
  /** Roving focus: only one player in the pitch is a tab stop. Omit for decorative dots. */
  tabIndex?: number;
  playerRef?: Ref<SVGGElement>;
  onFocus?: () => void;
  onBlur?: () => void;
  onPointerEnter?: () => void;
  onKeyDown?: (e: KeyboardEvent<SVGGElement>) => void;
}

export function PlayerDot({ at, team, num, label, hint, dim = false, focus = false, pattern = 'plain', colour, tabIndex, playerRef, onFocus, onBlur, onPointerEnter, onKeyDown }: PlayerDotProps) {
  const { P } = usePitch();
  const fill = colour ?? `var(--${team})`;
  const interactive = tabIndex !== undefined;
  return (
    <g
      ref={playerRef}
      className={interactive ? 'player player-interactive' : 'player'}
      tabIndex={tabIndex}
      role={interactive ? 'button' : undefined}
      aria-label={interactive ? label : undefined}
      aria-hidden={interactive ? undefined : true}
      onFocus={onFocus}
      onBlur={onBlur}
      onPointerEnter={onPointerEnter}
      onKeyDown={onKeyDown}
      style={{ transform: translate(P(at)), opacity: dim ? 0.4 : 1, transition: 'opacity var(--dur-smooth)' }}
    >
      {focus && (
        <>
          <circle className="anim-ripple" r={22} style={{ fill: 'none', stroke: 'var(--space)', strokeWidth: 3 }} />
          <circle r={22} style={{ fill: 'none', stroke: 'var(--space)', strokeWidth: 3 }} />
        </>
      )}
      <circle className="player-dot" r={13} style={{ fill, stroke: 'var(--halo)', strokeWidth: 2.5 }} />
      {pattern === 'hoops' && <circle className="player-dot" r={8.5} style={{ fill: 'none', stroke: 'var(--halo)', strokeWidth: 2.5 }} />}
      {pattern === 'stripes' && <path d="M-4 -12 V12 M4 -12 V12" style={{ stroke: 'var(--halo)', strokeWidth: 2.2 }} />}
      <text className="player-num" y={4.5} style={{ fill: colour ? 'var(--bg)' : `var(--on-${team})` }}>
        {num}
      </text>
      {hint && (
        <text className="svg-label player-hint anim-fade" y={-26} style={labelStyle('var(--text)', 18)}>
          {hint}
        </text>
      )}
    </g>
  );
}

/** The ball, with a fading trail of recent positions during passes and shots (PRD 16.10). */
export function Ball({ at, trail = [] }: { at: XY; trail?: readonly XY[] }) {
  const { P } = usePitch();
  return (
    <g aria-hidden="true">
      {trail.map((p, i) => {
        const [x, y] = P(p);
        return <circle key={i} cx={x} cy={y} r={5 - i} style={{ fill: 'var(--ball)', opacity: 0.42 - i * 0.09 }} />;
      })}
      <circle r={6.5} style={{ transform: translate(P(at)), fill: 'var(--ball)', stroke: 'var(--ball-edge)', strokeWidth: 2 }} />
    </g>
  );
}

/** Ellipse radii in SVG units, swapped on the vertical pitch so the ellipse stays on the same patch of grass. */
function radii(o: 'h' | 'v', rx: number, ry: number): [number, number] {
  return o === 'h' ? [rx * 10, ry * 10] : [ry * 10, rx * 10];
}

/** Space that has just opened: the stroke draws, then pulses once. Remount it to replay. */
export function GapRing({ at, label, rx = 5.4, ry = 6.8, passFrom, ball, retracted = false }: { at: XY; label?: string; rx?: number; ry?: number; passFrom?: XY; ball?: XY; retracted?: boolean }) {
  const { o, P } = usePitch();
  const [cx, cy] = P(at);
  const [ex, ey] = radii(o, rx, ry);
  return (
    <g style={{ opacity: retracted ? 0.35 : 1, transition: 'opacity var(--dur-smooth)' }}>
      <ellipse className="anim-fade" cx={cx} cy={cy} rx={ex} ry={ey} style={{ fill: 'var(--space-fill)' }} />
      <ellipse className="ring-draw" cx={cx} cy={cy} rx={ex} ry={ey} pathLength={100} style={{ fill: 'none', stroke: 'var(--space)', strokeWidth: 4 }} />
      {passFrom && ball && <PassInto from={passFrom} ball={ball} to={at} />}
      {label && (
        <text className="svg-label anim-pop" x={cx} y={cy - ey - 16} style={{ ...labelStyle('var(--space-ink)', 21), animationDelay: 'var(--dur-smooth)' }}>
          {label}
        </text>
      )}
    </g>
  );
}

/** The pass into the gap, drawn as part of the ring in one-overlay-at-a-time modes. */
function PassInto({ from, ball, to }: { from: XY; ball: XY; to: XY }) {
  const { P } = usePitch();
  const [x0, y0] = P(from);
  const [x1, y1] = P(ball);
  const [x2, y2] = P(to);
  return (
    <g aria-hidden="true">
      <line x1={x0} y1={y0} x2={x1} y2={y1} style={{ stroke: 'var(--text)', strokeWidth: 4, strokeLinecap: 'round', opacity: 0.85 }} />
      <line x1={x1} y1={y1} x2={x2} y2={y2} style={{ stroke: 'var(--text)', strokeWidth: 3, strokeDasharray: '9 8', opacity: 0.7 }} />
    </g>
  );
}

/** The counterfactual result: the gap that never opened. */
export function ShutRing({ at, label, rx = 5.4, ry = 6.8 }: { at: XY; label?: string; rx?: number; ry?: number }) {
  const { o, P } = usePitch();
  const [cx, cy] = P(at);
  const [ex, ey] = radii(o, rx, ry);
  return (
    <g className="anim-shake">
      <ellipse cx={cx} cy={cy} rx={ex} ry={ey} style={{ fill: 'none', stroke: 'var(--muted)', strokeWidth: 3, strokeDasharray: '8 7' }} />
      <line x1={cx - 40} y1={cy - 40} x2={cx + 40} y2={cy + 40} style={{ stroke: 'var(--muted)', strokeWidth: 3, strokeLinecap: 'round' }} />
      {label && (
        <text className="svg-label" x={cx} y={cy - ey - 16} style={labelStyle('var(--text)', 21)}>
          {label}
        </text>
      )}
    </g>
  );
}

/**
 * A run: solid from where it started to the runner, dashed for the planned path ahead, with the arrowhead about
 * 0.8 s ahead of the runner so viewers see where the run is going (PRD 15.2, 16.10).
 */
export function RunArrow({ from, runner, ahead, color = 'var(--kes)' }: { from: XY; runner: XY; ahead: XY; color?: string }) {
  const { P } = usePitch();
  const a = P(from);
  const r = P(runner);
  const h = P(ahead);
  const tip = Math.hypot(h[0] - r[0], h[1] - r[1]) > 8 ? h : r;
  return (
    <g className="anim-fade" aria-hidden="true">
      <line x1={a[0]} y1={a[1]} x2={r[0]} y2={r[1]} style={{ stroke: color, strokeWidth: 5, strokeLinecap: 'round' }} />
      {tip === h && <line x1={r[0]} y1={r[1]} x2={h[0]} y2={h[1]} style={{ stroke: color, strokeWidth: 4, strokeDasharray: '8 7', strokeLinecap: 'round' }} />}
      <polygon points={arrowHead(tip === h ? r : a, tip)} style={{ fill: color }} />
    </g>
  );
}

/** A pass: solid behind the ball, dashed ahead; line weight carries difficulty (0–10); the head pops on arrival. */
export function PassLine({ from, ball, to, difficulty = 6, arrived = false, retracted = false }: { from: XY; ball: XY; to: XY; difficulty?: number; arrived?: boolean; retracted?: boolean }) {
  const { P } = usePitch();
  const weight = 2 + difficulty * 0.5;
  const [x0, y0] = P(from);
  const [x1, y1] = P(ball);
  const [x2, y2] = P(to);
  return (
    <g aria-hidden="true" style={{ opacity: retracted ? 0.35 : 1, transition: 'opacity var(--dur-smooth)' }}>
      <line x1={x0} y1={y0} x2={x1} y2={y1} style={{ stroke: 'var(--text)', strokeWidth: weight, strokeLinecap: 'round' }} />
      {!arrived && <line x1={x1} y1={y1} x2={x2} y2={y2} style={{ stroke: 'var(--text)', strokeWidth: 3, strokeDasharray: '9 8', opacity: 0.8 }} />}
      {arrived && <polygon key="arrived" className="anim-pop" points={arrowHead([x0, y0], [x2, y2])} style={{ fill: 'var(--text)' }} />}
    </g>
  );
}

/** Where a player would have been: a dashed outline, never filled, always labelled (PRD 15.2: translucent and desaturated). */
export function Ghost({ at, team, label }: { at: XY; team: Team; label: string }) {
  const { P } = usePitch();
  return (
    <g style={{ transform: translate(P(at)) }} aria-hidden="true">
      <g className="anim-pop">
        <circle r={13} style={{ fill: `var(--${team})`, opacity: 0.18 }} />
        <circle r={13} style={{ fill: 'none', stroke: `var(--${team})`, strokeWidth: 3, strokeDasharray: '5 4', opacity: 0.9 }} />
        <text className="svg-label" y={-24} style={labelStyle('var(--text)', 17)}>
          {label}
        </text>
      </g>
    </g>
  );
}

/** A label on a halo at a position already laid out in SVG units. Pops in when it first appears. */
export function Tag({ x, y, text, color = 'var(--text)', size = 20 }: { x: number; y: number; text: string; color?: string; size?: number }) {
  return (
    <text className="svg-label anim-pop" x={x} y={y} style={labelStyle(color, size)}>
      {text}
    </text>
  );
}

/** The defending team's last line (offside_line), with its distance from goal. */
export function BackLine({ x, label }: { x: number; label: string }) {
  const { o, P } = usePitch();
  const [x1, y1] = P([x, 0]);
  const [x2, y2] = P([x, 68]);
  const [lx, ly] = o === 'h' ? [x2, y2 - 8] : [x1 + 8, y1 - 8];
  return (
    <g className="anim-fade" aria-hidden="true">
      <line x1={x1} y1={y1} x2={x2} y2={y2} style={{ stroke: 'var(--text)', strokeWidth: 2, strokeDasharray: '10 8', opacity: 0.6 }} />
      <text x={lx} y={ly} style={{ fontFamily: 'var(--font-body)', fontSize: 18, fontWeight: 600, fill: 'var(--muted)', textAnchor: o === 'h' ? 'middle' : 'end', paintOrder: 'stroke', stroke: 'var(--halo)', strokeWidth: 5 }}>
        {label}
      </text>
    </g>
  );
}

/** How far a defender was pulled: dashed in the defending team's colour, with the distance in metres. */
export function Displacement({ from, to, label }: { from: XY; to: XY; label: string }) {
  const { P } = usePitch();
  const [x0, y0] = P(from);
  const [x1, y1] = P(to);
  return (
    <g className="anim-fade" aria-hidden="true">
      <line x1={x0} y1={y0} x2={x1} y2={y1} style={{ stroke: 'var(--ash)', strokeWidth: 3, strokeDasharray: '6 6' }} />
      <circle cx={x0} cy={y0} r={5} style={{ fill: 'var(--ash)' }} />
      <text x={(x0 + x1) / 2 + 14} y={(y0 + y1) / 2} style={{ fontFamily: 'var(--font-mono)', fontSize: 20, fill: 'var(--text)', paintOrder: 'stroke', stroke: 'var(--halo)', strokeWidth: 6, strokeLinejoin: 'round' }}>
        {label}
      </text>
    </g>
  );
}

/** Particles radiating from the ball, once per goal. They end invisible, so nothing is left behind. */
export function GoalBurst({ at, count = 14 }: { at: XY; count?: number }) {
  const { P } = usePitch();
  const [cx, cy] = P(at);
  return (
    <g aria-hidden="true">
      {Array.from({ length: count }, (_, i) => {
        const angle = (i / count) * Math.PI * 2;
        const dist = 70 + (i % 3) * 26;
        const style = {
          fill: i % 2 ? 'var(--space)' : 'var(--kes)',
          '--dx': `${(Math.cos(angle) * dist).toFixed(0)}px`,
          '--dy': `${(Math.sin(angle) * dist).toFixed(0)}px`,
          animationDelay: `calc(${i % 4} * var(--stagger) / 1.33)`,
        } as CSSProperties;
        return <circle key={i} className="burst" cx={cx} cy={cy} r={3 + (i % 3)} style={style} />;
      })}
      {/* With reduced motion the particles are dropped and one still ring marks the ball instead. */}
      <circle className="burst-rest" cx={cx} cy={cy} r={30} style={{ fill: 'var(--space-fill)', stroke: 'var(--space)', strokeWidth: 3 }} />
    </g>
  );
}

export function GoalBanner({ text }: { text: string }) {
  const { o } = usePitch();
  const centre = o === 'h' ? 525 : 340;
  const width = Math.min(o === 'h' ? 420 : 560, 40 + text.length * 20);
  return (
    <g className="anim-pop" aria-hidden="true">
      <rect x={centre - width / 2} y={14} width={width} height={58} rx={8} style={{ fill: 'var(--space)' }} />
      <text x={centre} y={55} style={{ fontFamily: 'var(--font-display)', fontSize: 36, fontWeight: 700, fill: 'var(--on-space)', textAnchor: 'middle', letterSpacing: 1 }}>
        {text}
      </text>
    </g>
  );
}

/** A small stat card pinned near a player, for broadcaster graphics (stat_card). */
export function StatPin({ at, title, value }: { at: XY; title: string; value: string }) {
  const { P } = usePitch();
  const [x, y] = P(at);
  return (
    <g className="anim-rise" aria-hidden="true" style={{ transform: `translate(${x + 30}px, ${y - 70}px)` }}>
      <rect width={170} height={64} rx={8} style={{ fill: 'var(--chip-bg)', stroke: 'var(--line)' }} />
      <text x={12} y={22} style={{ fontFamily: 'var(--font-body)', fontSize: 12, fontWeight: 700, letterSpacing: '0.08em', fill: 'var(--muted)' }}>
        {title}
      </text>
      <text x={12} y={52} style={{ fontFamily: 'var(--font-display)', fontSize: 30, fontWeight: 700, fill: 'var(--text)' }}>
        {value}
      </text>
    </g>
  );
}
