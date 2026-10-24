import { useEffect, useId, useRef, type ReactNode, type RefObject } from 'react';
import { createPortal } from 'react-dom';
import { cx } from '../../lib/cx';
import { usePresence } from '../../lib/motion';

let inertCount = 0;

/**
 * Modal behaviour shared by the drawer and dialogs: everything behind becomes inert, so Tab and screen readers stay
 * inside; focus moves in on open and returns on close; Escape closes (WCAG 2.4.3, 2.1.2).
 */
export function useModal(active: boolean, onClose: () => void, initialFocus: RefObject<HTMLElement>) {
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;
  useEffect(() => {
    if (!active) return;
    const previous = document.activeElement as HTMLElement | null;
    const root = document.getElementById('root');
    inertCount++;
    if (root) root.inert = true;
    initialFocus.current?.focus();
    const dialog = initialFocus.current?.closest('[role="dialog"]') ?? null;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopPropagation();
        onCloseRef.current();
        return;
      }
      // Tab wraps within the dialog, so focus never leaves it for the browser's own controls.
      if (e.key !== 'Tab' || !dialog) return;
      const items = [...dialog.querySelectorAll<HTMLElement>('a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), summary, [tabindex]:not([tabindex="-1"])')].filter((el) => el.offsetParent !== null || el === document.activeElement);
      if (!items.length) return;
      const first = items[0];
      const last = items[items.length - 1];
      const current = document.activeElement as HTMLElement | null;
      if (!current || !dialog.contains(current)) {
        e.preventDefault();
        first.focus();
      } else if (e.shiftKey && current === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && current === last) {
        e.preventDefault();
        first.focus();
      }
    };
    document.addEventListener('keydown', onKey, true);
    return () => {
      document.removeEventListener('keydown', onKey, true);
      inertCount--;
      if (root && inertCount === 0) root.inert = false;
      previous?.focus();
    };
  }, [active, initialFocus]);
}

const CloseIcon = () => (
  <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true">
    <path d="M2 2 L12 12 M12 2 L2 12" style={{ stroke: 'currentColor', strokeWidth: 1.8, strokeLinecap: 'round' }} />
  </svg>
);

interface DrawerProps {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
}

/**
 * A modal side drawer that slides in over a fading backdrop and slides out on close. It opens from the right, or the
 * left in right-to-left languages, and closes from its button, the backdrop or Escape.
 */
export function Drawer({ open, onClose, title, children }: DrawerProps) {
  const { mounted, closing } = usePresence(open, '--dur-smooth');
  const closeRef = useRef<HTMLButtonElement>(null);
  const titleId = useId();
  useModal(mounted && !closing, onClose, closeRef);
  if (!mounted) return null;
  return createPortal(
    <>
      <button type="button" className={cx('drawer-scrim', closing && 'drawer-closing')} aria-label={`Close ${title.toLowerCase()}`} tabIndex={-1} onClick={onClose} />
      <div role="dialog" aria-modal="true" aria-labelledby={titleId} className={cx('drawer', closing && 'drawer-closing')}>
        <div className="drawer-head">
          <h2 id={titleId} className="drawer-title">
            {title}
          </h2>
          <button ref={closeRef} type="button" aria-label="Close" onClick={onClose} className="btn btn-ghost btn-icon btn-round press">
            <CloseIcon />
          </button>
        </div>
        {children}
      </div>
    </>,
    document.body,
  );
}

/** A centred modal dialog: keyboard shortcuts, pairing, recap previews. */
export function Dialog({ open, onClose, title, children, wide = false }: DrawerProps & { wide?: boolean }) {
  const { mounted, closing } = usePresence(open, '--dur-quick');
  const closeRef = useRef<HTMLButtonElement>(null);
  const titleId = useId();
  useModal(mounted && !closing, onClose, closeRef);
  if (!mounted) return null;
  return createPortal(
    <>
      <button type="button" className={cx('drawer-scrim', closing && 'drawer-closing')} aria-label={`Close ${title.toLowerCase()}`} tabIndex={-1} onClick={onClose} />
      <div role="dialog" aria-modal="true" aria-labelledby={titleId} className={cx('dialog', wide && 'dialog-wide', closing && 'dialog-closing')}>
        <div className="drawer-head">
          <h2 id={titleId} className="drawer-title">
            {title}
          </h2>
          <button ref={closeRef} type="button" aria-label="Close" onClick={onClose} className="btn btn-ghost btn-icon btn-round press">
            <CloseIcon />
          </button>
        </div>
        {children}
      </div>
    </>,
    document.body,
  );
}
