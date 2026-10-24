import { useMemo } from 'react';
import { player, playerLabel, type XY } from '../../lib/match';
import type { RecapMoment } from '../../lib/recap';
import { Ball, GapRing, PassLine, PitchContext, PitchMarkings, PlayerDot, RunArrow, project } from '../pitch';

/** The part of the pitch a moment happened in, framed 16:10 around its players, in pitch units. */
function frameOf(m: RecapMoment): string {
  const pts: XY[] = [...m.diagram.players.map((p) => p.at), m.diagram.ring, m.diagram.run.from, m.diagram.ball];
  let x0 = Math.min(...pts.map((p) => p[0])) - 9;
  let x1 = Math.max(...pts.map((p) => p[0])) + 9;
  let y0 = Math.min(...pts.map((p) => p[1])) - 9;
  let y1 = Math.max(...pts.map((p) => p[1])) + 9;
  // Widen the narrow side to 16:10 (x across, y up the page), then keep inside the pitch and its margin.
  if ((x1 - x0) / (y1 - y0) < 1.6) {
    const grow = ((y1 - y0) * 1.6 - (x1 - x0)) / 2;
    x0 -= grow;
    x1 += grow;
  } else {
    const grow = ((x1 - x0) / 1.6 - (y1 - y0)) / 2;
    y0 -= grow;
    y1 += grow;
  }
  const shiftX = Math.max(0, -3 - x0) - Math.max(0, x1 - 108);
  const shiftY = Math.max(0, -3 - y0) - Math.max(0, y1 - 71);
  x0 += shiftX;
  x1 += shiftX;
  y0 += shiftY;
  y1 += shiftY;
  return `${(x0 * 10).toFixed(0)} ${((68 - y1) * 10).toFixed(0)} ${((x1 - x0) * 10).toFixed(0)} ${((y1 - y0) * 10).toFixed(0)}`;
}

/**
 * A moment drawn in the overlay grammar: the run that made the space, the space, and the pass into it. `title` is the
 * moment's title as this viewer reads it (spoiler-safe or not); a thumbnail beside its own title can be decorative.
 */
export function MomentDiagram({ m, title, className = 'recap-diagram', decorative = false }: { m: RecapMoment; title: string; className?: string; decorative?: boolean }) {
  const geometry = useMemo(() => ({ o: 'h' as const, P: ([x, y]: XY) => project('h', x, y) }), []);
  const runner = player(m.diagram.run.id);
  const label = `${m.minute}′: ${title}. Diagram of the run that made the space and where it opened.`;
  return (
    <PitchContext.Provider value={geometry}>
      <svg className={className} viewBox={frameOf(m)} role={decorative ? undefined : 'img'} aria-label={decorative ? undefined : label} aria-hidden={decorative || undefined}>
        <PitchMarkings orientation="h" />
        <GapRing at={m.diagram.ring} />
        <RunArrow from={m.diagram.run.from} runner={m.diagram.run.to} ahead={m.diagram.run.to} color={`var(--${runner.team})`} />
        {m.diagram.pass && <PassLine from={m.diagram.pass.from} ball={m.diagram.pass.to} to={m.diagram.pass.to} arrived />}
        {m.diagram.players.map((p) => (
          <PlayerDot key={p.id} at={p.at} team={player(p.id).team} num={player(p.id).num} label={playerLabel(p.id)} />
        ))}
        <Ball at={m.diagram.ball} />
      </svg>
    </PitchContext.Provider>
  );
}
