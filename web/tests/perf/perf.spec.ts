// Performance budgets from PRD 16.7, measured on the production build in Chrome.
//
// Frame times: headless Chrome's own display cadence varies with the machine and its power state (from 55 to
// 144 Hz), so budgets are counted in display frames, calibrated on an empty page first. At full speed, p95 may not
// drop a frame; with the CPU slowed 4x (a stand-in for a four-year-old mid-range phone), p95 may drop one, which at
// 60 Hz is the PRD's 33 ms for tier C.
import { gzipSync } from 'node:zlib';
import { readFileSync } from 'node:fs';
import { expect, test, type Page } from '../helpers';

test.describe.configure({ mode: 'serial' });

async function frameTimes(page: Page, ms: number): Promise<number[]> {
  const d = await page.evaluate(
    (span) =>
      new Promise<number[]>((resolve) => {
        const out: number[] = [];
        let last = performance.now();
        const end = last + span;
        const tick = (now: number) => {
          out.push(now - last);
          last = now;
          if (now < end) requestAnimationFrame(tick);
          else resolve(out);
        };
        requestAnimationFrame(tick);
      }),
    ms,
  );
  return d.sort((a, b) => a - b);
}

const pct = (sorted: number[], p: number) => sorted[Math.min(sorted.length - 1, Math.floor(sorted.length * p))];

let cadence = { p50: 16.7, p95: 17.5 };

test.beforeAll(async ({ browser }) => {
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();
  await page.setContent('<div id="x" style="width:50px;height:50px;background:red"></div>');
  await page.evaluate(() => {
    const el = document.getElementById('x')!;
    const move = (now: number) => {
      el.style.transform = `translateX(${(now / 10) % 300}px)`;
      requestAnimationFrame(move);
    };
    requestAnimationFrame(move);
  });
  const d = await frameTimes(page, 2000);
  cadence = { p50: pct(d, 0.5), p95: pct(d, 0.95) };
  await context.close();
});

for (const mode of ['casual', 'analyst'] as const) {
  test.describe(`${mode} mode`, () => {
    test.use({ prefs: { mode } });
    for (const rate of [1, 4]) {
      test(`frame time p95 at ${rate}x CPU`, async ({ page, browserName }) => {
        test.skip(browserName !== 'chromium', 'CPU throttling needs the Chrome DevTools Protocol');
        await page.goto('/#/match');
        await page.waitForTimeout(1500);
        const cdp = await page.context().newCDPSession(page);
        await cdp.send('Emulation.setCPUThrottlingRate', { rate });
        const d = await frameTimes(page, 5000);
        const p95 = pct(d, 0.95);
        const budget = rate === 1 ? Math.max(17.5, cadence.p95 * 1.1) : Math.max(34, cadence.p50 * 2 + 1.5);
        test.info().annotations.push({ type: 'frames', description: `p95 ${p95.toFixed(1)} ms, budget ${budget.toFixed(1)} ms, display frame ${cadence.p50.toFixed(1)} ms, ${d.length} frames` });
        expect(p95, `p95 ${p95.toFixed(1)} ms against ${budget.toFixed(1)} ms`).toBeLessThanOrEqual(budget);
      });
    }
  });
}

test.describe('the 3D broadcast view', () => {
  test.use({ prefs: { mode: 'analyst', view: 'broadcast', tier: 'auto' } });
  test('frame time p95 at 1x CPU meets the 3D budget', async ({ page, browserName }) => {
    test.skip(browserName !== 'chromium', 'Frame pacing is measured in Chrome');
    await page.goto('/#/match');
    await expect(page.locator('.pitch-3d')).toHaveCount(1, { timeout: 10_000 });
    await expect(page.locator('.pitch-3d .pitch-stage')).toBeVisible({ timeout: 10_000 });
    await page.waitForTimeout(1500);
    const d = await frameTimes(page, 5000);
    const p95 = pct(d, 0.95);
    // Tiers A and B: 16.7 ms on a mid-range laptop (PRD 16.7), so no dropped frames at p95.
    const budget = Math.max(17.5, cadence.p95 * 1.1);
    test.info().annotations.push({ type: 'frames', description: `p95 ${p95.toFixed(1)} ms, budget ${budget.toFixed(1)} ms, ${d.length} frames` });
    expect(p95, `p95 ${p95.toFixed(1)} ms against ${budget.toFixed(1)} ms`).toBeLessThanOrEqual(budget);
  });
});

test('the first frame of a replay is drawn within 2 s', async ({ page }) => {
  await page.goto('/#/match');
  await expect(page.locator('.pitch-stage').first()).toHaveAttribute('data-resting', /true|false/, { timeout: 5000 });
  const firstFrame = await page.evaluate(() => performance.now());
  expect(firstFrame).toBeLessThan(2000);
});

test('playing the moment for 10 s doesn’t grow memory', async ({ page, browserName }) => {
  test.skip(browserName !== 'chromium', 'Heap metrics need the Chrome DevTools Protocol');
  await page.goto('/#/match');
  const cdp = await page.context().newCDPSession(page);
  await cdp.send('Performance.enable');
  const heap = async () => {
    await cdp.send('HeapProfiler.collectGarbage');
    const { metrics } = await cdp.send('Performance.getMetrics');
    return metrics.find((m) => m.name === 'JSHeapUsedSize')!.value / 1e6;
  };
  await page.waitForTimeout(3000);
  const before = await heap();
  await page.waitForTimeout(10_000);
  const after = await heap();
  expect(after, `heap ${before.toFixed(1)} MB, then ${after.toFixed(1)} MB`).toBeLessThan(500);
  expect(after - before).toBeLessThan(15);
});

test('initial JavaScript is 300 KB or less compressed', () => {
  // The entry script and what it preloads; Vega and the 3D code load on demand.
  const dist = new URL('../../dist/', import.meta.url);
  const html = readFileSync(new URL('index.html', dist), 'utf8');
  const files = [...html.matchAll(/(?:src|href)="\/?(assets\/[^"]+\.js)"/g)].map((m) => m[1]);
  expect(files.length).toBeGreaterThan(0);
  const kb = files.reduce((sum, f) => sum + gzipSync(readFileSync(new URL(f, dist))).length, 0) / 1024;
  test.info().annotations.push({ type: 'size', description: `${kb.toFixed(0)} KB gzip across ${files.length} files` });
  expect(kb).toBeLessThanOrEqual(300);
});
