interface Bar {
  label: string;
  value: number;
  color: string;
}

/** Horizontal bars that grow in turn: compact answers on the phone. */
export function BarList({ bars, max, suffix = '' }: { bars: readonly Bar[]; max: number; suffix?: string }) {
  const rowH = 30;
  return (
    <svg viewBox={`0 0 300 ${bars.length * rowH}`} role="img" aria-label={bars.map((b) => `${b.label} ${b.value}${suffix}`).join(', ')} style={{ width: '100%', height: 'auto', display: 'block' }}>
      {bars.map((b, i) => {
        const w = Math.max(8, (b.value / max) * 180);
        const y = 4 + i * rowH;
        return (
          <g key={b.label}>
            <text x={0} y={y + 12} style={{ fontFamily: 'var(--font-body)', fontSize: 11, fill: 'var(--muted)' }}>
              {b.label}
            </text>
            <rect className="anim-grow" x={74} y={y} width={w} height={16} rx={3} style={{ fill: b.color, transformBox: 'fill-box', animationDelay: `calc(var(--dur-draw) + var(--stagger) * ${i * 4})` }} />
            <text className="anim-fade" x={80 + w} y={y + 12} style={{ fontFamily: 'var(--font-body)', fontSize: 11, fontWeight: 700, fill: 'var(--text)', animationDelay: 'calc(var(--dur-draw) * 2)' }}>
              {b.value}
              {suffix}
            </text>
          </g>
        );
      })}
    </svg>
  );
}
