import { useId, type KeyboardEvent, type ReactNode } from 'react';
import { cx } from '../../lib/cx';

/**
 * The phone layout's side panel (PRD 15.1): docked at the bottom, collapsed to its handle until the viewer expands
 * it. It isn't modal, so the match stays usable behind it; Escape collapses it.
 */
export function BottomSheet({ title, open, onToggle, children }: { title: string; open: boolean; onToggle: (open: boolean) => void; children: ReactNode }) {
  const bodyId = useId();
  const onKeyDown = (e: KeyboardEvent<HTMLElement>) => {
    if (e.key === 'Escape' && open) {
      e.stopPropagation();
      onToggle(false);
    }
  };
  return (
    <section className={cx('sheet', open && 'sheet-open')} aria-label={title} onKeyDown={onKeyDown}>
      <button type="button" className="sheet-handle press" aria-expanded={open} aria-controls={bodyId} onClick={() => onToggle(!open)}>
        <span className="sheet-grip" aria-hidden="true" />
        <span className="sheet-title">{title}</span>
        <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true" className="sheet-chevron">
          <path d="M3 9 L7 5 L11 9" style={{ fill: 'none', stroke: 'currentColor', strokeWidth: 1.8, strokeLinecap: 'round', strokeLinejoin: 'round' }} />
        </svg>
      </button>
      <div id={bodyId} className="sheet-body" hidden={!open}>
        {children}
      </div>
    </section>
  );
}
