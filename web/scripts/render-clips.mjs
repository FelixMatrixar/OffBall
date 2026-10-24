// Renders the pre-rendered clips (PRD 16.2 tier D, 16.8 share clips) from the real renderer: the #/clip route is
// stepped frame by frame at 30 fps in Chrome, and each frame is piped to ffmpeg. Every frame is exact, however long it
// takes to capture, because the clip route runs the scene, the camera and the labels' animations on its own timeline.
//
// Usage: npm run clips   (builds first; needs ffmpeg on PATH, or FFMPEG=/path/to/ffmpeg, and Google Chrome)
//        node scripts/render-clips.mjs share-vertical-safe   (just the named clips, from an existing build)
// Output: public/clips/<name>.mp4 and a poster <name>.jpg for each clip below.
import { spawn } from 'node:child_process';
import { mkdirSync, statSync, writeFileSync } from 'node:fs';
import { createServer } from 'node:net';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright-core';

const root = fileURLToPath(new URL('..', import.meta.url));
const out = fileURLToPath(new URL('../public/clips/', import.meta.url));
const FPS = 30;
/** Where the posters are taken: the gap open, the pass on its way. */
const POSTER_T = 4.6;

const CLIPS = [
  // Tier D: one clip per family of modes, overlays burned in; captions stay live DOM text in the viewer's language.
  { name: 'showcase-casual', mode: 'casual', view: 'broadcast', w: 1280, h: 720 },
  { name: 'showcase-analyst', mode: 'analyst', view: 'broadcast', w: 1280, h: 720 },
  { name: 'showcase-broadcaster', mode: 'broadcaster', view: 'broadcast', w: 1280, h: 720 },
  // The vertical share clip, with the caption burned in and the synthetic-data label: laid out at phone size and
  // drawn at 2x, so text reads as it would on a phone.
  { name: 'share-vertical', mode: 'casual', view: 'broadcast', w: 540, h: 960, scale: 2, captions: true },
  // The spoiler-safe cut stops before the finish: the run, the gap and the pass, but not the shot.
  { name: 'share-vertical-safe', mode: 'casual', view: 'broadcast', w: 540, h: 960, scale: 2, captions: true, until: 6.2 },
];

const PREFS = { theme: 'dark', reducedMotion: false, lang: 'en', club: 'kes', fav: 'kes-09', metric: 'space', density: 'standard', voice: false, sonify: false, capSize: 20, tier: 'B', view: 'broadcast', cfView: 'overlay', layout: 'auto', onboarded: true };

const freePort = () =>
  new Promise((resolve) => {
    const s = createServer();
    s.listen(0, () => {
      const { port } = s.address();
      s.close(() => resolve(port));
    });
  });

async function serve() {
  if (process.env.CLIPS_URL) return { base: process.env.CLIPS_URL, stop: () => {} };
  const port = await freePort();
  // Node runs Vite directly, without a shell, so stopping it stops the server too.
  const vite = fileURLToPath(new URL('../node_modules/vite/bin/vite.js', import.meta.url));
  const proc = spawn(process.execPath, [vite, 'preview', '--port', String(port), '--strictPort'], { cwd: root, stdio: ['ignore', 'pipe', 'inherit'] });
  await new Promise((resolve, reject) => {
    proc.stdout.on('data', (d) => String(d).includes(String(port)) && resolve());
    proc.on('exit', (code) => reject(new Error(`vite preview exited with ${code}`)));
  });
  return { base: `http://localhost:${port}`, stop: () => proc.kill() };
}

function encoder(file, crf) {
  const ff = spawn(process.env.FFMPEG ?? 'ffmpeg', ['-y', '-loglevel', 'error', '-f', 'image2pipe', '-framerate', String(FPS), '-i', '-', '-c:v', 'libx264', '-preset', 'slow', '-crf', String(crf), '-pix_fmt', 'yuv420p', '-movflags', '+faststart', file], { stdio: ['pipe', 'inherit', 'inherit'] });
  const done = new Promise((resolve, reject) => ff.on('exit', (code) => (code === 0 ? resolve() : reject(new Error(`ffmpeg exited with ${code}`)))));
  const write = (buf) => new Promise((resolve) => (ff.stdin.write(buf) ? resolve() : ff.stdin.once('drain', resolve)));
  return { write, end: () => (ff.stdin.end(), done) };
}

mkdirSync(out, { recursive: true });
const server = await serve();
const browser = await chromium.launch({ channel: process.env.PW_CHANNEL === 'bundled' ? undefined : 'chrome', headless: true });
try {
  const only = process.argv.slice(2);
  for (const clip of only.length ? CLIPS.filter((c) => only.includes(c.name)) : CLIPS) {
    const started = Date.now();
    const context = await browser.newContext({ viewport: { width: clip.w, height: clip.h }, deviceScaleFactor: clip.scale ?? 1 });
    await context.addInitScript((p) => localStorage.setItem('offball.prefs', JSON.stringify(p)), { ...PREFS, mode: clip.mode });
    const page = await context.newPage();
    page.on('pageerror', (e) => console.error(`  page error: ${e}`));
    await page.goto(`${server.base}/#/clip?view=${clip.view}&w=${clip.w}&h=${clip.h}${clip.captions ? '&captions=1' : ''}`);
    await page.evaluate(() => document.fonts.ready);
    await page.waitForFunction(() => window.__offballClip?.ready());
    await page.evaluate(() => window.__offballClip.seek(0));
    const duration = clip.until ?? (await page.evaluate(() => window.__offballClip.duration));
    const frames = Math.round(duration * FPS);
    const ff = encoder(`${out}${clip.name}.mp4`, clip.h > clip.w ? 24 : 23);
    // Screenshots come out at the device scale, so a 540 × 960 layout at 2x is a 1080 × 1920 video.
    for (let i = 0; i < frames; i++) {
      await page.evaluate((t) => window.__offballClip.seek(t), i / FPS);
      await ff.write(await page.screenshot({ type: 'png', clip: { x: 0, y: 0, width: clip.w, height: clip.h } }));
    }
    await ff.end();
    await page.evaluate((t) => window.__offballClip.seek(t), Math.min(POSTER_T, duration - 0.2));
    writeFileSync(`${out}${clip.name}.jpg`, await page.screenshot({ type: 'jpeg', quality: 82, clip: { x: 0, y: 0, width: clip.w, height: clip.h } }));
    const mb = (statSync(`${out}${clip.name}.mp4`).size / 1e6).toFixed(1);
    console.log(`${clip.name}: ${frames} frames, ${mb} MB, ${((Date.now() - started) / 1000).toFixed(0)} s`);
    await context.close();
  }
} finally {
  await browser.close();
  server.stop();
}
