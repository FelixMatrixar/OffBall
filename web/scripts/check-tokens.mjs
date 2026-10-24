// Token lint (PRD 16.3, 16.10): every colour, duration and easing comes from src/styles/tokens.css.
// Flags colour literals, and durations or easing curves in animations and transitions, anywhere else in src/.
//
// Allowed without comment: a literal right after the token it falls back to on the same line, such as
// `token(el, '--text', '#ecf1ec')`. Elsewhere, mark a deliberate exception with `tokens-ok: <reason>` on the line,
// or `tokens-ok-file: <reason>` near the top of a file whose colours are data (kit colours, colour maths).
//
// Usage: node scripts/check-tokens.mjs   (exits 1 when it finds anything)
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('..', import.meta.url));
const src = join(root, 'src');
const TOKENS = join(src, 'styles', 'tokens.css');

const walk = (dir) => readdirSync(dir).flatMap((name) => {
  const path = join(dir, name);
  return statSync(path).isDirectory() ? walk(path) : [path];
});

const COLOUR = /(?<![\w&/])#[0-9a-fA-F]{3,8}\b|\b(?:rgba?|hsla?)\(\s*\d/g;
const TOKEN_NAME = /['"`]--[a-z0-9-]+['"`]/;
const DURATION = /(?<![\w.-])\d*\.?\d+m?s\b/;
const CSS_MOTION = /^\s*(?:transition|animation)[\w-]*\s*:/;
const TSX_MOTION = /\b(?:transition|animation\w*)\s*:\s*['"`]([^'"`]*)['"`]/g;

const problems = [];
for (const file of walk(src)) {
  if (!/\.(css|ts|tsx)$/.test(file) || file === TOKENS) continue;
  const text = readFileSync(file, 'utf8');
  if (/tokens-ok-file:/.test(text.slice(0, 600))) continue;
  const css = file.endsWith('.css');
  text.split('\n').forEach((line, i) => {
    if (/tokens-ok:/.test(line)) return;
    const where = `${relative(root, file).replaceAll('\\', '/')}:${i + 1}`;
    for (const m of line.matchAll(COLOUR)) {
      const before = line.slice(0, m.index);
      // A fallback for a token named earlier on the line is fine; any other literal isn't.
      if (TOKEN_NAME.test(before)) continue;
      // CSS: rgb(var(--x-rgb) / 0.5) is a token in use, and comments may name colours.
      if (css && (/\/\*/.test(before) || /var\(/.test(line.slice(m.index, m.index + 12)))) continue;
      problems.push(`${where}  colour literal ${m[0].replace(/\($/, '')}…  ${line.trim().slice(0, 90)}`);
    }
    if (css) {
      if (CSS_MOTION.test(line) && DURATION.test(line.replace(/var\([^)]*\)/g, ''))) problems.push(`${where}  duration literal  ${line.trim().slice(0, 90)}`);
      if (/cubic-bezier\(/.test(line) && !/\/\*/.test(line)) problems.push(`${where}  easing literal  ${line.trim().slice(0, 90)}`);
    } else {
      for (const m of line.matchAll(TSX_MOTION)) {
        if (DURATION.test(m[1].replace(/var\([^)]*\)/g, ''))) problems.push(`${where}  duration literal in a style  ${m[0].slice(0, 80)}`);
        if (/cubic-bezier\(/.test(m[1])) problems.push(`${where}  easing literal in a style  ${m[0].slice(0, 80)}`);
      }
    }
  });
}

if (problems.length) {
  console.error(`Token lint: ${problems.length} value(s) outside the tokens.\n`);
  for (const p of problems) console.error(`  ${p}`);
  console.error('\nUse a token from src/styles/tokens.css, or mark a deliberate exception with tokens-ok: <reason>.');
  process.exit(1);
}
console.log('Token lint: every colour, duration and easing comes from the tokens.');
