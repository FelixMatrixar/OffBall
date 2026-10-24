// The other screens: Ask OffBall on the phone, the Space Centre's sweep and ticker, and the producer console.
import { expect, test } from '../helpers';

test.describe('Ask OffBall', () => {
  test('answers a typed question with the evidence, and declines betting', async ({ page }) => {
    await page.goto('/#/phone');
    await page.getByRole('radio', { name: 'Ask' }).click();
    await page.locator('.ask-form input').fill('Who is the fastest player?');
    await page.keyboard.press('Enter');
    await expect(page.locator('.ask-log')).toContainText(/fastest/i, { timeout: 10_000 });
    await expect(page.locator('.ask-log')).toContainText('km/h');
    await page.locator('.ask-form input').fill('What are the odds Kestrel win?');
    await page.keyboard.press('Enter');
    await expect(page.locator('.ask-log')).toContainText('doesn’t do odds or betting', { timeout: 10_000 });
  });
});

test.describe('the Space Centre', () => {
  test('sweeps end off-screen, and the ticker can be paused without a mouse', async ({ page }) => {
    await page.goto('/#/space-centre');
    await page.waitForTimeout(2500);
    const sweeps = await page.locator('.sweep').evaluateAll((els) => els.map((el) => getComputedStyle(el).transform));
    expect(sweeps.every((t) => t !== 'none')).toBe(true);
    await expect(page.locator('.ticker-wrap button')).toHaveCount(1);
    // The ticker's loop copy is hidden from screen readers, so each line is read once.
    const items = await page.locator('.ticker > span').evaluateAll((els) => els.map((el) => el.getAttribute('aria-hidden')));
    expect(items.filter((h) => h === 'true').length).toBe(items.length / 2);
  });
});

test.describe('the producer console', () => {
  test.use({ prefs: { mode: 'broadcaster' } });

  test('approvals reach an open match view, and a correction strikes and patches the claim', async ({ page, context }) => {
    // The fixture's page carries the seeded preferences into this context; the match opens in a second tab.
    const producer = page;
    await producer.goto('/#/producer');
    await producer.getByRole('button', { name: 'Reset all decisions' }).click();

    const match = await context.newPage();
    await match.goto('/#/match?t=5');
    await match.waitForTimeout(1200);
    // In Broadcaster mode, the gap ring waits for the producer.
    await expect(match.locator('.pitch-label[data-kind="gap_ring"]')).toHaveCount(0);
    await producer.locator('li.queue-item', { hasText: 'gap_ring' }).getByRole('button', { name: 'Approve' }).click();
    await expect(match.locator('.pitch-label[data-kind="gap_ring"]')).toHaveCount(1);

    // Analyst mode: the pass caption is struck and replaced, with a Correction tag.
    await match.evaluate(() => {
      const p = JSON.parse(localStorage.getItem('offball.prefs') ?? '{}');
      localStorage.setItem('offball.prefs', JSON.stringify({ ...p, mode: 'analyst' }));
    });
    await match.goto('/#/match?t=4.5');
    await match.reload();
    await match.waitForTimeout(1200);
    await producer.getByRole('button', { name: 'Simulate a feed correction' }).click();
    await expect(match.locator('.caption-old')).toContainText('28.0', { timeout: 10_000 });
    await expect(match.locator('.caption-line')).toContainText('27.4');
    await expect(match.locator('.caption-side .chip-alert')).toHaveCount(1);
    await producer.getByRole('button', { name: 'Reset all decisions' }).click();
  });
});
