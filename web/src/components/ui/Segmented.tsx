import { useEffect, useRef, type CSSProperties, type KeyboardEvent } from 'react';

export interface SegOption<T extends string> {
  value: T;
  label: string;
}

interface SegmentedProps<T extends string> {
  options: readonly SegOption<T>[];
  value: T;
  onChange: (value: T) => void;
  label: string;
  /** Minimum width of each segment in px; the control scrolls sideways when it can't fit. */
  minWidth?: number;
  dots?: boolean;
  maxWidth?: number;
  /** Language of the option labels, when it differs from the page. */
  lang?: string;
}

/**
 * A segmented control whose indicator slides to the chosen option. The indicator is sized from the real column
 * width, so it stays under its button when the control scrolls on narrow screens; arrow keys move the choice.
 */
export function Segmented<T extends string>({ options, value, onChange, label, minWidth, dots = false, maxWidth, lang }: SegmentedProps<T>) {
  const index = Math.max(0, options.findIndex((o) => o.value === value));
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const scroller = useRef<HTMLDivElement>(null);

  // When the options don't fit, the edges with more options past them fade, so it's clear the row scrolls.
  useEffect(() => {
    const el = scroller.current;
    if (!el) return;
    const update = () => {
      const travelled = Math.abs(el.scrollLeft);
      const more = el.scrollWidth - el.clientWidth;
      el.dataset.moreStart = String(more > 2 && travelled > 2);
      el.dataset.moreEnd = String(more > 2 && travelled < more - 2);
    };
    update();
    el.addEventListener('scroll', update, { passive: true });
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => {
      el.removeEventListener('scroll', update);
      ro.disconnect();
    };
  }, []);

  // The chosen option stays in view, however it was chosen (a click, a key, a shortcut elsewhere).
  useEffect(() => {
    const el = scroller.current;
    const btn = refs.current[index];
    if (!el || !btn || el.scrollWidth <= el.clientWidth) return;
    // Measured on screen, so it works the same in right-to-left languages; only this row scrolls, never the page.
    const box = el.getBoundingClientRect();
    const b = btn.getBoundingClientRect();
    if (b.left < box.left || b.right > box.right) el.scrollBy({ left: b.left + b.width / 2 - (box.left + box.width / 2) });
  }, [index]);
  const style = {
    '--count': options.length,
    '--index': index,
    '--min': `${minWidth ?? 0}px`,
    maxWidth,
  } as CSSProperties;

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    const rtl = getComputedStyle(e.currentTarget).direction === 'rtl';
    const forward = rtl ? 'ArrowLeft' : 'ArrowRight';
    const back = rtl ? 'ArrowRight' : 'ArrowLeft';
    let next = -1;
    if (e.key === forward) next = Math.min(options.length - 1, index + 1);
    if (e.key === back) next = Math.max(0, index - 1);
    if (e.key === 'Home') next = 0;
    if (e.key === 'End') next = options.length - 1;
    if (next < 0) return;
    e.preventDefault();
    onChange(options[next].value);
    refs.current[next]?.focus();
    refs.current[next]?.scrollIntoView({ block: 'nearest', inline: 'nearest' });
  };

  return (
    <div ref={scroller} className="seg-scroll">
      <div className="seg" role="radiogroup" aria-label={label} style={style} onKeyDown={onKeyDown} lang={lang}>
        <span className="seg-indicator" aria-hidden="true" />
        {options.map((o, i) => (
          <button
            key={o.value}
            ref={(el) => {
              refs.current[i] = el;
            }}
            type="button"
            role="radio"
            className="seg-btn"
            aria-checked={o.value === value}
            tabIndex={o.value === value ? 0 : -1}
            onClick={() => onChange(o.value)}
          >
            {dots && <span className="seg-dot" aria-hidden="true" />}
            {o.label}
          </button>
        ))}
      </div>
    </div>
  );
}
