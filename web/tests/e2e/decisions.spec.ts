// Change one decision (PRD 10.10, 15.12): pick a player, choose an option, re-run, see the changed world.
import { axeViolations, expect, test } from '../helpers';

test.describe('Change one decision', () => {
  test.use({ prefs: { reducedMotion: true } });

  test('picks No. 9, re-runs "Stay central" and shows the changed world, accessibly', async ({ page, errors }) => {
    await page.goto('/#/match?t=4.5');
    await page.getByRole('button', { name: /Change a decision/ }).click();
    await expect(page.getByRole('heading', { name: 'Whose decision?' })).toBeVisible();
    expect(await axeViolations(page)).toEqual([]);

    await page.getByRole('button', { name: /No\. 9 · J\. Velmar/ }).click();
    await page.getByRole('radio', { name: /Stay central/ }).check({ force: true });
    await page.getByRole('button', { name: /Re-run 32 times/ }).click();
    await expect(page.getByRole('heading', { name: 'If No. 9 stays central' })).toBeVisible({ timeout: 8000 });
    await expect(page.locator('.map-chip', { hasText: 'Field: if No. 9 stays central' })).toBeVisible();
    await expect(page.locator('.decision-compare')).toContainText('3 of 32');
    expect(await axeViolations(page)).toEqual([]);

    // D closes it and the match comes back.
    await page.keyboard.press('d');
    await expect(page.locator('.decision')).toHaveCount(0);
    expect(errors).toEqual([]);
  });
});

test.describe('Change one decision in Spanish', () => {
  test.use({ prefs: { reducedMotion: true, lang: 'es' } });

  test('speaks the viewer’s language, from the button to the result', async ({ page, errors }) => {
    await page.goto('/#/match?t=4.5');
    await page.keyboard.press('d');
    await expect(page.getByRole('heading', { name: '¿La decisión de quién?' })).toBeVisible();
    await page.getByRole('button', { name: /El 9 · J\. Velmar/ }).click();
    await page.getByRole('radio', { name: /Quedarse por dentro/ }).check({ force: true });
    await page.getByRole('button', { name: 'Repetir 32 veces' }).click();
    await expect(page.getByRole('heading', { name: 'Si el 9 se queda por dentro' })).toBeVisible({ timeout: 8000 });
    await expect(page.locator('.map-chip', { hasText: 'Campo: si el 9 se queda por dentro' })).toBeVisible();
    await expect(page.locator('.decision-compare')).toContainText('3 de 32');
    expect(errors).toEqual([]);
  });
});
