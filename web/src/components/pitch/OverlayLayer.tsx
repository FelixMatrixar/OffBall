// Draws feed overlays (PRD 15.2) for one viewer: the pitch layer under the players, and labels above them.
import { useRef } from 'react';
import { fill } from '../../lib/i18n';
import { LABELS } from '../../lib/i18n/labels';
import type { ActiveOverlay } from '../../lib/feed';
import { PASS_FROM, at as along, player, type Key, type XY } from '../../lib/match';
import type { Density, Lang } from '../../lib/prefs';
import { usePitch } from './geometry';
import { layoutLabels, type LabelIn } from './labels';
import { BackLine, Displacement, GapRing, Ghost, PassLine, RunArrow, ShutRing, StatPin, Tag } from './overlays';

export interface LiveValues {
  /** Gap-zone control change since the build-up, in points. */
  gapPts: number;
  /** Metres Ashmoor's No. 5 has been pulled from his starting spot. */
  displacement: number;
  /** Metres from Ashmoor's back line to their goal. */
  depth: number;
  speedOf: (id: string) => number;
  /** Where a player will be `lead` seconds from now (for run arrows drawn ahead of the runner). */
  ahead: (id: string, lead: number) => XY;
  num: (n: number, digits?: number) => string;
}

interface LayerProps {
  items: readonly ActiveOverlay[];
  pos: Record<string, XY>;
  ball: XY;
  t: number;
  lang: Lang;
  live: LiveValues;
  density: Density;
}

const signed = (n: number, num: LiveValues['num']) => `${n >= 0 ? '+' : '−'}${num(Math.abs(n))}`;
const text = (o: ActiveOverlay['overlay'], lang: Lang) => o.text[lang] ?? o.text.en ?? '';

/** The pitch layer: rings, runs, passes, ghosts and the defensive line, drawn under the players. */
export function PitchOverlays({ items, pos, ball, t, lang, live, density }: LayerProps) {
  return (
    <>
      {items.map(({ overlay: o, retraction }) => {
        const retracted = !!retraction;
        const d = (o.data ?? {}) as Record<string, unknown>;
        const key = `${o.overlay_id}:${o.rev}`;
        switch (o.kind) {
          case 'offside_line':
            if (density === 'minimal') return null;
            return <BackLine key={key} x={105 - live.depth} label={fill(text(o, lang), { m: live.num(live.depth, 1) })} />;
          case 'gap_ring': {
            const c = o.anchors.centre_xy;
            if (!c) return null;
            const rx = Number(d.rx_m ?? 5.4);
            const ry = Number(d.ry_m ?? 6.8);
            if (d.shut) return <ShutRing key={key} at={c} rx={rx} ry={ry} label={text(o, lang)} />;
            const label = d.live === 'gap_zone' ? fill(text(o, lang), { pts: signed(live.gapPts, live.num) }) : text(o, lang);
            const passing = d.with_pass === true && t >= 4.2 && t < 6.4;
            return <GapRing key={key} at={c} rx={rx} ry={ry} label={label} passFrom={passing ? PASS_FROM : undefined} ball={passing ? ball : undefined} retracted={retracted} />;
          }
          case 'run_arrow': {
            const id = o.anchors.player_id;
            if (!id || !pos[id]) return null;
            if (d.style === 'displacement') {
              const from = o.anchors.from_xy ?? pos[id];
              return <Displacement key={key} from={from} to={pos[id]} label={`${live.num(live.displacement, 1)} m`} />;
            }
            const from = o.anchors.from_xy ?? pos[id];
            const lead = Number(d.lead_s ?? 0.8);
            return <RunArrow key={key} from={from} runner={pos[id]} ahead={live.ahead(id, lead)} color={`var(--${player(id).team})`} />;
          }
          case 'pass_line': {
            const from = o.anchors.from_xy;
            const to = o.anchors.to_xy;
            if (!from || !to) return null;
            const arrived = Math.hypot(ball[0] - to[0], ball[1] - to[1]) < 1.2 || t >= 5.6;
            return <PassLine key={key} from={from} ball={arrived ? to : ball} to={to} difficulty={Number(d.difficulty ?? 6)} arrived={arrived} retracted={retracted} />;
          }
          case 'ghost': {
            const id = o.anchors.player_id;
            const track = d.track as Key[] | undefined;
            if (!id || !track) return null;
            return <Ghost key={key} at={along(track, t)} team={player(id).team} label={text(o, lang)} />;
          }
          default:
            return null;
        }
      })}
    </>
  );
}

/** Labels above the players: tags, sprint badges, stat pins and Correction tags, laid out to avoid collisions. */
export function LabelOverlays({ items, pos, lang, live, density }: Omit<LayerProps, 'ball' | 't'>) {
  const { P } = usePitch();
  const memory = useRef(new Map<string, number>());
  const labels: (LabelIn & { color: string })[] = [];
  const pins: JSX.Element[] = [];
  for (const { overlay: o, retraction } of items) {
    const id = o.anchors.player_id ?? undefined;
    if (retraction && o.layer !== 'dom') {
      const anchor = o.anchors.centre_xy ?? o.anchors.to_xy ?? (id ? pos[id] : undefined);
      if (anchor) labels.push({ key: `${o.overlay_id}:corr`, anchor: P(anchor), text: LABELS[lang].correction, color: 'var(--danger-text)', dy: 44 });
      continue;
    }
    if (density === 'minimal') continue;
    if (o.kind === 'player_tag' && id && pos[id]) labels.push({ key: o.overlay_id, anchor: P(pos[id]), text: text(o, lang), color: 'var(--text)' });
    if (o.kind === 'badge' && id && pos[id]) {
      const speed = live.speedOf(id);
      if (speed > 25.2) labels.push({ key: o.overlay_id, anchor: P(pos[id]), text: fill(text(o, lang), { speed: live.num(speed, 1) }), color: 'var(--space-ink)', dy: 40 });
    }
    if (o.kind === 'stat_card' && id && pos[id]) {
      const d = (o.data ?? {}) as Record<string, unknown>;
      pins.push(<StatPin key={o.overlay_id} at={pos[id]} title={text(o, lang)} value={`${live.num(Number(d.value ?? 0), 1)} ${String(d.unit ?? '')}`} />);
    }
  }
  const dots = Object.values(pos).map((p) => P(p));
  const placed = layoutLabels(labels, dots, memory.current);
  return (
    <>
      {pins}
      {placed.map((l, i) => (
        <Tag key={l.key} x={l.x} y={l.y} text={l.text} color={labels[i].color} />
      ))}
    </>
  );
}
