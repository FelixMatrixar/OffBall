import { Fragment, type CSSProperties } from 'react';
import { isCjk, isRtl } from '../../lib/i18n';
import { cx } from '../../lib/cx';
import type { Lang } from '../../lib/prefs';

interface CaptionRevealProps {
  text: string;
  lang?: Lang;
  className?: string;
  style?: CSSProperties;
  /** Delay before the first word, as a multiple of the word stagger. */
  startAfter?: number;
}

/** The last word starts within 700 ms however long the caption is (PRD 16.10). */
const MAX_STEPS = 20;

/**
 * Reveals a caption word by word: each word rises and unblurs, right to left for Arabic, character by character for
 * Chinese and Japanese. A new `text` remounts the paragraph, so the reveal replays. With reduced motion the whole
 * line fades in instead.
 */
export function CaptionReveal({ text, lang = 'en', className, style, startAfter = 0 }: CaptionRevealProps) {
  const cjk = isCjk(lang);
  const parts = cjk ? Array.from(text) : text.split(' ');
  const per = cjk ? 0.5 : 1;
  return (
    <p key={text} dir={isRtl(lang) ? 'rtl' : 'ltr'} lang={lang} className={cx('caption-line', className)} style={style}>
      {parts.map((word, i) => (
        <Fragment key={i}>
          {/* Real spaces between words, so the text reads correctly to screen readers and copies cleanly. */}
          {i > 0 && !cjk && ' '}
          <span className="caption-word" style={{ animationDelay: `calc(var(--stagger-word) * ${(startAfter + Math.min(i * per, MAX_STEPS)).toFixed(1)})` }}>
            {word}
          </span>
        </Fragment>
      ))}
    </p>
  );
}
