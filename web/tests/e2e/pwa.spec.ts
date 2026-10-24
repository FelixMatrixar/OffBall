// The installable app and its offline state (PRD 4.3, 15.11): a manifest and icons, a service worker that opens the
// app without a network, and a live feed that falls back to the minutes saved on the device, then catches up.
import { FEED_PORT } from '../../playwright.config';
import { expect, test, type Page } from '../helpers';

/** Waits until the service worker controls the page, so the app shell is cached. */
async function controlled(page: Page) {
  await page.evaluate(async () => {
    await navigator.serviceWorker.ready;
    if (!navigator.serviceWorker.controller) await new Promise((resolve) => navigator.serviceWorker.addEventListener('controllerchange', resolve, { once: true }));
  });
}

test('is installable: a manifest with its icons, and a service worker', async ({ page, request }) => {
  await page.goto('/');
  const href = await page.locator('link[rel="manifest"]').getAttribute('href');
  const manifest = await (await request.get(href!)).json();
  expect(manifest).toMatchObject({ name: 'OffBall', display: 'standalone', start_url: './#/match' });
  for (const size of ['192x192', '512x512']) expect(manifest.icons.some((i: { sizes: string }) => i.sizes === size)).toBe(true);
  expect(manifest.icons.some((i: { purpose?: string }) => i.purpose === 'maskable')).toBe(true);
  for (const icon of manifest.icons) {
    const res = await request.get(icon.src);
    expect(res.status(), icon.src).toBe(200);
    expect(res.headers()['content-type']).toContain('image/png');
  }
  await controlled(page);
});

test('opens without a network once it has been visited', async ({ page, context }) => {
  await page.goto('/#/match?t=3');
  await expect(page.locator('.pitch-stage').first()).toBeVisible();
  await controlled(page);
  await context.setOffline(true);
  await page.reload();
  await expect(page.locator('.pitch-stage').first()).toBeVisible();
  await expect(page.getByRole('status').filter({ hasText: 'offline' }).first()).toContainText('The last 10 minutes are saved on this device');
  await context.setOffline(false);
});

test('a live feed plays, replays what the device saved while offline, and catches up on reconnect', async ({ page, context }) => {
  test.slow();
  const feed = `sse:http://localhost:${FEED_PORT}/sse?speed=2`;
  await page.goto(`/#/match?feed=${feed}`);
  // The feed's name sits with the demo controls, out of viewers' way.
  const source = page.locator('.demo-tools');
  await expect(source).toContainText('Live · Server-Sent Events', { timeout: 10_000 });
  await expect(page.locator('.scoreboard, [role="group"]').filter({ hasText: 'LIVE' }).first()).toBeVisible();
  await controlled(page);
  // The device keeps the last 10 minutes, saved every 5 s.
  await expect
    .poll(
      () =>
        page.evaluate(
          () =>
            new Promise<number>((resolve) => {
              // Opened as the app opens it, so the check can't leave a database without its store.
              const open = indexedDB.open('offball');
              open.onupgradeneeded = () => open.result.createObjectStore('feed-buffers');
              open.onsuccess = () => {
                if (!open.result.objectStoreNames.contains('feed-buffers')) return resolve(0);
                const get = open.result.transaction('feed-buffers').objectStore('feed-buffers').get('m07');
                get.onsuccess = () => resolve(get.result?.messages.length ?? 0);
                get.onerror = () => resolve(0);
              };
              open.onerror = () => resolve(0);
            }),
        ),
      { timeout: 15_000 },
    )
    .toBeGreaterThan(50);

  await context.setOffline(true);
  await page.reload();
  await expect(source).toContainText('Offline · saved on this device', { timeout: 10_000 });
  await expect(page.locator('.pitch-stage').first()).toBeVisible();
  await expect(page.getByText('REPLAY', { exact: true }).first()).toBeVisible();

  await context.setOffline(false);
  await expect(source).toContainText('Live · Server-Sent Events', { timeout: 20_000 });
});
