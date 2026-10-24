import { BIG_CHANCES, momentum } from '../../lib/stats';

function areaPath(minute: number, sign: 1 | -1): string {
  let d = 'M0 44';
  for (let m = 0; m <= minute; m++) {
    const v = momentum(m);
    const part = sign === 1 ? Math.max(0, v) : Math.min(0, v);
    d += ` L${m * 10} ${(44 - part * 38).toFixed(1)}`;
  }
  return `${d} L${minute * 10} 44 Z`;
}

/**
 * Space-value flow per team, minute by minute: Kestrel Bay above the line, Ashmoor below (PRD 16.4). The ribbon
 * stays left to right in every language, like the match clock it follows.
 */
export function MomentumRibbon({ minute, label }: { minute: number; label: string }) {
  const now = minute * 10;
  const chances = BIG_CHANCES.filter((e) => e.minute <= minute);
  return (
    <div className="chart-live">
      <svg
        viewBox="0 0 900 96"
        role="img"
        aria-label={label}
        style={{
          width: '100%',
          height: 'auto',
          display: 'block',
          direction: 'ltr',
        }}
      >
        <line x1={0} y1={44} x2={900} y2={44} style={{ stroke: 'var(--line)', strokeWidth: 1.5 }} />
        <g className="anim-wipe" style={{ animationDelay: 'var(--dur-smooth)' }}>
          <path d={areaPath(minute, 1)} style={{ fill: 'var(--kes)', opacity: 0.85 }} />
          <path d={areaPath(minute, -1)} style={{ fill: 'var(--ash)', opacity: 0.85 }} />
        </g>
        <line
          x1={450}
          y1={4}
          x2={450}
          y2={84}
          style={{
            stroke: 'var(--muted)',
            strokeWidth: 1,
            strokeDasharray: '4 4',
          }}
        />
        <text
          x={454}
          y={14}
          style={{
            fontFamily: 'var(--font-body)',
            fontSize: 11,
            fill: 'var(--muted)',
          }}
        >
          HT
        </text>
        {chances.map((e, i) => (
          <circle
            key={`${e.minute}-${e.team}`}
            className="anim-pop"
            cx={e.minute * 10}
            cy={e.team === 'kes' ? 6 : 82}
            r={5}
            style={{
              fill: `var(--${e.team})`,
              stroke: 'var(--surface)',
              strokeWidth: 2,
              animationDelay: `calc(var(--dur-draw) + var(--stagger) * ${i * 3})`,
            }}
          />
        ))}
        <line x1={now} y1={2} x2={now} y2={86} style={{ stroke: 'var(--space)', strokeWidth: 2 }} />
        <circle cx={now} cy={44} r={4} style={{ fill: 'var(--space)' }} />
        <text
          x={now}
          y={95}
          style={{
            fontFamily: 'var(--font-body)',
            fontSize: 11,
            fontWeight: 700,
            fill: 'var(--text)',
            textAnchor: 'middle',
          }}
        >
          {minute}'
        </text>
        <text
          x={0}
          y={95}
          style={{
            fontFamily: 'var(--font-body)',
            fontSize: 11,
            fill: 'var(--muted)',
          }}
        >
          0'
        </text>
        <text
          x={900}
          y={95}
          style={{
            fontFamily: 'var(--font-body)',
            fontSize: 11,
            fill: 'var(--muted)',
            textAnchor: 'end',
          }}
        >
          90'
        </text>
      </svg>
      {/* The live ripple is HTML over the chart, so it animates on the compositor rather than repainting the SVG. */}
      <span
        className="chart-ripple anim-ripple"
        style={{
          left: `${(now / 900) * 100}%`,
          top: `${(44 / 96) * 100}%`,
          width: `${(10 / 900) * 100}%`,
        }}
      />
    </div>
  );
}
