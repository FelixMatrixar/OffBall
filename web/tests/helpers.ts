// Shared fixtures for the browser tests: seeded preferences, collected errors, axe, and waiting for the pitch.
import { test as base, expect, type BrowserContext, type Page } from '@playwright/test';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const AXE = require.resolve('axe-core/axe.min.js');

/** Every route, for the sweeps. */
export const ROUTES = ['', 'match', 'phone', 'onboarding', 'space-centre', 'broadcast', 'producer', 'recap', 'eval', 'components', 'visual-language', 'motion', 'states'] as const;

/** A returning viewer with the default settings, so the first-run screen doesn't intercept routes. */
export const DEFAULT_PREFS = {
  theme: 'dark',
  reducedMotion: false,
  mode: 'casual',
  lang: 'en',
  club: 'kes',
  fav: 'kes-09',
  metric: 'space',
  density: 'standard',
  voice: false,
  sonify: false,
  capSize: 20,
  tier: 'auto',
  view: '2d',
  cfView: 'overlay',
  layout: 'auto',
  spoilerSafe: false,
  onboarded: true,
};

export type Prefs = Partial<Record<keyof typeof DEFAULT_PREFS, string | number | boolean>>;

/** Seeds preferences once per context, before the app reads them; reloads keep whatever the app changed since. */
export async function seedPrefs(context: BrowserContext, prefs: Prefs = {}): Promise<void> {
  await context.addInitScript(
    (p) => {
      if (sessionStorage.getItem('test-seeded')) return;
      localStorage.setItem('offball.prefs', JSON.stringify(p));
      sessionStorage.setItem('test-seeded', '1');
    },
    { ...DEFAULT_PREFS, ...prefs },
  );
}

/** Console errors and uncaught exceptions on a page. */
export function collectErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on('console', (m) => {
    if (m.type() === 'error') errors.push(m.text());
  });
  page.on('pageerror', (e) => errors.push(String(e)));
  return errors;
}

/** WCAG 2.2 AA violations on the page as it is now, one line each. */
export async function axeViolations(page: Page): Promise<string[]> {
  await page.addScriptTag({ path: AXE });
  return page.evaluate(async () => {
    const run = (window as unknown as { axe: { run: (ctx: Document, opts: object) => Promise<{ violations: { id: string; nodes: { target: string[]; failureSummary?: string }[] }[] }> } }).axe.run;
    const r = await run(document, { runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'] } });
    return r.violations.map((v) => `${v.id} (${v.nodes.length}): ${v.nodes.slice(0, 2).map((n) => `${n.target.join(' ')} ${(n.failureSummary ?? '').split('\n')[1] ?? ''}`).join(' | ')}`);
  });
}

/**
 * Brings every finite animation to its end, so axe reads final colours rather than a word mid-fade. The galleries
 * restart their demos on a cycle, so this finishes them rather than waiting. Live indicators loop and are left alone.
 */
export async function animationsSettled(page: Page): Promise<void> {
  await page.evaluate(() => {
    for (const a of document.getAnimations()) if (a.playState === 'running' && a.effect?.getComputedTiming().endTime !== Infinity) a.finish();
  });
}

/** Waits until the pitch has nothing entering or looping, so a screenshot or a check sees the settled picture. */
export async function pitchAtRest(page: Page): Promise<void> {
  await expect(page.locator('.pitch-stage').first()).toHaveAttribute('data-resting', 'true', { timeout: 10_000 });
}

/** The test API with preferences as an option: `test.use({ prefs: { mode: 'analyst' } })`. */
export const test = base.extend<{ prefs: Prefs; errors: string[] }>({
  prefs: [{}, { option: true }],
  page: async ({ page, context, prefs }, use) => {
    await seedPrefs(context, prefs);
    await use(page);
  },
  errors: async ({ page }, use) => {
    await use(collectErrors(page));
  },
});

export { expect };
export type { Page };
