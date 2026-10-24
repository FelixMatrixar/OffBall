import type { ActiveOverlay } from '../../lib/feed';
import { useI18n } from '../../lib/i18n';
import { LABELS } from '../../lib/i18n/labels';
import type { Lang } from '../../lib/prefs';
import { CaptionReveal, CheckIcon, Chip, Equalizer } from '../ui';

interface CaptionBarProps {
  /** Active caption overlays, newest revision first; a retracted one shows struck through beside its patch. */
  captions: readonly ActiveOverlay[];
  /**
   * Overrides the feed caption, e.g. the overlay-feed log in Broadcaster mode, a Learn line with the viewer's count, or a
   * changed decision's verdict. `lang` is the language it's written in (English if left out), which sets its direction.
   */
  override?: { text: string; mono?: boolean; lang?: Lang };
  meta: string;
  size: number;
  voice: { on: boolean; speaking: boolean; label: string };
  className?: string;
}

/**
 * The explanation, as DOM text so it stays sharp and readable by screen readers (PRD 15.2), revealed word by word,
 * with its fact-check status and voice state. Corrections strike the old claim and replace it within 5 s (PRD 15.11).
 */
export function CaptionBar({ captions, override, meta, size, voice, className }: CaptionBarProps) {
  const { lang, ui } = useI18n();
  const retracted = captions.find((c) => c.retraction);
  const current = captions.find((c) => !c.retraction);
  const textOf = (c: ActiveOverlay) => c.overlay.text[lang] ?? c.overlay.text.en ?? '';
  const lineLang: Lang = current && current.overlay.text[lang] ? lang : 'en';
  const text = override?.text ?? (current ? textOf(current) : '');
  const corrected = !!retracted || current?.overlay.labels.includes('correction');
  const style = override?.mono ? { fontFamily: 'var(--font-mono)', fontSize: Math.max(15, size - 3), lineHeight: 1.45 } : { fontSize: size, lineHeight: 1.4, fontWeight: 500 };
  return (
    <div className={`card caption-bar ${className ?? ''}`}>
      <div className="caption-bar-main">
        {retracted && (
          <span className="caption-old strike" lang={lang} key={retracted.overlay.overlay_id}>
            {textOf(retracted)}
          </span>
        )}
        {text ? <CaptionReveal text={text} lang={override ? (override.lang ?? 'en') : lineLang} style={style} /> : <p style={style}>&nbsp;</p>}
        <p className="caption-meta">{meta}</p>
      </div>
      <div className="caption-side">
        {corrected && (
          <Chip tone="alert" className="anim-pop">
            {LABELS[lang].correction}
          </Chip>
        )}
        {!override?.mono && text && (
          <Chip key={text} tone="outline" size="lg" style={{ fontSize: 12 }}>
            <span style={{ color: 'var(--space-ink)', display: 'inline-flex' }}>
              <CheckIcon draw size={14} />
            </span>
            {ui.factChecked}
          </Chip>
        )}
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 12, color: 'var(--muted)' }}>
          <Equalizer active={voice.on && voice.speaking} />
          {voice.label}
        </span>
      </div>
    </div>
  );
}
