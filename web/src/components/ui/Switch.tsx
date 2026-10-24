import type { ReactNode } from 'react';
import { cx } from '../../lib/cx';

interface SwitchProps {
  checked: boolean;
  onChange: (checked: boolean) => void;
  label: ReactNode;
  hint?: string;
  /** Full-width row with the label on the left, as in the Personalize drawer. */
  block?: boolean;
}

const Track = () => (
  <span className="switch-track" aria-hidden="true">
    <span className="switch-knob" />
  </span>
);

export function Switch({ checked, onChange, label, hint, block = false }: SwitchProps) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      onClick={() => onChange(!checked)}
      className={cx('switch', 'press', block && 'switch-block')}
    >
      {block ? (
        <>
          <span>
            {label}
            {hint && <span className="switch-hint">{hint}</span>}
          </span>
          <Track />
        </>
      ) : (
        <>
          <Track />
          {label}
        </>
      )}
    </button>
  );
}
