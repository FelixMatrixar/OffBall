import { leaderName, type Leader } from '../../lib/content';
import { player } from '../../lib/match';

/** Space Created per player: a bar for the estimate and a whisker for its 90% interval (PRD 10.3). */
export function Leaderboard({ rows, max, unit = 'm²' }: { rows: readonly Leader[]; max: number; unit?: string }) {
  const pct = (v: number) => `${((v / max) * 100).toFixed(1)}%`;
  return (
    <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexDirection: 'column', gap: 12 }}>
      {rows.map((r, i) => (
        <li key={r.id}>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13, marginBottom: 4 }}>
            <span>{leaderName(r.id)}</span>
            <span className="tabular" style={{ fontWeight: 600 }}>
              {r.v} {unit}
            </span>
          </div>
          <div className="meter" aria-hidden="true">
            <div className="meter-fill anim-grow" style={{ width: pct(r.v), background: `var(--${player(r.id).team})`, animationDelay: `calc(var(--dur-base) + var(--stagger) * ${i * 2})` }} />
            <div className="whisker anim-fade" style={{ insetInlineStart: pct(r.lo), width: pct(r.hi - r.lo), animationDelay: `calc(var(--dur-draw) + var(--stagger) * ${i * 2})` }} />
          </div>
          <span className="sr-only">
            90% interval {r.lo} to {r.hi} {unit}
          </span>
        </li>
      ))}
    </ul>
  );
}
