// Draws the installable app's icons from the logo (PRD 4.3: installable as a PWA). Run once after a logo change:
// node scripts/make-icons.mjs   (writes public/icons/)
import { mkdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright-core';

const out = fileURLToPath(new URL('../public/icons/', import.meta.url));
mkdirSync(out, { recursive: true });

// The mark from public/favicon.svg: a pitch with the space ring.
const mark = `<rect x="3" y="7" width="24" height="16" rx="3" fill="none" stroke="#ecf1ec" stroke-width="1.8"/><line x1="15" y1="7" x2="15" y2="23" stroke="#ecf1ec" stroke-width="1.8"/><circle cx="20.5" cy="13.5" r="3.4" fill="none" stroke="#d7f25c" stroke-width="2"/>`;
// Regular icons keep the rounded tile; maskable ones fill the square and keep the mark inside the 80% safe circle.
const regular = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 30 30"><rect width="30" height="30" rx="6" fill="#0b1110"/>${mark}</svg>`;
const maskable = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 30 30"><rect width="30" height="30" fill="#0b1110"/><g transform="translate(15 15) scale(0.66) translate(-15 -15)">${mark}</g></svg>`;

const ICONS = [
  { file: 'icon-192.png', size: 192, svg: regular },
  { file: 'icon-512.png', size: 512, svg: regular },
  { file: 'maskable-512.png', size: 512, svg: maskable },
  { file: 'apple-touch-icon.png', size: 180, svg: maskable },
];

const browser = await chromium.launch({ channel: process.env.PW_CHANNEL === 'bundled' ? undefined : 'chrome', headless: true });
const page = await browser.newPage({ deviceScaleFactor: 1 });
for (const icon of ICONS) {
  await page.setViewportSize({ width: icon.size, height: icon.size });
  await page.setContent(`<style>html,body{margin:0;background:transparent}svg{display:block;width:${icon.size}px;height:${icon.size}px}</style>${icon.svg}`);
  await page.screenshot({ path: `${out}${icon.file}`, omitBackground: true, clip: { x: 0, y: 0, width: icon.size, height: icon.size } });
  console.log(`public/icons/${icon.file}`);
}
await browser.close();
