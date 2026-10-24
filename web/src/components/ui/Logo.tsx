export function LogoMark({ size = 30 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 30 30" aria-hidden="true">
      <rect x="2" y="6" width="26" height="18" rx="3" style={{ fill: 'none', stroke: 'var(--text)', strokeWidth: 1.8 }} />
      <line x1="15" y1="6" x2="15" y2="24" style={{ stroke: 'var(--text)', strokeWidth: 1.8 }} />
      <circle cx="21" cy="13" r="3.4" style={{ fill: 'none', stroke: 'var(--space)', strokeWidth: 2 }} />
    </svg>
  );
}

export function Logo({ href = '#/', suffix, size = 28 }: { href?: string; suffix?: string; size?: number }) {
  return (
    <a className="logo" href={href}>
      <LogoMark size={size + 2} />
      <span className="logo-word" style={{ fontSize: size }}>
        OffBall{suffix ? ` ${suffix}` : ''}
      </span>
    </a>
  );
}
