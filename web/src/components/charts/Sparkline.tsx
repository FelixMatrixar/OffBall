interface SparklineProps {
  values: readonly number[];
  /** The value at the top of the chart. */
  max: number;
  /** How many samples fill the full width; fewer samples draw a partial line. */
  span: number;
  threshold?: number;
  thresholdLabel?: string;
  label: string;
  color?: string;
  /** Show the live end point (a live indicator, so it pulses). */
  live?: boolean;
}

/** A small line chart (physical sparklines, PRD 16.4). Stays left to right: time runs that way. */
export function Sparkline({ values, max, span, threshold, thresholdLabel, label, color = 'var(--kes)', live = true }: SparklineProps) {
  const W = 200;
  const H = 52;
  const x = (i: number) => (i / Math.max(1, span - 1)) * W;
  const y = (v: number) => H - 4 - (Math.min(max, v) / max) * (H - 8);
  const points = values.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(' ');
  const last = values.length ? [x(values.length - 1), y(values[values.length - 1])] : null;

  return (
    <div className="chart-live">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        role="img"
        aria-label={label}
        style={{
          width: '100%',
          height: 'auto',
          display: 'block',
          direction: 'ltr',
        }}
      >
        {threshold !== undefined && (
          <>
            <line
              x1={0}
              y1={y(threshold)}
              x2={W}
              y2={y(threshold)}
              style={{
                stroke: 'var(--space)',
                strokeWidth: 1,
                strokeDasharray: '3 3',
              }}
            />
            {thresholdLabel && (
              <text
                x={W}
                y={y(threshold) - 4}
                style={{
                  fontFamily: 'var(--font-body)',
                  fontSize: 8,
                  fill: 'var(--muted)',
                  textAnchor: 'end',
                }}
              >
                {thresholdLabel}
              </text>
            )}
          </>
        )}
        <polyline
          points={points}
          style={{
            fill: 'none',
            stroke: color,
            strokeWidth: 2.5,
            strokeLinejoin: 'round',
          }}
        />
        {last && <circle cx={last[0]} cy={last[1]} r={3.5} style={{ fill: color }} />}
      </svg>
      {last && live && (
        <span
          className="chart-ripple anim-ripple"
          style={{
            left: `${(last[0] / W) * 100}%`,
            top: `${(last[1] / H) * 100}%`,
            width: `${(7 / W) * 100}%`,
            borderColor: color,
            borderWidth: 1.5,
          }}
        />
      )}
    </div>
  );
}
