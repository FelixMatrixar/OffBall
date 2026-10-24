import type { Lang } from '../../prefs';
import { ar } from './ar';
import { en } from './en';
import { es } from './es';
import { fr } from './fr';
import { hi } from './hi';
import { id } from './id';
import { ja } from './ja';
import { pt } from './pt';
import type { MatchStrings } from './types';
import { zh } from './zh';

export type { MatchStrings } from './types';

/**
 * The match view's words around the pitch, by language (PRD 15.3). Drafted for nine languages; Kiswahili isn't
 * written yet. The screens still use their English text inline: wiring these in comes after the English UI is done.
 */
export const MATCH_STRINGS: Partial<Record<Lang, MatchStrings>> = { en, es, pt, fr, ar, hi, id, zh, ja };

/** The match strings for a language, or English where a language has none yet. */
export const matchStrings = (lang: Lang): MatchStrings => MATCH_STRINGS[lang] ?? en;
