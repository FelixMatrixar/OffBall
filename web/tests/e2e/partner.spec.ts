// The partner graphics template (PRD 15.7): an OBS Browser Source and CasparCG HTML template that reads the overlay
// protocol from a JSONL replay, Server-Sent Events or WebSocket.
import { FEED_PORT } from '../../playwright.config';
import { expect, test } from '../helpers';

const T0 = 1_080_000;
const at = (page: import('@playwright/test').Page, ms: number) => page.waitForFunction((t) => (window as unknown as { offball: { time: () => number } }).offball.time() >= t, T0 + ms, { timeout: 20_000 });
const onAir = (page: import('@playwright/test').Page) => page.evaluate(() => (window as unknown as { offball: { onAir: string[] } }).offball.onAir);

test('replays the showcase on a transparent 1080p page, and answers CasparCG calls', async ({ page, errors }) => {
  await page.setViewportSize({ width: 1920, height: 1080 });
  await page.goto('/partner/index.html?speed=2&loop=0');
  expect(await page.evaluate(() => getComputedStyle(document.body).backgroundColor)).toBe('rgba(0, 0, 0, 0)');
  await expect(page.locator('#bug')).toHaveClass(/\bon\b/);

  // The run: its arrow goes up on the radar, and the lower third reads the line.
  await at(page, 1400);
  await expect(page.locator('#radar')).toHaveClass(/\bon\b/);
  await expect(page.locator('#caption')).toHaveText(/./);
  // The JSONL replay has no producer behind it, so graphics awaiting approval are shown too.
  await at(page, 4000);
  expect(await onAir(page)).toContain('m07-o0247');

  // The goal: the score updates, and the stat card is up.
  await at(page, 6800);
  await expect(page.locator('#score')).toHaveText('1–0');
  await expect(page.locator('#stat-title')).toHaveText('DEFENDER PULLED');

  // update() takes JSON or CasparCG's templateData XML.
  await page.evaluate(() => (window as unknown as { update: (d: string) => void }).update('{"lang":"es"}'));
  await expect(page.locator('#caption')).toHaveText(/Gol|desmarque|hueco|pase/);
  await page.evaluate(() =>
    (window as unknown as { update: (d: string) => void }).update('<templateData><componentData id="lang"><data id="text" value="fr" /></componentData></templateData>'),
  );
  await expect(page.locator('html')).toHaveAttribute('lang', 'fr');

  // stop() takes every graphic off; play() brings the bugs back.
  await page.evaluate(() => (window as unknown as { stop: () => void }).stop());
  await expect(page.locator('.gfx.on')).toHaveCount(0);
  await page.evaluate(() => (window as unknown as { play: () => void }).play());
  await expect(page.locator('#bug')).toHaveClass(/\bon\b/);
  expect(errors).toEqual([]);
});

test('waits for play() when autoplay is off, and next() jumps to the next graphic', async ({ page }) => {
  await page.goto('/partner/index.html?autoplay=0&safe=1');
  await expect(page.locator('.safe-graphics')).toBeVisible();
  await page.waitForFunction(() => /Replay/.test(document.getElementById('status')?.textContent ?? ''));
  await expect(page.locator('.gfx.on')).toHaveCount(0);
  await page.evaluate(() => (window as unknown as { play: () => void; next: () => void }).play());
  await expect(page.locator('#bug')).toHaveClass(/\bon\b/);
  const before = await page.evaluate(() => (window as unknown as { offball: { time: () => number } }).offball.time());
  await page.evaluate(() => (window as unknown as { next: () => void }).next());
  const after = await page.evaluate(() => (window as unknown as { offball: { time: () => number } }).offball.time());
  expect(after).toBeGreaterThan(before + 100);
});

test('follows a live SSE feed and honours producer approvals', async ({ page }) => {
  await page.goto(`/partner/index.html?feed=${encodeURIComponent(`sse:http://localhost:${FEED_PORT}/sse?speed=4`)}`);
  await expect(page.locator('#caption')).toHaveText(/./, { timeout: 15_000 });
  await expect(page.locator('#radar')).toHaveClass(/\bon\b/, { timeout: 15_000 });
  // The space ring is still waiting for the producer: live, it stays off air.
  await at(page, 4500);
  expect(await onAir(page)).not.toContain('m07-o0247');
});
