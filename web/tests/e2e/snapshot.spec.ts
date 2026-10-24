// Snapshots of the pitch (PRD 16.8): PNG in every tier, SVG in 2D with its shapes and words as vectors, the
// side-by-side what-if as one picture, and the label on every one.
import { readFileSync } from 'node:fs';
import { expect, pitchAtRest, test, type Page } from '../helpers';

const LABEL = 'OffBall · synthetic data · AI-generated';

/** A PNG's size, from its header. */
const pngSize = (bytes: Buffer) => ({ width: bytes.readUInt32BE(16), height: bytes.readUInt32BE(20) });

async function save(page: Page, button: RegExp): Promise<{ name: string; bytes: Buffer }> {
  const [dl] = await Promise.all([page.waitForEvent('download'), page.getByRole('button', { name: button }).click()]);
  return { name: dl.suggestedFilename(), bytes: readFileSync(await dl.path()) };
}

/** How many distinct colours a PNG has in its top four-fifths (the picture, not the footer), sampled. */
function colours(page: Page, png: Buffer): Promise<number> {
  return page.evaluate(async (b64) => {
    const img = new Image();
    img.src = `data:image/png;base64,${b64}`;
    await img.decode();
    const c = document.createElement('canvas');
    c.width = img.width;
    c.height = img.height;
    const ctx = c.getContext('2d')!;
    ctx.drawImage(img, 0, 0);
    const d = ctx.getImageData(0, 0, c.width, Math.floor(c.height * 0.8)).data;
    const seen = new Set<number>();
    for (let i = 0; i < d.length; i += 4 * 97) seen.add(((d[i] >> 4) << 8) | ((d[i + 1] >> 4) << 4) | (d[i + 2] >> 4));
    return seen.size;
  }, png.toString('base64'));
}

test.describe('snapshots of the 2D pitch', () => {
  test.use({ prefs: { mode: 'analyst' } });

  test('PNG: the picture about 1920 pixels across, with the label', async ({ page, errors }) => {
    await page.goto('/#/match?t=5.2');
    await pitchAtRest(page);
    const png = await save(page, /^Snapshot/);
    expect(png.name).toBe('offball-snapshot-63-05.png');
    const size = pngSize(png.bytes);
    expect(size.width).toBeGreaterThanOrEqual(1800);
    expect(size.width).toBeLessThanOrEqual(3840);
    expect(await colours(page, png.bytes)).toBeGreaterThan(40);
    await expect(page.locator('.live-region')).toHaveText('Snapshot saved as PNG.', { timeout: 8000 });
    expect(errors).toEqual([]);
  });

  test('SVG: shapes and words stay vectors; only the control field is pixels', async ({ page }) => {
    await page.goto('/#/match?t=5.2');
    await pitchAtRest(page);
    const { name, bytes } = await save(page, /^SVG/);
    expect(name).toBe('offball-snapshot-63-05.svg');
    const svg = bytes.toString('utf8');
    const parsed = await page.evaluate((s) => {
      const doc = new DOMParser().parseFromString(s, 'image/svg+xml');
      return { error: !!doc.querySelector('parsererror'), texts: [...doc.querySelectorAll('text')].map((t) => t.textContent), images: doc.querySelectorAll('image').length, paths: doc.querySelectorAll('path').length };
    }, svg);
    expect(parsed.error).toBe(false);
    expect(parsed.images).toBe(1);
    expect(parsed.paths).toBeGreaterThan(30);
    // Every shirt number and every label on the pitch is text, and so is the export label.
    for (let n = 1; n <= 11; n++) expect(parsed.texts.filter((t) => t === String(n)).length).toBe(2);
    expect(parsed.texts).toContain('No. 9 Velmar');
    expect(parsed.texts.some((t) => t?.startsWith('Gap zone · +'))).toBe(true);
    expect(parsed.texts.some((t) => t?.startsWith(`${LABEL} · 63:05 · Analyst`))).toBe(true);
  });

  test('S saves a PNG snapshot', async ({ page }) => {
    await page.goto('/#/match?t=2');
    await pitchAtRest(page);
    const [dl] = await Promise.all([page.waitForEvent('download'), page.keyboard.press('s')]);
    expect(dl.suggestedFilename()).toMatch(/^offball-snapshot-63-02\.png$/);
  });
});

test.describe('the side-by-side what-if', () => {
  test.use({ prefs: { cfView: 'split' } });

  test('is one picture with both sides, titled', async ({ page }) => {
    await page.goto('/#/match?t=5.2');
    await page.keyboard.press('w');
    await expect(page.locator('.split .pitch-card')).toHaveCount(2);
    await expect(page.locator('.split .pitch-stage[data-resting="true"]')).toHaveCount(2, { timeout: 10_000 });
    const { bytes } = await save(page, /^SVG/);
    const svg = bytes.toString('utf8');
    expect(svg).toContain('>What happened</text>');
    expect(svg).toContain('>Without No. 9’s run</text>');
    expect(svg).toContain('>Gap stays shut</text>');
    const png = pngSize((await save(page, /^Snapshot/)).bytes);
    expect(png.width / png.height).toBeGreaterThan(2);
  });
});

test.describe('a snapshot of the 3D view', () => {
  test.use({ prefs: { view: 'broadcast', tier: 'B' } });

  test('is the scene as drawn, with its labels, and PNG only', async ({ page, errors }) => {
    await page.goto('/#/match?t=5.2');
    await pitchAtRest(page);
    await expect(page.getByRole('button', { name: /^SVG/ })).toHaveCount(0);
    const png = await save(page, /^Snapshot/);
    expect(pngSize(png.bytes).width).toBeGreaterThanOrEqual(1800);
    // A blank or cleared canvas would be a colour or two; the stadium, pitch and players are many.
    expect(await colours(page, png.bytes)).toBeGreaterThan(60);
    expect(errors).toEqual([]);
  });
});
