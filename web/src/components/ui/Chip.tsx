import type { HTMLAttributes } from 'react';
import { cx } from '../../lib/cx';

type Tone = 'space' | 'solid' | 'outline' | 'muted' | 'accent' | 'danger' | 'alert';

export function Chip({
  tone = 'outline',
  size = 'sm',
  className,
  ...rest
}: HTMLAttributes<HTMLSpanElement> & { tone?: Tone; size?: 'sm' | 'lg' }) {
  return <span className={cx('chip', `chip-${tone}`, size === 'lg' && 'chip-lg', className)} {...rest} />;
}

/** A check mark; with `draw`, the stroke draws itself in. */
export function CheckIcon({ draw = false, size = 12 }: { draw?: boolean; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 14 14" aria-hidden="true">
      <path
        className={draw ? 'check-draw' : undefined}
        d="M2.5 7.5 L5.5 10.5 L11.5 3.5"
        style={{ fill: 'none', stroke: 'currentColor', strokeWidth: 2.4, strokeLinecap: 'round', strokeLinejoin: 'round' }}
      />
    </svg>
  );
}

/** Pops in, then draws its check. */
export function VerifiedChip({ label = 'Verified' }: { label?: string }) {
  return (
    <Chip tone="space" className="anim-pop">
      <CheckIcon draw size={10} />
      {label}
    </Chip>
  );
}

export function PendingChip({ label = 'Pending' }: { label?: string }) {
  return (
    <Chip tone="muted">
      <span className="anim-blink" style={{ width: 6, height: 6, borderRadius: 3, background: 'var(--muted)' }} />
      {label}
    </Chip>
  );
}
