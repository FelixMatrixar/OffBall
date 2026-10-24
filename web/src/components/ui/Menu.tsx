import { useEffect, useId, useRef, useState, type KeyboardEvent, type ReactNode } from 'react';
import { cx } from '../../lib/cx';
import { CheckIcon } from './Chip';

export interface MenuItem {
  key: string;
  label: ReactNode;
  /** A link, or an action. */
  href?: string;
  onSelect?: () => void;
  /** An on/off item (menuitemcheckbox): choosing it toggles it and leaves the menu open. */
  checked?: boolean;
  /** A rule above the item, to set it apart from the ones before. */
  divided?: boolean;
}

interface MenuButtonProps {
  label: string;
  items: readonly MenuItem[];
  icon?: ReactNode;
  className?: string;
  /** The button's classes; a secondary button by default. */
  buttonClassName?: string;
  /** After the label, inside the button: a count, say. */
  extra?: ReactNode;
  /** A line of explanation at the top of the list. */
  note?: ReactNode;
  /** Which edge of the button the list lines up with. */
  align?: 'start' | 'end';
}

/**
 * A menu button (the WAI-ARIA menu button pattern): a short list of actions under a button. Opening it focuses the
 * first item; arrow keys, Home and End move between items; Escape closes it and returns focus to the button; Tab or a
 * click outside closes it. On/off items toggle in place and keep it open. It pops in from its corner (PRD 16.10).
 */
export function MenuButton({ label, items, icon, className, buttonClassName = 'btn btn-secondary press', extra, note, align = 'end' }: MenuButtonProps) {
  const [open, setOpen] = useState(false);
  const id = useId();
  const button = useRef<HTMLButtonElement>(null);
  const list = useRef<HTMLUListElement>(null);
  const entries = () => [...(list.current?.querySelectorAll<HTMLElement>('[role="menuitem"], [role="menuitemcheckbox"]') ?? [])];
  const focusAt = (i: number) => {
    const all = entries();
    if (all.length) all[(i + all.length) % all.length].focus();
  };

  useEffect(() => {
    if (!open) return;
    focusAt(0);
    const away = (e: PointerEvent) => {
      const target = e.target as Node;
      if (!list.current?.contains(target) && !button.current?.contains(target)) setOpen(false);
    };
    document.addEventListener('pointerdown', away);
    return () => document.removeEventListener('pointerdown', away);
  }, [open]);

  const close = (refocus: boolean) => {
    setOpen(false);
    if (refocus) button.current?.focus();
  };
  const onListKey = (e: KeyboardEvent<HTMLUListElement>) => {
    const i = entries().indexOf(document.activeElement as HTMLElement);
    const moves: Record<string, () => void> = {
      ArrowDown: () => focusAt(i + 1),
      ArrowUp: () => focusAt(i - 1),
      Home: () => focusAt(0),
      End: () => focusAt(entries().length - 1),
      Escape: () => close(true),
    };
    if (e.key === 'Tab') {
      setOpen(false);
      return;
    }
    const move = moves[e.key];
    if (!move) return;
    // The match view's own shortcuts (Escape among them) don't see keys the menu used.
    e.preventDefault();
    e.stopPropagation();
    move();
  };

  return (
    <div className={cx('menu', className)}>
      <button
        ref={button}
        type="button"
        className={buttonClassName}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? id : undefined}
        onClick={() => setOpen((o) => !o)}
        onKeyDown={(e) => {
          if (e.key === 'ArrowDown' && !open) {
            e.preventDefault();
            setOpen(true);
          }
        }}
      >
        {icon}
        {label}
        {extra}
        <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true" className={cx('menu-caret', open && 'menu-caret-open')}>
          <path d="M2.5 4.5 L6 8 L9.5 4.5" style={{ fill: 'none', stroke: 'currentColor', strokeWidth: 1.6, strokeLinecap: 'round', strokeLinejoin: 'round' }} />
        </svg>
      </button>
      {open && (
        <ul ref={list} id={id} role="menu" aria-label={label} className={cx('menu-list anim-pop', align === 'start' && 'menu-list-start')} onKeyDown={onListKey}>
          {note && (
            <li role="presentation" className="menu-note">
              {note}
            </li>
          )}
          {items.map((item) => (
            <li key={item.key} role="none" className={item.divided ? 'menu-divided' : undefined}>
              {item.href ? (
                <a role="menuitem" href={item.href} tabIndex={-1} className="menu-item" onClick={() => close(false)}>
                  {item.label}
                </a>
              ) : item.checked !== undefined ? (
                <button role="menuitemcheckbox" type="button" tabIndex={-1} aria-checked={item.checked} className="menu-item menu-check" onClick={() => item.onSelect?.()}>
                  <span className="menu-box" aria-hidden="true">
                    {item.checked && <CheckIcon size={11} />}
                  </span>
                  {item.label}
                </button>
              ) : (
                <button
                  role="menuitem"
                  type="button"
                  tabIndex={-1}
                  className="menu-item"
                  onClick={() => {
                    close(false);
                    item.onSelect?.();
                  }}
                >
                  {item.label}
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
