// The last steps down (PRD 16.2): tier D's recorded clip, kept in step with the match clock, and a static recap when
// scripts are off. Every device gets the story (VIS-4).
import { expect, test } from '../helpers';

test.describe('tier D, the recorded clip', () => {
  test.use({ prefs: { tier: 'D' } });

  test('follows the match clock: plays, pauses and scrubs with it', async ({ page }) => {
    await page.goto('/#/match');
    const video = page.locator('.pitch-video video');
    await expect(video).toHaveCount(1);
    await expect(page.locator('.map-chip').filter({ hasText: 'Tier D' })).toContainText('Video');
    await expect.poll(() => video.evaluate((v: HTMLVideoElement) => v.readyState), { timeout: 10_000 }).toBeGreaterThanOrEqual(2);
    // Playing: the video runs with the clock.
    await expect.poll(() => video.evaluate((v: HTMLVideoElement) => !v.paused && v.currentTime > 0.3), { timeout: 10_000 }).toBe(true);
    // Paused and scrubbed: the frame on screen is the moment on the clock.
    await page.locator('body').click({ position: { x: 5, y: 600 } });
    await page.keyboard.press('k');
    await expect.poll(() => video.evaluate((v: HTMLVideoElement) => v.paused)).toBe(true);
    await page.locator('#match-scrub').focus();
    await page.keyboard.press('Home');
    for (let i = 0; i < 100; i++) await page.keyboard.press('ArrowRight');
    await expect.poll(() => video.evaluate((v: HTMLVideoElement) => Math.round(v.currentTime * 100) / 100)).toBeCloseTo(4, 1);
    // The caption is still live text, not pixels.
    await expect(page.locator('.caption-line')).not.toHaveText(/^\s*$/);
  });
});

test.describe('a device that can’t hold 30 fps', () => {
  test.use({ prefs: { view: '2d', tier: 'auto' } });
  test('steps down to the clip and says so', async ({ page }) => {
    test.slow();
    await page.goto('/#/match');
    await expect(page.locator('.pitch-stage canvas').first()).toBeVisible();
    await page.getByText('Demo controls').click();
    await page.getByRole('switch', { name: 'Slow device' }).click();
    await expect(page.locator('.pitch-video video')).toHaveCount(1, { timeout: 15_000 });
    await expect(page.locator('.toast')).toContainText('Tier D');
  });
});

test.describe('without scripts', () => {
  test.use({ javaScriptEnabled: false });
  test('shows a static recap of the moment with the clip', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByRole('heading', { level: 1 })).toContainText('Kestrel Bay 1–0 Ashmoor');
    await expect(page.locator('noscript ~ #root, #root')).toBeEmpty();
    await expect(page.locator('main video')).toHaveAttribute('src', 'clips/showcase-casual.mp4');
  });
});
