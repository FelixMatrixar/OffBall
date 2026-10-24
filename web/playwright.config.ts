import { defineConfig, devices } from '@playwright/test';

/** The preview server the browser tests run against: a production build, as viewers get it. */
const PORT = Number(process.env.PW_PORT ?? 4180);
/** The local live feed (scripts/feed-server.mjs), for the live and offline tests. */
export const FEED_PORT = Number(process.env.PW_FEED_PORT ?? 8788);

/**
 * The browser. Google Chrome by default, since most machines have it; set PW_CHANNEL=bundled to use Playwright's
 * own Chromium after `npx playwright install chromium`, as CI does.
 */
const channel = process.env.PW_CHANNEL === 'bundled' ? undefined : (process.env.PW_CHANNEL ?? 'chrome');
const desktop = { ...devices['Desktop Chrome'], channel, viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 };

// Unit tests need no server; everything else runs against the preview build.
const asked = process.argv.filter((a) => a.startsWith('--project=')).map((a) => a.slice('--project='.length));
const needsServer = asked.length === 0 || asked.some((p) => p !== 'unit');

export default defineConfig({
  testDir: './tests',
  outputDir: './test-results/artifacts',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: [[process.env.CI ? 'github' : 'list'], ['html', { open: 'never', outputFolder: 'test-results/report' }]],
  use: { baseURL: `http://localhost:${PORT}`, trace: 'retain-on-failure', screenshot: 'only-on-failure' },
  expect: { toHaveScreenshot: { maxDiffPixelRatio: 0.015, animations: 'disabled', caret: 'hide' } },
  snapshotPathTemplate: '{testDir}/__screenshots__/{arg}-{platform}{ext}',
  projects: [
    // Pure logic: the contracts, the feed store, frames, the field, colour and kit checks, label layout.
    { name: 'unit', testDir: './tests/unit' },
    // Every route in every theme (axe and console), and the behaviours viewers rely on.
    { name: 'e2e', testDir: './tests/e2e', use: desktop },
    // Screenshot baselines at fixed moments. Update with `npm run test:visual:update` after an intended change.
    { name: 'visual', testDir: './tests/visual', use: desktop },
    // Frame-time budgets (PRD 16.7). Run alone (`npm run test:perf`), since other work on the machine skews them.
    { name: 'perf', testDir: './tests/perf', use: desktop },
  ],
  webServer: needsServer
    ? [
        {
          command: `npm run build && npx vite preview --port ${PORT} --strictPort`,
          url: `http://localhost:${PORT}`,
          reuseExistingServer: !process.env.CI,
          timeout: 180_000,
        },
        { command: `node scripts/feed-server.mjs --port ${FEED_PORT}`, url: `http://localhost:${FEED_PORT}/`, reuseExistingServer: !process.env.CI },
      ]
    : undefined,
});
