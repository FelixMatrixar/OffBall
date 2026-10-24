import type { AnchorHTMLAttributes, ButtonHTMLAttributes } from 'react';
import { cx } from '../../lib/cx';

type Variant = 'primary' | 'secondary' | 'ghost' | 'danger' | 'solid';

interface Look {
  variant?: Variant;
  size?: 'md' | 'lg';
  icon?: boolean;
  round?: boolean;
}

const classes = ({ variant = 'secondary', size = 'md', icon = false, round = false }: Look, extra?: string) =>
  cx('btn', `btn-${variant}`, size === 'lg' && 'btn-lg', icon && 'btn-icon', round && 'btn-round', 'press', extra);

export function Button({
  variant,
  size,
  icon,
  round,
  className,
  type = 'button',
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & Look) {
  return <button type={type} className={classes({ variant, size, icon, round }, className)} {...rest} />;
}

export function LinkButton({
  variant,
  size,
  icon,
  round,
  className,
  ...rest
}: AnchorHTMLAttributes<HTMLAnchorElement> & Look) {
  return <a className={classes({ variant, size, icon, round }, className)} {...rest} />;
}
