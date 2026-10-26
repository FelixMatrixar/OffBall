// Pitch-anchored charts use OffBall's own pitch renderer (PRD 16.4): pass network, shot map, heat map and run map.
import type { CSSProperties, ReactNode } from 'react';
import { player, type XY } from '../../lib/match';
import { occupancy, passNetwork, runMap, shots as servedShots, type RunLine, type Shot } from '../../lib/stats';
import { PitchMarkings } from '../pitch/Pitch';
import { arrowHead, project } from '../pitch/geometry';

const P = (p: XY) => project('h', p[0], p[1]);
const text: CSSProperties = { fontFamily: 'var(--font-body)', fontWeight: 700, textAnchor: 'middle' };

function MiniPitch({ label, children, half = false }: { label: string; children: ReactNode; half?: boolean }) {
  return (
    <svg viewBox={half ? '495 -30 585 740' : '-30 -30 1110 740'} role="img" aria-label={label} style={{ width: '100%', height: 'auto', display: 'block', borderRadius: 8, direction: 'ltr' }}>
      <PitchMarkings />
      {children}
    </svg>
  );
}

/** Kestrel Bay's pass network: who passes to whom, and where they stand on average. */
export function PassNetwork() {
  const network = passNetwork();
  const nodes = new Map(network.nodes.map((n) => [n.id, n]));
  return (
    <MiniPitch label="Kestrel Bay pass network: average positions, with thicker lines for more passes. The full table is in the table view.">
      {network.edges.map((e) => {
        const a = nodes.get(e.from);
        const b = nodes.get(e.to);
        if (!a || !b) return null;
        const [x1, y1] = P([a.x, a.y]);
        const [x2, y2] = P([b.x, b.y]);
        return <line key={`${e.from}-${e.to}`} className="anim-fade" x1={x1} y1={y1} x2={x2} y2={y2} style={{ stroke: 'var(--kes)', strokeWidth: 1 + e.n * 0.45, opacity: 0.25 + e.n / 30, strokeLinecap: 'round' }} />;
      })}
      {network.nodes.map((n, i) => {
        const [x, y] = P([n.x, n.y]);
        const r = 9 + n.touches / 6;
        return (
          <g key={n.id} className="anim-pop" style={{ animationDelay: `calc(var(--stagger) * ${i})` }}>
            <circle cx={x} cy={y} r={r} style={{ fill: 'var(--kes)', stroke: 'var(--halo)', strokeWidth: 3 }} />
            <text x={x} y={y + 6} style={{ ...text, fontSize: 17, fill: 'var(--on-kes)' }}>
              {n.num}
            </text>
          </g>
        );
      })}
    </MiniPitch>
  );
}

export const passNetworkTable = () => ({
  columns: ['From', 'To', 'Passes'],
  rows: passNetwork().edges.map((e) => [`No. ${player(e.from).num}`, `No. ${player(e.to).num}`, e.n]),
});

/** The shot map's window: the last 34 m, goal at the top, the full width, in vertical pitch units. */
const SHOT_VIEW = { x: -30, y: -46, w: 740, h: 406 };
const shotR = (xg: number) => 10 + xg * 80;

type Box = { x: number; y: number; w: number; h: number };
const hits = (a: Box, b: Box) => a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;

/**
 * Places each minute label beside its ring where it covers no other label or ring: above first, then below, right,
 * left and the corners. Larger chances choose first, so the shots that matter most keep the clearest spot.
 */
function placeMinuteLabels(rings: readonly { x: number; y: number; r: number; text: string }[], size: number) {
  const placed: Box[] = [];
  const out = new Map<number, { x: number; y: number }>();
  const order = rings.map((_, i) => i).sort((i, j) => rings[j].r - rings[i].r);
  for (const i of order) {
    const { x, y, r, text } = rings[i];
    const w = text.length * size * 0.62 + 6;
    const h = size + 4;
    const gap = r + 5;
    const spots: [number, number][] = [
      [x, y - gap - h / 2],
      [x, y + gap + h / 2],
      [x + gap + w / 2, y],
      [x - gap - w / 2, y],
      [x + gap * 0.75 + w / 2, y - gap * 0.75 - h / 2],
      [x - gap * 0.75 - w / 2, y - gap * 0.75 - h / 2],
      [x + gap * 0.75 + w / 2, y + gap * 0.75 + h / 2],
      [x - gap * 0.75 - w / 2, y + gap * 0.75 + h / 2],
    ];
    const boxOf = ([cx, cy]: [number, number]): Box => ({ x: cx - w / 2, y: cy - h / 2, w, h });
    const inView = (b: Box) => b.x >= SHOT_VIEW.x && b.x + b.w <= SHOT_VIEW.x + SHOT_VIEW.w && b.y >= SHOT_VIEW.y && b.y + b.h <= SHOT_VIEW.y + SHOT_VIEW.h;
    const clear = (b: Box) =>
      inView(b) &&
      !placed.some((p) => hits(p, b)) &&
      !rings.some((o, j) => j !== i && hits(b, { x: o.x - o.r, y: o.y - o.r, w: o.r * 2, h: o.r * 2 }));
    const spot = spots.find((s) => clear(boxOf(s))) ?? spots.find((s) => !placed.some((p) => hits(p, boxOf(s)))) ?? spots[0];
    placed.push(boxOf(spot));
    out.set(i, { x: spot[0], y: spot[1] });
  }
  return out;
}

/**
 * Shots sized by xG on the last third, goal at the top: both teams are shown attacking the same goal, Kestrel Bay as
 * solid blue rings and Ashmoor as dashed orange ones, and a filled ring is a goal. Spoiler-safe recaps hide outcomes,
 * so every ring is drawn open. Bigger chances are drawn first, so a small ring is never hidden under a big one.
 */
export function ShotMap({ shots = servedShots(), hideOutcomes = false }: { shots?: readonly Shot[]; hideOutcomes?: boolean }) {
  const label = hideOutcomes
    ? `Shot map: ${shots.length} shots sized by expected goals, Kestrel Bay in blue and Ashmoor in orange, both attacking the goal at the top. Outcomes are hidden.`
    : `Shot map: ${shots.length} shots sized by expected goals, Kestrel Bay in blue and Ashmoor in orange, both attacking the goal at the top; a filled circle is a goal.`;
  const size = 24;
  const rings = [...shots]
    .sort((a, b) => b.xg - a.xg)
    .map((s) => {
      const [x, y] = project('v', s.x, s.y);
      return { s, x, y, r: shotR(s.xg), text: `${s.minute}′` };
    });
  const labels = placeMinuteLabels(rings, size);
  return (
    <div className="stack" style={{ gap: 8 }}>
      <svg viewBox={`${SHOT_VIEW.x} ${SHOT_VIEW.y} ${SHOT_VIEW.w} ${SHOT_VIEW.h}`} role="img" aria-label={label} style={{ width: '100%', height: 'auto', display: 'block', borderRadius: 8, direction: 'ltr' }}>
        <PitchMarkings orientation="v" />
        {rings.map(({ s, x, y, r }, i) => {
          const goal = s.outcome === 'goal' && !hideOutcomes;
          return (
            <circle
              key={`${s.minute}-${s.team}`}
              className="anim-pop"
              cx={x}
              cy={y}
              r={r}
              style={{
                fill: `var(--${s.team})`,
                fillOpacity: goal ? 0.9 : 0.14,
                stroke: `var(--${s.team})`,
                strokeWidth: 4,
                strokeDasharray: s.team === 'ash' ? '9 6' : undefined,
                transformBox: 'fill-box',
                transformOrigin: 'center',
                animationDelay: `calc(var(--stagger) * ${i})`,
              }}
            />
          );
        })}
        {rings.map(({ s, text: minute }, i) => {
          const at = labels.get(i);
          if (!at) return null;
          return (
            <text key={`${s.minute}-${s.team}`} className="anim-fade" x={at.x} y={at.y + size * 0.36} style={{ ...text, fontSize: size, fill: 'var(--text)', paintOrder: 'stroke', stroke: 'var(--halo)', strokeWidth: 6, animationDelay: `calc(var(--stagger) * ${i + 2})` }}>
              {minute}
            </text>
          );
        })}
      </svg>
      <div className="legend" aria-hidden="true">
        <span>
          <svg width="14" height="14" viewBox="0 0 14 14" style={{ verticalAlign: -2, marginInlineEnd: 6 }}>
            <circle cx="7" cy="7" r="5.5" style={{ fill: 'none', stroke: 'var(--kes)', strokeWidth: 2 }} />
          </svg>
          Kestrel Bay
        </span>
        <span>
          <svg width="14" height="14" viewBox="0 0 14 14" style={{ verticalAlign: -2, marginInlineEnd: 6 }}>
            <circle cx="7" cy="7" r="5.5" style={{ fill: 'none', stroke: 'var(--ash)', strokeWidth: 2, strokeDasharray: '3 2' }} />
          </svg>
          Ashmoor
        </span>
        {!hideOutcomes && (
          <span>
            <svg width="14" height="14" viewBox="0 0 14 14" style={{ verticalAlign: -2, marginInlineEnd: 6 }}>
              <circle cx="7" cy="7" r="5.5" style={{ fill: 'var(--muted)', stroke: 'var(--muted)', strokeWidth: 2 }} />
            </svg>
            Goal
          </span>
        )}
        <span>Bigger ring, bigger chance (xG)</span>
      </div>
    </div>
  );
}

export const shotTable = (shots: readonly Shot[] = servedShots(), hideOutcomes = false) => ({
  columns: ['Minute', 'Team', 'Player', 'xG', 'Outcome'],
  rows: shots.map((s) => [s.minute, s.team === 'kes' ? 'Kestrel Bay' : 'Ashmoor', `No. ${player(s.playerId).num}`, s.xg.toFixed(2), hideOutcomes ? 'hidden' : s.outcome]),
});

/** Where a player spent the match: a sequential single-hue map, never a rainbow (PRD 16.3). */
export function HeatMap({ id }: { id: string }) {
  const cols = 21;
  const rows = 14;
  const cells = occupancy(id, cols, rows);
  const max = Math.max(...cells);
  return (
    <MiniPitch label={`Heat map for No. ${player(id).num}: brighter cells are where he spent more time. The values are in the table view.`}>
      {cells.map((v, i) => {
        const r = Math.floor(i / cols);
        const c = i % cols;
        return <rect key={i} x={(c * 1050) / cols} y={(r * 680) / rows} width={1050 / cols + 0.5} height={680 / rows + 0.5} style={{ fill: 'rgb(var(--space-rgb))', opacity: Number(((v / max) * 0.75).toFixed(3)) }} />;
      })}
    </MiniPitch>
  );
}

export const heatTable = (id: string) => {
  const cells = occupancy(id, 21, 14);
  const zones = ['Defensive third', 'Middle third', 'Attacking third'];
  const sums = [0, 0, 0];
  cells.forEach((v, i) => {
    sums[Math.min(2, Math.floor(((i % 21) / 21) * 3))] += v;
  });
  const total = sums.reduce((a, b) => a + b, 0);
  return { columns: ['Zone', 'Share of time'], rows: zones.map((z, i) => [z, `${Math.round((sums[i] / total) * 100)}%`]) };
};

const RUN_STYLE: Record<RunLine['type'], { color: string; dash?: string }> = {
  Decoy: { color: 'var(--space)', dash: '10 7' },
  'In behind': { color: 'var(--kes)' },
  Overlap: { color: 'var(--ash)', dash: '3 6' },
  'Check to ball': { color: 'var(--muted)', dash: '1 6' },
};

/** A player's runs by type: colour and line style both encode the type (PRD 16.4 run map, VIS-5). */
export function RunMap({ id }: { id: string }) {
  const runs = runMap(id);
  return (
    <div className="stack" style={{ gap: 8 }}>
      <MiniPitch label={`Run map for No. ${player(id).num}: ${runs.length} off-ball runs, styled by type. The list is in the table view.`}>
        {runs.map((r, i) => {
          const a = P(r.from);
          const b = P(r.to);
          const s = RUN_STYLE[r.type];
          return (
            <g key={i} className="anim-fade" style={{ animationDelay: `calc(var(--stagger) * ${i * 2})` }}>
              <line x1={a[0]} y1={a[1]} x2={b[0]} y2={b[1]} style={{ stroke: s.color, strokeWidth: 6, strokeDasharray: s.dash, strokeLinecap: 'round' }} />
              <polygon points={arrowHead(a, b, 22)} style={{ fill: s.color }} />
            </g>
          );
        })}
      </MiniPitch>
      <div className="legend" aria-hidden="true">
        {Object.entries(RUN_STYLE).map(([type, s]) => (
          <span key={type}>
            <svg width="26" height="10" style={{ verticalAlign: -1, marginInlineEnd: 6 }}>
              <line x1="1" y1="5" x2="25" y2="5" style={{ stroke: s.color, strokeWidth: 3, strokeDasharray: s.dash ? s.dash.split(' ').map((v) => Number(v) / 2).join(' ') : undefined }} />
            </svg>
            {type}
          </span>
        ))}
      </div>
    </div>
  );
}

export const runTable = (id: string) => ({
  columns: ['Minute', 'Type', 'Length (m)'],
  rows: runMap(id).map((r) => [r.minute, r.type, Math.round(Math.hypot(r.to[0] - r.from[0], r.to[1] - r.from[1]))]),
});
