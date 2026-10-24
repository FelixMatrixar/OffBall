// Exports the showcase feed as JSONL (PRD 15.7): one contract message per line, in the order a live feed sends them,
// the format partners load and replay. The emitter is TypeScript, so esbuild bundles it for Node first.
//
// Usage: npm run feed:export   (writes public/feeds/showcase.jsonl)
import { build } from 'esbuild';
import { mkdirSync, writeFileSync } from 'node:fs';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = fileURLToPath(new URL('..', import.meta.url));
const bundle = fileURLToPath(new URL('../node_modules/.cache/offball/emitter.mjs', import.meta.url));
await build({
  entryPoints: [`${root}src/lib/feed/emitter.ts`],
  bundle: true,
  format: 'esm',
  platform: 'node',
  jsx: 'automatic',
  outfile: bundle,
  logLevel: 'error',
});
const { showcaseJsonl, showcaseFeed } = await import(pathToFileURL(bundle).href);
const out = fileURLToPath(new URL('../public/feeds/', import.meta.url));
mkdirSync(out, { recursive: true });
const jsonl = `${showcaseJsonl()}\n`;
writeFileSync(`${out}showcase.jsonl`, jsonl);
const feed = showcaseFeed();
const kinds = feed.timeline.reduce((acc, { msg }) => ({ ...acc, [msg.type]: (acc[msg.type] ?? 0) + 1 }), {});
console.log(`public/feeds/showcase.jsonl: ${feed.timeline.length} messages (${Object.entries(kinds).map(([k, n]) => `${n} ${k}`).join(', ')}), ${(jsonl.length / 1024).toFixed(0)} KB`);
