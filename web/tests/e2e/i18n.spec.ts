// Captions in every language and mode come from the language's pack, not English (PRD 15.3).
import { expect, test } from '../helpers';

const LANGS = ['es', 'pt', 'fr', 'ar', 'hi', 'id', 'zh', 'ja', 'sw'] as const;
const MODES = ['casual', 'learn', 'analyst', 'player', 'audio'] as const;
/** Common English words that never appear in a translated caption (names and IDs aside). */
const ENGLISH = /\b(the|and|is|run)\b/i;

for (const lang of LANGS) {
  test(`captions in ${lang} for every mode`, async ({ browser }) => {
    // Five fresh match views in turn: more than the default 30 s when the whole suite runs in parallel.
    test.slow();
    const untranslated: string[] = [];
    for (const mode of MODES) {
      const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
      await context.addInitScript((p) => localStorage.setItem('offball.prefs', JSON.stringify(p)), { onboarded: true, lang, mode });
      const page = await context.newPage();
      await page.goto('/#/match?t=1.5');
      const caption = page.locator('.caption-line');
      await expect(caption).not.toHaveText(/^\s*$/);
      const text = (await caption.textContent()) ?? '';
      // Indonesian borrows some English football words, so it is only checked for being present.
      if (lang !== 'id' && ENGLISH.test(text.replace(/Kestrel Bay|Ashmoor/g, ''))) untranslated.push(`${mode}: ${text.slice(0, 50)}`);
      await context.close();
    }
    expect(untranslated).toEqual([]);
  });
}
