import { useCallback, useEffect, useRef, useState, type CSSProperties } from 'react';
import { cx } from '../../lib/cx';
import { tokenMs } from '../../lib/motion';

/** A shimmering placeholder that holds the space while data loads. */
export function Skeleton({ width = '100%', height = 14, radius = 6, style }: { width?: number | string; height?: number; radius?: number; style?: CSSProperties }) {
  return <span className="skeleton" aria-hidden="true" style={{ display: 'block', width, height, borderRadius: radius, ...style }} />;
}

export type ToastTone = 'info' | 'success' | 'warn';

export interface ToastItem {
  id: string;
  text: string;
  tone?: ToastTone;
  /** One quick way back, such as Undo. */
  action?: { label: string; onClick: () => void };
}

const TONE_COLOR: Record<ToastTone, string> = {
  info: 'var(--kes)',
  success: 'var(--space)',
  warn: 'var(--ash)',
};

/**
 * Toasts rise in with a small overshoot and fade out when they leave (PRD 16.10). A toast that disappears from
 * `toasts` stays for the exit duration with a leaving class. Announced politely.
 */
export function ToastStack({ toasts }: { toasts: readonly ToastItem[] }) {
  const [shown, setShown] = useState<(ToastItem & { leaving?: boolean })[]>(() => [...toasts]);
  useEffect(() => {
    const ids = new Set(toasts.map((t) => t.id));
    setShown((prev) => {
      const kept = prev.map((t) => (ids.has(t.id) ? t : { ...t, leaving: true }));
      const added = toasts.filter((t) => !prev.some((p) => p.id === t.id));
      return [...kept, ...added];
    });
    const id = window.setTimeout(() => setShown((prev) => prev.filter((t) => !t.leaving)), tokenMs('--dur-quick'));
    return () => window.clearTimeout(id);
  }, [toasts]);
  return (
    <div className="toast-stack" role="status" aria-live="polite">
      {shown.map((t) => (
        <div key={t.id} className={cx('toast', t.leaving && 'toast-leaving')}>
          <span className="toast-dot" style={{ background: TONE_COLOR[t.tone ?? 'info'] }} />
          <span>{t.text}</span>
          {t.action && !t.leaving && (
            <button type="button" className="toast-action press" onClick={t.action.onClick}>
              {t.action.label}
            </button>
          )}
        </div>
      ))}
    </div>
  );
}

/** Toasts that dismiss themselves after the hold time (3.5 s, PRD 16.10). */
export function useToasts() {
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const timers = useRef<number[]>([]);

  useEffect(() => () => timers.current.forEach(clearTimeout), []);

  const push = useCallback((text: string, tone: ToastTone = 'info') => {
    const id = `${Date.now()}-${Math.random().toString(36).slice(2)}`;
    setToasts((ts) => [...ts, { id, text, tone }]);
    timers.current.push(window.setTimeout(() => setToasts((ts) => ts.filter((t) => t.id !== id)), tokenMs('--dur-hold')));
  }, []);

  return { toasts, push };
}
