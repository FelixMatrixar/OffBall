// Adaptive density (PRD 8.2, 15.2, 15.9): hide groups from the pitch's Overlays menu, undo, and keep what's learned.
import { axeViolations, expect, test } from '../helpers';

const hidden = (page: import('@playwright/test').Page) => page.evaluate(() => JSON.parse(localStorage.getItem('offball.prefs') ?? '{}').hidden);

test.describe('Adaptive density', () => {
  // Tier C held, so the frame-time monitor can't step down to the video tier mid-test, where there's nothing to hide.
  test.use({ prefs: { reducedMotion: true, mode: 'analyst', tier: 'C' } });

  test('hides runs and tags in Analyst, offers Undo, steps density down and remembers it', async ({ page, errors }) => {
    await page.goto('/#/match?t=4.5');
    const menu = page.getByRole('button', { name: 'Overlays' });
    await menu.click();
    await expect(page.getByRole('menu', { name: 'Overlays' })).toBeVisible();
    await expect(page.getByRole('menuitemcheckbox')).toHaveText(['Space field', 'Space rings', 'Runs', 'Passes', 'Back line', 'Player tags']);
    expect(await axeViolations(page)).toEqual([]);

    // Each choice toggles in place and leaves the menu open.
    await page.getByRole('menuitemcheckbox', { name: 'Runs' }).click();
    await expect(page.getByRole('menuitemcheckbox', { name: 'Runs' })).toHaveAttribute('aria-checked', 'false');
    await page.getByRole('menuitemcheckbox', { name: 'Player tags' }).click();
    await expect(page.locator('.toast').last()).toContainText('Player tags hidden in Analyst. Analyst now shows fewer overlays.');
    expect(await hidden(page)).toEqual({ analyst: ['runs', 'tags'] });

    // Escape closes the menu and returns to its chip, which counts what's hidden.
    await page.keyboard.press('Escape');
    await expect(page.getByRole('menu')).toHaveCount(0);
    await expect(page.getByRole('button', { name: /Overlays/ })).toBeFocused();
    await expect(page.getByRole('button', { name: /Overlays/ })).toContainText('2 hidden');

    // Undo puts the last one back.
    await page.locator('.toast-action', { hasText: 'Undo' }).click();
    expect(await hidden(page)).toEqual({ analyst: ['runs'] });

    // Remembered after a reload, and only in Analyst.
    await page.reload();
    await expect(page.getByRole('button', { name: /Overlays/ })).toContainText('1 hidden');
    await page.getByRole('radio', { name: 'Casual' }).click();
    await expect(page.locator('.map-chip-count')).toHaveCount(0);

    // Personalize says what it learned, and forgets it on request.
    await page.getByRole('button', { name: 'Personalize' }).click();
    await expect(page.locator('.learned-list')).toHaveText('Analyst · Runs hidden');
    await page.getByRole('button', { name: 'Forget what it learned' }).click();
    await expect(page.getByText('Nothing learned yet.')).toBeVisible();
    expect(await hidden(page)).toEqual({});
    expect(errors).toEqual([]);
  });

  test('keeps choices for the page only when Adapt is off, and leaves what-if views whole', async ({ page }) => {
    await page.goto('/#/match?t=4.5');
    await page.getByRole('button', { name: 'Personalize' }).click();
    await page.getByRole('switch', { name: /Adapt to what I hide or show/ }).click();
    await page.keyboard.press('Escape');

    await page.getByRole('button', { name: 'Overlays' }).click();
    await expect(page.locator('.menu-note')).toContainText('Hidden until you leave this page.');
    await page.getByRole('menuitemcheckbox', { name: 'Runs' }).click();
    expect(await hidden(page)).toEqual({});
    await page.keyboard.press('Escape');

    // The what-if switch asks for the other world: the menu steps aside and every group is drawn.
    await page.keyboard.press('w');
    await expect(page.getByRole('button', { name: /Overlays/ })).toHaveCount(0);
    await page.keyboard.press('w');
    await expect(page.getByRole('button', { name: /Overlays/ })).toContainText('1 hidden');

    await page.reload();
    await expect(page.locator('.map-chip-count')).toHaveCount(0);
  });
});
