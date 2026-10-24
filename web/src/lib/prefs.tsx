import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { cleanHidden, type HiddenByMode } from './density';

export type Theme = 'dark' | 'light' | 'contrast';
export type Mode = 'casual' | 'learn' | 'analyst' | 'player' | 'audio' | 'broadcaster';
export type Club = 'kes' | 'ash' | 'none';
export type Density = 'minimal' | 'standard' | 'rich';
export type Metric = 'space' | 'pass' | 'sprint';
export type Lang = 'en' | 'es' | 'pt' | 'fr' | 'ar' | 'hi' | 'id' | 'zh' | 'ja' | 'sw';
/** A locked rendering tier, or automatic (PRD 16.2). */
export type TierChoice = 'auto' | 'A' | 'B' | 'C' | 'D';
/** 2D tactical, 3D broadcast, 3D tactical, player cam, behind goal (PRD 15.1). */
export type View = '2d' | 'broadcast' | 'tactical' | 'player' | 'goal';
export type CfView = 'overlay' | 'split';
export type Layout = 'auto' | 'tv';

export const THEMES: readonly Theme[] = ['dark', 'light', 'contrast'];
export const MODE_IDS: readonly Mode[] = ['casual', 'learn', 'analyst', 'player', 'audio', 'broadcaster'];
export const LANG_IDS: readonly Lang[] = ['en', 'es', 'pt', 'fr', 'ar', 'hi', 'id', 'zh', 'ja', 'sw'];

export interface Prefs {
  theme: Theme;
  reducedMotion: boolean;
  mode: Mode;
  lang: Lang;
  club: Club;
  /** Favourite player as a contract player ID, such as kes-09 or ash-05 (PRD 12.8). */
  fav: string;
  metric: Metric;
  density: Density;
  /** Adaptive density (PRD 8.2): remember, per mode, the pitch graphics the viewer hides, and show fewer once they hide two. */
  adapt: boolean;
  /** What adaptive density has learned: the groups hidden in each mode. */
  hidden: HiddenByMode;
  voice: boolean;
  /** A stereo-panned tone where space is opening (PRD 16.6). */
  sonify: boolean;
  capSize: number;
  tier: TierChoice;
  view: View;
  cfView: CfView;
  layout: Layout;
  /** Recaps without results: scores, outcomes and goal lines hidden until asked for (PRD 8.2, 10.8). */
  spoilerSafe: boolean;
  onboarded: boolean;
}

export const DEFAULT_PREFS: Prefs = {
  theme: 'dark',
  reducedMotion: false,
  mode: 'casual',
  lang: 'en',
  club: 'kes',
  fav: 'kes-09',
  metric: 'space',
  density: 'standard',
  adapt: true,
  hidden: {},
  voice: false,
  sonify: false,
  capSize: 20,
  tier: 'auto',
  view: '2d',
  cfView: 'overlay',
  layout: 'auto',
  spoilerSafe: false,
  onboarded: false,
};

const STORAGE_KEY = 'offball.prefs';
const oneOf = <T,>(value: unknown, options: readonly T[], fallback: T): T => (options.includes(value as T) ? (value as T) : fallback);

/** Fills gaps with defaults and upgrades values saved by older builds, such as a bare shirt number for the favourite. */
export function migrate(raw: Record<string, unknown>): Prefs {
  const p = { ...DEFAULT_PREFS, ...raw } as Prefs;
  if (/^\d{1,2}$/.test(String(raw.fav ?? ''))) p.fav = `kes-${String(raw.fav).padStart(2, '0')}`;
  if (!/^(kes|ash)-\d{2}$/.test(p.fav)) p.fav = DEFAULT_PREFS.fav;
  p.theme = oneOf(p.theme, THEMES, DEFAULT_PREFS.theme);
  p.mode = oneOf(p.mode, MODE_IDS, DEFAULT_PREFS.mode);
  p.lang = oneOf(p.lang, LANG_IDS, DEFAULT_PREFS.lang);
  p.club = oneOf(p.club, ['kes', 'ash', 'none'] as const, DEFAULT_PREFS.club);
  p.metric = oneOf(p.metric, ['space', 'pass', 'sprint'] as const, DEFAULT_PREFS.metric);
  p.density = oneOf(p.density, ['minimal', 'standard', 'rich'] as const, DEFAULT_PREFS.density);
  p.tier = oneOf(p.tier, ['auto', 'A', 'B', 'C', 'D'] as const, DEFAULT_PREFS.tier);
  p.view = oneOf(p.view, ['2d', 'broadcast', 'tactical', 'player', 'goal'] as const, DEFAULT_PREFS.view);
  p.cfView = oneOf(p.cfView, ['overlay', 'split'] as const, DEFAULT_PREFS.cfView);
  p.layout = oneOf(p.layout, ['auto', 'tv'] as const, DEFAULT_PREFS.layout);
  p.capSize = Math.min(28, Math.max(16, Number(p.capSize) || DEFAULT_PREFS.capSize));
  p.spoilerSafe = p.spoilerSafe === true;
  p.adapt = p.adapt !== false;
  p.hidden = cleanHidden(p.hidden);
  return p;
}

const query = (q: string) => typeof window !== 'undefined' && typeof window.matchMedia === 'function' && window.matchMedia(q).matches;

// Preferences live on the device only (PRD 18.6); storage can be missing, so every access is guarded.
function load(): Prefs {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) return migrate(JSON.parse(raw) as Record<string, unknown>);
  } catch {
    // Unreadable or blocked storage: fall through to defaults.
  }
  // First visit: honour the OS asking for more contrast.
  return { ...DEFAULT_PREFS, theme: query('(prefers-contrast: more)') ? 'contrast' : DEFAULT_PREFS.theme };
}

function useMedia(q: string): boolean {
  const [on, setOn] = useState(() => query(q));
  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return;
    const m = window.matchMedia(q);
    const onChange = () => setOn(m.matches);
    m.addEventListener('change', onChange);
    return () => m.removeEventListener('change', onChange);
  }, [q]);
  return on;
}

interface PrefsContextValue {
  prefs: Prefs;
  update: (patch: Partial<Prefs>) => void;
  reset: () => void;
  /** The in-app switch or the OS setting (PRD 16.10). */
  reducedMotion: boolean;
  /** The 10-foot layout: chosen in Personalize, or a 4K-wide screen. */
  tv: boolean;
}

const PrefsContext = createContext<PrefsContextValue | null>(null);

export function PrefsProvider({ children }: { children: ReactNode }) {
  const [prefs, setPrefs] = useState<Prefs>(load);
  const osReduced = useMedia('(prefers-reduced-motion: reduce)');
  const wide = useMedia('(min-width: 2400px)');
  const reducedMotion = prefs.reducedMotion || osReduced;
  const tv = prefs.layout === 'tv' || wide;

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(prefs));
    } catch {
      // Storage blocked: preferences last for this visit only.
    }
    document.documentElement.dataset.theme = prefs.theme;
  }, [prefs]);

  useEffect(() => {
    document.documentElement.dataset.motion = reducedMotion ? 'reduced' : 'full';
  }, [reducedMotion]);

  useEffect(() => {
    document.documentElement.dataset.layout = tv ? 'tv' : 'auto';
  }, [tv]);

  // Another tab (the first-run flow, a paired screen) changed a setting: pick it up.
  useEffect(() => {
    const onStorage = (e: StorageEvent) => {
      if (e.key !== STORAGE_KEY || !e.newValue) return;
      try {
        setPrefs(migrate(JSON.parse(e.newValue) as Record<string, unknown>));
      } catch {
        // Ignore a malformed write from elsewhere.
      }
    };
    window.addEventListener('storage', onStorage);
    return () => window.removeEventListener('storage', onStorage);
  }, []);

  const update = useCallback((patch: Partial<Prefs>) => setPrefs((p) => ({ ...p, ...patch })), []);
  const reset = useCallback(() => setPrefs({ ...DEFAULT_PREFS, onboarded: true }), []);

  const value = useMemo<PrefsContextValue>(() => ({ prefs, update, reset, reducedMotion, tv }), [prefs, update, reset, reducedMotion, tv]);
  return <PrefsContext.Provider value={value}>{children}</PrefsContext.Provider>;
}

export function usePrefs(): PrefsContextValue {
  const ctx = useContext(PrefsContext);
  if (!ctx) throw new Error('usePrefs must be used inside PrefsProvider');
  return ctx;
}
