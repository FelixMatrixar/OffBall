// The match view: the pitch, its keyboard and pointer access, the drawer, shortcuts, layouts and system states.
import { expect, pitchAtRest, test } from '../helpers';

test.describe('a favourite Ashmoor player', () => {
  test.use({ prefs: { mode: 'player', club: 'ash', fav: 'ash-05' } });

  test('is followed on the pitch and in the panel, and the drawer keeps focus', async ({ page }) => {
    await page.goto('/#/match');
    await expect(page.locator('.player-target[aria-label$=", followed"]')).toHaveAttribute('aria-label', /^Ashmoor No\. 5/);
    await expect(page.locator('.match-panel .display').first()).toContainText(/Hendricx|5/);

    await page.getByRole('button', { name: 'Personalize' }).click();
    await expect(page.locator('#pz-fav')).toHaveValue('ash-05');
    // Tab never leaves the open drawer.
    for (let i = 0; i < 40; i++) {
      await page.keyboard.press('Tab');
      expect(await page.evaluate(() => !!document.activeElement?.closest('[role="dialog"]'))).toBe(true);
    }
    await page.keyboard.press('Escape');
    await expect(page.locator('[role="dialog"]')).toHaveCount(0);
  });
});

test.describe('the mode switcher', () => {
  test.use({ prefs: { reducedMotion: true } });
  for (const width of [1440, 768, 390]) {
    for (const mode of ['casual', 'analyst', 'broadcaster']) {
      test(`slides its pill under ${mode} at ${width}px`, async ({ page }) => {
        await page.setViewportSize({ width, height: 900 });
        await page.goto('/#/match');
        await page.evaluate((m) => {
          const p = JSON.parse(localStorage.getItem('offball.prefs') ?? '{}');
          localStorage.setItem('offball.prefs', JSON.stringify({ ...p, mode: m }));
        }, mode);
        await page.reload();
        await page.waitForTimeout(900);
        const cover = await page.evaluate(() => {
          const seg = document.querySelector('nav .seg')!;
          const ind = seg.querySelector('.seg-indicator')!.getBoundingClientRect();
          const btn = seg.querySelector('.seg-btn[aria-checked="true"]')!.getBoundingClientRect();
          return Math.round((Math.max(0, Math.min(ind.right, btn.right) - Math.max(ind.left, btn.left)) / btn.width) * 100);
        });
        expect(cover).toBeGreaterThanOrEqual(95);
      });
    }
  }
});

test('the goal burst plays once and leaves the picture at rest', async ({ page }) => {
  await page.goto('/#/match?t=8.5');
  await pitchAtRest(page);
});

test.describe('players', () => {
  test('are one tab stop; arrow keys move between them and focus names them', async ({ page }) => {
    await page.goto('/#/match?t=2');
    await expect(page.locator('.pitch [tabindex="0"]')).toHaveCount(1);
    await page.locator('.player-target[tabindex="0"]').first().focus();
    await page.keyboard.press('ArrowRight');
    await expect(page.locator(':focus')).toHaveAttribute('aria-label', /No\. 2/);
    // Down switches teams and keeps the shirt number.
    await page.keyboard.press('ArrowDown');
    await expect(page.locator(':focus')).toHaveAttribute('aria-label', /^Ashmoor No\. 2/);
    const hint = page.locator('.pitch-label[data-kind="hint"] .pitch-label-text');
    await expect(hint).toHaveText(/No\. 2/);
    await expect(hint).toHaveCSS('opacity', '1');
  });

  test('can be pointed at: a click focuses the player and shows the name', async ({ page }) => {
    await page.goto('/#/match?t=0');
    await pitchAtRest(page);
    // No. 1, Kestrel Bay's keeper, stands still at (6, 34) on a 105 x 68 m pitch.
    const box = (await page.locator('.pitch-stage').first().boundingBox())!;
    await page.mouse.click(box.x + ((60 + 30) / 1110) * box.width, box.y + ((340 + 30) / 740) * box.height);
    await expect(page.locator(':focus')).toHaveAttribute('aria-label', /^Kestrel Bay No\. 1,/);
    await expect(page.locator('.pitch-label[data-kind="hint"]')).toContainText('No. 1');
  });

  test('Enter follows the focused player', async ({ page }) => {
    await page.goto('/#/match?t=2');
    await page.locator('.player-target[tabindex="0"]').first().focus();
    await page.keyboard.press('End');
    await expect(page.locator(':focus')).toHaveAttribute('aria-label', /^Ashmoor No\. 11/);
    await page.keyboard.press('Enter');
    await expect(page.getByRole('radio', { name: /Player focus/ })).toHaveAttribute('aria-checked', 'true');
    await expect(page.locator('.player-target[aria-label$=", followed"]')).toHaveAttribute('aria-label', /^Ashmoor No\. 11/);
  });
});

test.describe('labels on a crowded pitch', () => {
  test.use({ prefs: { mode: 'analyst' } });
  test('never overlap each other', async ({ page }) => {
    await page.goto('/#/match?t=5.3');
    await pitchAtRest(page);
    const boxes = await page.locator('.pitch-label-text').evaluateAll((els) =>
      els.map((el) => {
        const r = el.getBoundingClientRect();
        return { text: el.textContent, x0: r.left, y0: r.top, x1: r.right, y1: r.bottom };
      }),
    );
    expect(boxes.length).toBeGreaterThan(2);
    const clashes: string[] = [];
    boxes.forEach((a, i) =>
      boxes.slice(i + 1).forEach((b) => {
        const w = Math.min(a.x1, b.x1) - Math.max(a.x0, b.x0);
        const h = Math.min(a.y1, b.y1) - Math.max(a.y0, b.y0);
        // A couple of pixels of halo may touch; text may not.
        if (w > 3 && h > 3) clashes.push(`${a.text} / ${b.text}`);
      }),
    );
    expect(clashes).toEqual([]);
  });
});

/** Labels covering a player other than their own by more than a few pixels of halo at the dot's rim. */
async function labelsOverPlayers(page: import('@playwright/test').Page) {
  return page.evaluate(() => {
    const dots = [...document.querySelectorAll<HTMLElement>('.player-target')].map((b) => {
      const r = b.getBoundingClientRect();
      // The target is 32 pitch units wide; the drawn dot's radius is 13.
      return { id: b.dataset.player, x: r.left + r.width / 2, y: r.top + r.height / 2, r: (r.width * 13) / 32 };
    });
    const over: string[] = [];
    for (const el of document.querySelectorAll<HTMLElement>('.pitch-label')) {
      const text = el.querySelector('.pitch-label-text');
      if (!text || el.style.visibility === 'hidden') continue;
      const b = text.getBoundingClientRect();
      for (const d of dots) {
        if (d.id === el.dataset.player) continue;
        const gap = Math.hypot(Math.max(b.left - d.x, 0, d.x - b.right), Math.max(b.top - d.y, 0, d.y - b.bottom)) - d.r;
        if (gap < -6) over.push(`${text.textContent} covers ${d.id} by ${Math.round(-gap)} px`);
      }
    }
    return over;
  });
}

test.describe('labels and players', () => {
  for (const [mode, t] of [
    ['casual', 4.5],
    ['analyst', 4.5],
    ['analyst', 5.3],
  ] as const) {
    test.describe(`${mode} at ${t} s`, () => {
      test.use({ prefs: { mode } });
      test('no label covers another player', async ({ page }) => {
        await page.goto(`/#/match?t=${t}`);
        await pitchAtRest(page);
        expect(await labelsOverPlayers(page)).toEqual([]);
      });
    });
  }
});

test.describe('Casual', () => {
  test('shows one pitch overlay at a time: only the ring is labelled while it shows', async ({ page }) => {
    await page.goto('/#/match?t=4.5');
    await pitchAtRest(page);
    const shown = await page.locator('.pitch-label').evaluateAll((els) => els.filter((el) => (el as HTMLElement).style.visibility !== 'hidden').map((el) => (el as HTMLElement).dataset.kind));
    expect(shown).toEqual(['gap_ring']);
  });
});

test('the scrubber steps a frame from the keyboard and its head follows', async ({ page }) => {
  await page.goto('/#/match?t=4');
  const head = page.locator('.scrub-head');
  const before = await head.evaluate((el) => el.style.transform);
  await page.locator('#match-scrub').focus();
  for (let i = 0; i < 10; i++) await page.keyboard.press('ArrowRight');
  await expect(page.locator('#match-scrub')).toHaveAttribute('aria-valuetext', /63:04\.4/);
  await expect.poll(() => head.evaluate((el) => el.style.transform)).not.toBe(before);
});

test.describe('Arabic', () => {
  test.use({ prefs: { lang: 'ar' } });
  test('reads right to left, mirrors the panel and keeps the pitch left to right', async ({ page }) => {
    await page.goto('/#/match');
    await expect(page.locator('html')).toHaveAttribute('dir', 'rtl');
    await expect(page.locator('html')).toHaveAttribute('lang', 'ar');
    await expect(page.locator('.pitch').first()).toHaveAttribute('dir', 'ltr');
    await expect(page.locator('.pitch-labels').first()).toHaveAttribute('dir', 'rtl');
    const mirrored = await page.evaluate(() => document.querySelector('aside')!.getBoundingClientRect().left < document.querySelector('.pitch')!.getBoundingClientRect().left);
    expect(mirrored).toBe(true);
    await expect(page.locator('.caption-line')).toHaveText(/[؀-ۿ]/);
  });
});

test('a feed stall holds and dims the picture, then reports what was missed', async ({ page }) => {
  test.slow();
  await page.goto('/#/match');
  await page.getByText('Demo controls').click();
  await page.getByRole('switch', { name: 'Feed stall' }).click();
  await expect(page.locator('.pitch-scrim')).toBeVisible({ timeout: 10_000 });
  await expect(page.locator('.toast')).toContainText('Back in sync', { timeout: 15_000 });
});

test.describe('a first visit', () => {
  test.use({ prefs: { onboarded: false } });
  test('goes to the first-run choices, and Skip lands on the match', async ({ page }) => {
    await page.goto('/#/match');
    await expect(page).toHaveURL(/#\/onboarding/);
    await page.getByRole('button', { name: 'Skip, use defaults' }).click();
    await expect(page).toHaveURL(/#\/match/);
  });
});

test('a phone in portrait gets a vertical pitch, a bottom sheet and no sideways scroll', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/#/match?t=4.5');
  await expect(page.locator('.pitch-v')).toHaveCount(1);
  await expect(page.locator('.sheet')).toHaveCount(1);
  expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(0);
});

test('shortcuts: K toggles play, ? lists the shortcuts', async ({ page }) => {
  await page.goto('/#/match');
  await page.waitForTimeout(1000);
  await page.locator('body').click({ position: { x: 5, y: 600 } });
  await page.keyboard.press('k');
  await expect(page.locator('.replay-controls .btn-solid')).toHaveAttribute('aria-label', 'Play');
  await page.keyboard.press('Shift+Slash');
  await expect(page.getByRole('dialog', { name: 'Keyboard shortcuts' })).toHaveCount(1);
});

test.describe('what if', () => {
  test.use({ prefs: { cfView: 'split' } });
  test('shows the two pitches side by side', async ({ page }) => {
    await page.goto('/#/match?t=5');
    await page.getByRole('switch', { name: 'What if no run?' }).click();
    await expect(page.locator('.split .pitch')).toHaveCount(2);
  });
});
