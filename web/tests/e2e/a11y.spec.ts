// Every route in every theme: no WCAG 2.2 AA violations from axe, and nothing in the console (PRD 15.4).
import { ROUTES, animationsSettled, axeViolations, expect, test } from '../helpers';

/** Screens that play the moment: paused at 63:02, so captions and queues aren't changing while axe reads them. */
const PLAYS = new Set(['match', 'phone', 'onboarding', 'producer']);

for (const theme of ['dark', 'light', 'contrast'] as const) {
  test.describe(`${theme} theme`, () => {
    // Reduced motion, so nothing is mid-animation when axe reads colours and contrast.
    test.use({ prefs: { theme, reducedMotion: true } });
    for (const route of ROUTES) {
      test(`#/${route} is accessible and error-free`, async ({ page, errors }) => {
        await page.goto(`/#/${route}${PLAYS.has(route) ? "?t=2" : ""}`);
        await page.waitForTimeout(1500);
        await animationsSettled(page);
        expect(await axeViolations(page)).toEqual([]);
        expect(errors).toEqual([]);
      });
    }
  });
}
