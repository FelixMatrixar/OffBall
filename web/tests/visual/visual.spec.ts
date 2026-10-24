// Screenshot baselines at fixed moments: the pitch in each orientation, mode and theme, and the static design pages.
// Reduced motion and a settled picture mean the only differences are real ones. Baselines are per platform; update
// them with `npm run test:visual:update` after an intended change, and review the diff.
import { expect, pitchAtRest, test, type Prefs } from '../helpers';

interface Shot {
  name: string;
  route: string;
  prefs: Prefs;
  viewport?: { width: number; height: number };
  /** Whole page rather than just the pitch. */
  page?: boolean;
  /** Waits for anything the page draws late. */
  ready?: (page: import('@playwright/test').Page) => Promise<void>;
}

/** The evaluation charts load Vega on demand; the reference scene holds still at the gap. */
const chartsDrawn = async (page: import('@playwright/test').Page) => {
  await expect(page.locator('.vega-host svg')).toHaveCount(8, { timeout: 15_000 });
  await pitchAtRest(page);
  await page.evaluate(() => document.fonts.ready);
};

/** The recap's card preview is drawn on a canvas once the web fonts are in, and drawn again if more arrive. */
const cardDrawn = async (page: import('@playwright/test').Page) => {
  await expect(page.locator('img.recap-card-img')).toBeVisible({ timeout: 10_000 });
  await page.evaluate(() => document.fonts.ready);
  await expect.poll(() => page.locator('img.recap-card-img').evaluate((img: HTMLImageElement) => img.complete && img.naturalWidth)).toBe(1080);
};

const SHOTS: Shot[] = [
  { name: 'pitch-casual-dark', route: 'match?t=4.5', prefs: { mode: 'casual' } },
  { name: 'pitch-analyst-light', route: 'match?t=5.3', prefs: { mode: 'analyst', theme: 'light' } },
  { name: 'pitch-player-contrast', route: 'match?t=3', prefs: { mode: 'player', theme: 'contrast', fav: 'kes-10' } },
  { name: 'pitch-broadcaster', route: 'match?t=6', prefs: { mode: 'broadcaster' } },
  { name: 'pitch-goal', route: 'match?t=7.5', prefs: { mode: 'learn' } },
  { name: 'pitch-arabic', route: 'match?t=2', prefs: { lang: 'ar' } },
  { name: 'pitch-phone-portrait', route: 'match?t=4.4', prefs: { mode: 'casual' }, viewport: { width: 390, height: 844 } },
  // The 3D views at tier B, which any machine with WebGL2 can draw. GPU output differs between machines, so these
  // baselines are for this machine's GPU; regenerate them on a new one.
  { name: 'pitch-3d-broadcast-analyst', route: 'match?t=5.6', prefs: { mode: 'analyst', view: 'broadcast', tier: 'B' } },
  { name: 'pitch-3d-goal', route: 'match?t=6.6', prefs: { view: 'goal', tier: 'B' } },
  { name: 'pitch-3d-tactical-light', route: 'match?t=4.5', prefs: { view: 'tactical', tier: 'B', theme: 'light' } },
  { name: 'match-analyst-page', route: 'match?t=5.3', prefs: { mode: 'analyst' }, page: true },
  { name: 'visual-language', route: 'visual-language', prefs: {}, page: true },
  { name: 'recap-fulltime', route: 'recap?kind=fulltime', prefs: {}, page: true, ready: cardDrawn },
  { name: 'eval', route: 'eval', prefs: {}, page: true, ready: chartsDrawn },
  { name: 'home', route: '', prefs: {}, page: true },
];

for (const shot of SHOTS) {
  test.describe(shot.name, () => {
    test.use({ prefs: { ...shot.prefs, reducedMotion: true } });
    test('matches its baseline', async ({ page }) => {
      if (shot.viewport) await page.setViewportSize(shot.viewport);
      await page.goto(`/#/${shot.route}`);
      if (shot.route.startsWith('match')) await pitchAtRest(page);
      await shot.ready?.(page);
      // Let DOM fades and the label layout settle.
      await page.waitForTimeout(600);
      // The frame-rate readouts change from run to run.
      const mask = [page.locator('.pitch-chips'), page.locator('.match-stage > .cluster')];
      if (shot.page) await expect(page).toHaveScreenshot(`${shot.name}.png`, { fullPage: true, mask });
      else await expect(page.locator('.pitch-card').first()).toHaveScreenshot(`${shot.name}.png`, { mask });
    });
  });
}
