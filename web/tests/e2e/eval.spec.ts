// The evaluation screen (PRD 16.4, 19): every chart and table labelled as sample data, each chart with its own name
// and a table view, the statistics worked out from the data shown, and a frame-time test that measures this device.
import { FIDELITY_RESULTS, RELIABILITY_RESULTS } from '../../src/lib/eval';
import { expect, test } from '../helpers';

test.describe('the evaluation screen', () => {
  test('labels every chart and table as sample data, and names each chart', async ({ page, errors }) => {
    await page.goto('/#/eval');
    await expect(page.locator('.vega-host svg')).toHaveCount(8, { timeout: 15_000 });
    // Vega names the element it draws into; each chart keeps its own name for screen readers.
    const names = await page.locator('.vega-host').evaluateAll((els) => els.map((e) => e.getAttribute('aria-label') ?? ''));
    expect(names.filter((n) => !n || n === 'Vega visualization')).toEqual([]);
    // Eight charts and three tables carry the label, and so does the notice at the top.
    await expect(page.getByText('Sample data', { exact: true })).toHaveCount(12);
    expect(errors).toEqual([]);
  });

  test('works out each statistic from the data it shows, and says which studies haven’t run', async ({ page }) => {
    await page.goto('/#/eval');
    for (const f of FIDELITY_RESULTS) await expect(page.getByText(`KS ${f.ks.toFixed(3)}`, { exact: true })).toBeVisible();
    for (const r of RELIABILITY_RESULTS) await expect(page.getByText(`Calibration error ${r.ece.toFixed(3)}`, { exact: true })).toBeVisible();
    await expect(page.getByRole('row', { name: /Mode distinctness/ })).toContainText('Not run yet');
    await expect(page.getByRole('row', { name: /Realism/ })).toContainText('Passes');
  });

  test('each chart has a table view', async ({ page }) => {
    await page.goto('/#/eval');
    const sprint = page.locator('figure', { hasText: 'Sprint distance per player-match' });
    await sprint.getByRole('button', { name: 'Table' }).click();
    await expect(sprint.locator('table tbody tr')).toHaveCount(9);
    await expect(sprint.locator('table tbody tr').nth(4)).toContainText('50%');
  });

  test('measures frame times on this device, in 2D and in 3D', async ({ page }) => {
    test.slow();
    await page.goto('/#/eval');
    const status = page.locator('.eval-render [role="status"]');
    await expect(status).toHaveText('No measurement yet.');
    await page.getByRole('button', { name: 'Measure this device' }).click();
    await expect(status).toHaveText(/^2D view, tier C: 95% of frames within [\d.]+ ms, against a 33\.3 ms budget\. (Within budget|Over budget on this device)\.$/, { timeout: 15_000 });
    await page.getByRole('radio', { name: '3D broadcast' }).click();
    await expect(page.getByRole('button', { name: 'Measure this device' })).toBeEnabled({ timeout: 20_000 });
    await page.getByRole('button', { name: 'Measure this device' }).click();
    await expect(status).toHaveText(/^3D broadcast view, tier [AB]: 95% of frames within [\d.]+ ms, against a 16\.7 ms budget\./, { timeout: 15_000 });
    await expect(page.locator('.eval-render table tbody tr')).toHaveCount(2);
  });
});
