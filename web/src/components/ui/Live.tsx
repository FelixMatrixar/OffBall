import { cx } from '../../lib/cx';

/** Live indicators are the only motion that loops (PRD 16.10); with reduced motion they hold a steady dot. */
export function LiveBadge({ label = 'LIVE' }: { label?: string }) {
  return (
    <span className="live-badge">
      <span className="live-badge-dot anim-blink" />
      {label}
    </span>
  );
}

export function PulseDot({ color = 'var(--space)', size = 10 }: { color?: string; size?: number }) {
  return (
    <span className="pulse-dot" style={{ width: size, height: size }} aria-hidden="true">
      <span style={{ background: color }} />
      <span className="anim-ripple" style={{ border: `2px solid ${color}` }} />
    </span>
  );
}

const offset = (i: number) => ({ animationDelay: `calc(var(--stagger) * ${i * 4})` });

export function Equalizer({ active, bars = 4, height = 14 }: { active: boolean; bars?: number; height?: number }) {
  return (
    <span className={cx('eq', !active && 'eq-paused')} style={{ height }} aria-hidden="true">
      {Array.from({ length: bars }, (_, i) => (
        <span key={i} style={offset(i)} />
      ))}
    </span>
  );
}

export function Spinner({ color }: { color?: string }) {
  return <span className="spinner" aria-hidden="true" style={color ? { borderTopColor: color } : undefined} />;
}

export function TypingDots({ label }: { label: string }) {
  return (
    <span className="typing" role="status" aria-label={label}>
      <span />
      <span style={offset(1)} />
      <span style={offset(2)} />
    </span>
  );
}
