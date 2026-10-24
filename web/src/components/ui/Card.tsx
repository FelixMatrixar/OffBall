import type { CSSProperties, HTMLAttributes, ReactNode } from 'react';
import { cx } from '../../lib/cx';

/** An entrance delay as a multiple of the stagger token (PRD 16.10: 40–60 ms between cards). */
export const stagger = (order?: number): CSSProperties | undefined => (order ? { animationDelay: `calc(var(--stagger) * ${order})` } : undefined);

interface CardProps extends HTMLAttributes<HTMLElement> {
  heading?: ReactNode;
  /** Position in a staggered column of cards. */
  order?: number;
}

export function Card({ heading, order, className, style, children, ...rest }: CardProps) {
  return (
    <section className={cx('card', 'anim-rise', className)} style={{ ...stagger(order), ...style }} {...rest}>
      {heading && <h2 className="card-title">{heading}</h2>}
      {children}
    </section>
  );
}

export function Tile({ label, children, order, highlight = false }: { label: ReactNode; children: ReactNode; order?: number; highlight?: boolean }) {
  return (
    <div className={cx('tile', 'anim-rise', highlight && 'tile-highlight')} style={stagger(order)}>
      <div className="tile-label">{label}</div>
      {children}
    </div>
  );
}
