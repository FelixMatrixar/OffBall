import { useEffect, useMemo } from 'react';
import { usePrefs, type Lang } from '../prefs';
import { ar } from './ar';
import { en } from './en';
import { es } from './es';
import { fr } from './fr';
import { hi } from './hi';
import { id } from './id';
import { ja } from './ja';
import { pt } from './pt';
import { sw } from './sw';
import type { Pack } from './types';
import { zh } from './zh';

export type { Concept, Pack, Six, StoryPlayer, UiStrings } from './types';
export { STORY_PLAYERS } from './types';

export const PACKS: Record<Lang, Pack> = { en, es, pt, fr, ar, hi, id, zh, ja, sw };

export const LANGS: readonly { code: Lang; native: string; en: string }[] = [
  { code: 'en', native: 'English', en: 'English' },
  { code: 'es', native: 'Español', en: 'Spanish' },
  { code: 'pt', native: 'Português', en: 'Portuguese' },
  { code: 'fr', native: 'Français', en: 'French' },
  { code: 'ar', native: 'العربية', en: 'Arabic' },
  { code: 'hi', native: 'हिन्दी', en: 'Hindi' },
  { code: 'id', native: 'Bahasa Indonesia', en: 'Indonesian' },
  { code: 'zh', native: '中文', en: 'Mandarin Chinese' },
  { code: 'ja', native: '日本語', en: 'Japanese' },
  { code: 'sw', native: 'Kiswahili', en: 'Swahili' },
];

export const isRtl = (lang: Lang) => lang === 'ar';
export const isCjk = (lang: Lang) => lang === 'zh' || lang === 'ja';

/** Replaces {name} placeholders. Unknown placeholders are left in place so a missing value is visible. */
export function fill(template: string, vars: Record<string, string | number>): string {
  return template.replace(/\{(\w+)\}/g, (whole, key: string) => (key in vars ? String(vars[key]) : whole));
}

// Building a formatter is far slower than using one, and numbers are formatted many times a frame: keep one per style.
const formatters = new Map<string, Intl.NumberFormat>();

/** Locale-aware number with Latin digits, so figures read the same in every language (PRD 16.3). */
export function fmtNum(lang: Lang, n: number, digits = 0): string {
  const key = `${lang}:${digits}`;
  let f = formatters.get(key);
  if (!f) {
    f = new Intl.NumberFormat(`${lang}-u-nu-latn`, { minimumFractionDigits: digits, maximumFractionDigits: digits });
    formatters.set(key, f);
  }
  return f.format(n);
}

export function useI18n() {
  const { prefs } = usePrefs();
  return useMemo(() => {
    const pack = PACKS[prefs.lang];
    return {
      lang: prefs.lang,
      pack,
      ui: pack.ui,
      dir: isRtl(prefs.lang) ? ('rtl' as const) : ('ltr' as const),
      num: (n: number, digits = 0) => fmtNum(prefs.lang, n, digits),
    };
  }, [prefs.lang]);
}

/**
 * Viewer surfaces speak the viewer's language: this sets lang and dir on <html> while the screen is mounted,
 * so panels mirror for Arabic (PRD 15.3). Operator screens such as the producer console stay English.
 */
export function useDocumentLocale(lang: Lang) {
  useEffect(() => {
    const root = document.documentElement;
    root.lang = lang;
    root.dir = isRtl(lang) ? 'rtl' : 'ltr';
    return () => {
      root.lang = 'en';
      root.dir = 'ltr';
    };
  }, [lang]);
}
