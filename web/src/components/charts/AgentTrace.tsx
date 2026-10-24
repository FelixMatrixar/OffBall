export interface TraceRow {
  agent: string;
  start: number;
  end: number;
  kind?: 'ok' | 'rejected' | 'async' | 'fallback';
  /** Shown instead of the duration, for steps that run past the budget off the critical path. */
  note?: string;
}

/** Animation time per second of agent time: the bars play back the real timings, scaled (PRD 16.10). */
const MS_PER_SECOND = 420;

/**
 * One bar per agent step, growing in the order the steps ran, at true proportions. A rejected step shakes once.
 * Give it a new `key` to replay. `compact` fits it in a narrow card: the names and timings take less room.
 */
export function AgentTrace({ rows, budget = 3, compact = false }: { rows: readonly TraceRow[]; budget?: number; compact?: boolean }) {
  const columns = compact ? '84px minmax(0, 1fr) 46px' : 'minmax(110px, 150px) minmax(0, 1fr) 64px';
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }} dir="ltr">
      {rows.map((r) => {
        const end = Math.min(r.end, budget);
        const delay = Math.round(r.start * MS_PER_SECOND);
        const dur = Math.max(220, Math.round((end - r.start) * MS_PER_SECOND));
        const rejected = r.kind === 'rejected';
        const background =
          r.kind === 'async'
            ? 'repeating-linear-gradient(90deg, var(--muted) 0 8px, transparent 8px 12px)'
            : rejected
              ? 'var(--danger)'
              : r.kind === 'fallback'
                ? 'var(--ash)'
                : 'var(--kes)';
        return (
          <div key={`${r.agent}-${r.start}`} style={{ display: 'grid', gridTemplateColumns: columns, alignItems: 'center', gap: compact ? 8 : 10 }}>
            <span style={{ fontSize: compact ? 12 : 13, fontWeight: 600 }}>{r.agent}</span>
            <span style={{ position: 'relative', height: 22, borderRadius: 4, background: 'var(--surface-2)' }}>
              <span
                className="trace-bar"
                style={{
                  position: 'absolute',
                  top: 3,
                  bottom: 3,
                  borderRadius: 3,
                  left: `${(r.start / budget) * 100}%`,
                  width: `${((end - r.start) / budget) * 100}%`,
                  background,
                  transformOrigin: 'left center',
                  animation: rejected
                    ? `ob-grow ${dur}ms var(--ease-standard) ${delay}ms backwards, ob-shake var(--dur-fill) var(--ease-standard) ${delay + dur}ms`
                    : `ob-grow ${dur}ms var(--ease-standard) ${delay}ms backwards`,
                }}
              />
              <span aria-hidden="true" style={{ position: 'absolute', right: 0, top: -4, bottom: -4, width: 2, background: 'var(--danger)' }} />
            </span>
            <span className="mono anim-fade" style={{ fontSize: compact ? 11 : 12, color: rejected ? 'var(--danger-text)' : 'var(--muted)', textAlign: 'right', animationDelay: `${delay + dur}ms` }}>
              {r.note ?? `${Math.round((r.end - r.start) * 1000)} ms`}
            </span>
          </div>
        );
      })}
    </div>
  );
}
