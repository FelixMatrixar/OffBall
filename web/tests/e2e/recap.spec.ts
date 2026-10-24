// The recap package (PRD 10.8) and the producer's recap builder (15.6): moments biggest space first, a halftime recap
// that knows nothing of the second half, spoiler-safe recaps, curated recaps that reach open views at once, and
// exports that carry the label.
import { readFileSync } from 'node:fs';
import { expect, test } from '../helpers';

/** A PNG's size, from its header. */
const pngSize = (path: string) => {
  const b = readFileSync(path);
  return { width: b.readUInt32BE(16), height: b.readUInt32BE(20) };
};

const minutes = (page: import('@playwright/test').Page) => page.locator('.recap-moment .chip-outline');

test.describe('the full-time recap', () => {
  test('tells the moments biggest space first, with the result', async ({ page, errors }) => {
    await page.goto('/#/recap?kind=fulltime');
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Kestrel Bay 1–0 Ashmoor');
    await expect(minutes(page)).toHaveText(['27′', '63′', '12′', '41′', '55′']);
    await expect(page.locator('.recap-moment').nth(1).locator('.chip-space')).toHaveText('Goal');
    await expect(page.locator('.recap-hero')).toContainText('biggest space first');
    await expect(page.locator('video.recap-clip')).toHaveAttribute('src', 'clips/share-vertical.mp4');
    expect(errors).toEqual([]);
  });

  test('downloads a 1080 × 1350 player card, described by its alt text', async ({ page }) => {
    await page.goto('/#/recap?kind=fulltime');
    // The preview is drawn once the web fonts arrive, or after a few seconds without them.
    await expect(page.locator('img.recap-card-img')).toHaveAttribute('alt', /^Player card: No\. 9 J\. Velmar, Kestrel Bay\. 118 m² .* OffBall · synthetic data · AI-generated\.$/, { timeout: 10_000 });
    const [card] = await Promise.all([page.waitForEvent('download'), page.getByRole('button', { name: 'Download PNG' }).click()]);
    expect(card.suggestedFilename()).toBe('offball-card-kes-09.png');
    expect(pngSize(await card.path())).toEqual({ width: 1080, height: 1350 });
    // Another player redraws the preview.
    await page.getByLabel('Player', { exact: true }).selectOption('ash-10');
    await expect(page.locator('img.recap-card-img')).toHaveAttribute('alt', /No\. 10 S\. Moravec, Ashmoor/, { timeout: 10_000 });
  });
});

test.describe('the halftime recap', () => {
  test('covers the first half only', async ({ page }) => {
    await page.goto('/#/recap?kind=halftime');
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Kestrel Bay 0–0 Ashmoor');
    await expect(minutes(page)).toHaveText(['27′', '12′', '41′']);
    await expect(page.getByText('Kestrel Bay No. 9, J. Velmar created the most space off the ball in the first half: 63 m²', { exact: false })).toBeVisible();
    await expect(page.getByText('5 shots, sized by expected goals')).toBeVisible();
    // The clip and the cards are about the whole match.
    await expect(page.locator('video.recap-clip')).toHaveCount(0);
    await expect(page.getByText('Player cards and the vertical clip come with the full-time recap')).toBeVisible();
  });
});

test.describe('a spoiler-safe recap', () => {
  test.use({ prefs: { spoilerSafe: true } });

  test('hides the score and every outcome until asked', async ({ page }) => {
    await page.goto('/#/recap?kind=fulltime');
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Kestrel Bay v Ashmoor');
    await expect(page.locator('.recap-moment .chip-space')).toHaveCount(0);
    await expect(page.locator('.recap-moment h3').nth(1)).toHaveText('The decoy run: No. 9 pulls No. 5 wide');
    await expect(page.locator('.recap-moments')).not.toContainText('score');
    await expect(page.locator('video.recap-clip')).toHaveAttribute('src', 'clips/share-vertical-safe.mp4');
    await expect(page.getByText(/Outcomes are hidden\./).first()).toBeVisible();
    await expect(page.locator('img.recap-card-img')).toHaveAttribute('alt', /^Player card: .*covered\. OffBall/, { timeout: 10_000 });

    // The CSV says what it is, and hides outcomes too.
    const [csv] = await Promise.all([page.waitForEvent('download'), page.getByRole('button', { name: 'Download as CSV' }).click()]);
    const lines = readFileSync(await csv.path(), 'utf8').trim().split('\n');
    expect(lines[0]).toBe('# OffBall · synthetic data · AI-generated');
    expect(lines.slice(2).every((l) => l.endsWith(',hidden'))).toBe(true);

    await page.getByRole('button', { name: 'Show the result' }).click();
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Kestrel Bay 1–0 Ashmoor');
  });
});

test.describe('the producer’s recap builder', () => {
  test('a curated recap reaches open recaps at once, and withdrawing restores the automatic one', async ({ page, context }) => {
    const producer = page;
    await producer.goto('/#/producer?t=2');
    const builder = producer.getByRole('region', { name: 'Recap builder' });
    await expect(builder.locator('.chip').first()).toHaveText('Automatic');

    const recap = await context.newPage();
    await recap.goto('/#/recap?kind=halftime');
    await expect(minutes(recap)).toHaveText(['27′', '12′', '41′']);

    // The 12′ moment first, the 41′ left out, spoiler-safe.
    await builder.getByRole('button', { name: 'Move the 12′ moment up' }).click();
    // At the top its up button is off, so focus stays on the row's other button.
    await expect(builder.getByRole('button', { name: 'Move the 12′ moment down' })).toBeFocused();
    await expect(builder.getByRole('status')).toHaveText('12′ moment moved to 1 of 3.');
    await builder.getByRole('checkbox', { name: /41′/ }).uncheck();
    await builder.getByRole('switch', { name: /Spoiler-safe/ }).click();
    await expect(builder.locator('.chip').first()).toHaveText('Draft');
    await builder.getByRole('button', { name: 'Publish recap' }).click();
    await expect(builder.getByRole('status')).toHaveText('Halftime recap published with 2 moments.');
    await expect(builder.locator('.chip').first()).toHaveText(/^Published at /);

    // The open recap follows without a reload, in the producer's order and spoiler-safe.
    await expect(minutes(recap)).toHaveText(['12′', '27′']);
    await expect(recap.getByRole('heading', { level: 1 })).toHaveText('Kestrel Bay v Ashmoor');
    await expect(recap.locator('.recap-hero')).toContainText('Scores and outcomes are hidden in this recap.');
    await expect(recap.locator('.recap-hero .card-label')).toContainText('curated by the producer');

    // A recap opened afterwards gets the same package.
    const later = await context.newPage();
    await later.goto('/#/recap?kind=halftime');
    await expect(minutes(later)).toHaveText(['12′', '27′']);

    await builder.getByRole('button', { name: 'Withdraw' }).click();
    await expect(minutes(recap)).toHaveText(['27′', '12′', '41′']);
    await expect(recap.getByRole('heading', { level: 1 })).toHaveText('Kestrel Bay 0–0 Ashmoor');
    await expect(builder.locator('.chip').first()).toHaveText('Automatic');
  });
});
