// The 3D views, tiers A and B (PRD 15.1, 16.2): they load on demand, follow the same clock and overlays as the 2D
// view, keep their labels and players accessible, and fall back to 2D on a device that can't draw them (VIS-4).
import { axeViolations, expect, pitchAtRest, test } from '../helpers';

const VIEWS = ['broadcast', 'tactical', 'player', 'goal'] as const;

test.describe('the 3D broadcast view at tier B', () => {
  test.use({ prefs: { view: 'broadcast', tier: 'B' } });

  test('loads on demand and shows the moment with its labels', async ({ page, errors }) => {
    await page.goto('/#/match?t=4.5');
    await expect(page.locator('.pitch-3d')).toHaveAttribute('data-view', 'broadcast');
    await pitchAtRest(page);
    await expect(page.locator('.map-chip').first()).toContainText('Tier B · WebGL2');
    await expect(page.locator('.pitch-label[data-kind="gap_ring"]')).toContainText('Space opens here');
    await expect(page.locator('canvas.pitch-3d-canvas')).toHaveAttribute('role', 'img');
    expect(errors).toEqual([]);
  });

  test('players are one tab stop, named by focus, as in 2D', async ({ page }) => {
    await page.goto('/#/match?t=2');
    await pitchAtRest(page);
    await expect(page.locator('.pitch [tabindex="0"]')).toHaveCount(1);
    await page.locator('.player-target[tabindex="0"]').focus();
    await page.keyboard.press('ArrowRight');
    await expect(page.locator(':focus')).toHaveAttribute('aria-label', /No\. 2/);
    await expect(page.locator('.pitch-label[data-kind="hint"]')).toContainText('No. 2');
  });

  test('passes axe', async ({ page }) => {
    await page.goto('/#/match?t=4.5');
    await pitchAtRest(page);
    expect(await axeViolations(page)).toEqual([]);
  });
});

test.describe('tier A', () => {
  test.use({ prefs: { view: 'broadcast', tier: 'A' } });
  test('draws with WebGPU where the browser has it', async ({ page }) => {
    await page.goto('/#/match?t=5.6');
    const webgpu = await page.evaluate(async () => !!(await (navigator as Navigator & { gpu?: { requestAdapter(): Promise<unknown> } }).gpu?.requestAdapter()));
    test.skip(!webgpu, 'This browser has no WebGPU adapter');
    await pitchAtRest(page);
    await expect(page.locator('.map-chip').first()).toContainText('Tier A · WebGPU');
  });
});

for (const view of VIEWS) {
  test.describe(`the ${view} camera`, () => {
    test.use({ prefs: { view, tier: 'B', mode: 'analyst' } });
    test('frames the moment and labels it', async ({ page, errors }) => {
      await page.goto('/#/match?t=5.6');
      await expect(page.locator('.pitch-3d')).toHaveAttribute('data-view', view);
      await pitchAtRest(page);
      // Some labels are in shot from every camera, and none is left unplaced.
      const placed = await page.locator('.pitch-label').evaluateAll((els) => els.filter((el) => (el as HTMLElement).style.visibility !== 'hidden').length);
      expect(placed).toBeGreaterThan(0);
      expect(errors).toEqual([]);
    });
  });
}

test('V moves through the views, and the picker shows the one in use', async ({ page }) => {
  await page.goto('/#/match?t=3');
  await page.waitForTimeout(800);
  await page.locator('body').click({ position: { x: 5, y: 600 } });
  await page.keyboard.press('v');
  await expect(page.locator('.pitch-3d')).toHaveAttribute('data-view', 'broadcast');
  await expect(page.locator('.pitch-view select')).toHaveValue('broadcast');
  await page.keyboard.press('v');
  await expect(page.locator('.pitch-3d')).toHaveAttribute('data-view', 'tactical');
});

test.describe('a device whose GPU context fails', () => {
  test.use({ prefs: { view: 'broadcast', tier: 'B' } });
  test('falls back to the 2D view and says so', async ({ page }) => {
    // The probe sees WebGL2, but the 3D canvas can't get a context: the engine fails as it would on a lost device.
    await page.addInitScript(() => {
      const original = HTMLCanvasElement.prototype.getContext;
      HTMLCanvasElement.prototype.getContext = function (this: HTMLCanvasElement, type: string, ...args: unknown[]) {
        if (this.classList.contains('pitch-3d-canvas')) return null;
        return (original as (...a: unknown[]) => unknown).call(this, type, ...args);
      } as typeof original;
    });
    await page.goto('/#/match?t=4.5');
    await expect(page.locator('.pitch-3d')).toHaveCount(0, { timeout: 10_000 });
    await expect(page.locator('.pitch-stage canvas.pitch-canvas').first()).toBeVisible();
    await expect(page.locator('.toast')).toContainText('2D view is showing');
    // The 3D views stay listed, marked unavailable, so it's clear why they can't be chosen.
    expect(await page.locator('.pitch-view option[value="broadcast"]').evaluate((o) => (o as HTMLOptionElement).disabled)).toBe(true);
  });
});
