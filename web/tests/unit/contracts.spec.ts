// Every message the showcase feed sends must match its contract in ../contracts (PRD 15.7, 12.8): renderers read
// these messages, so a drift here is a drift for every partner too.
import { expect, test } from '@playwright/test';
import Ajv2020 from 'ajv/dist/2020.js';
import { readFileSync } from 'node:fs';
import { showcaseFeed, showcaseJsonl } from '../../src/lib/feed/emitter';
import type { ClientMessage, Overlay } from '../../src/lib/feed/types';
import { PLAYERS } from '../../src/lib/match';
import { LANG_IDS, MODE_IDS } from '../../src/lib/prefs';

const schema = (name: string) => JSON.parse(readFileSync(new URL(`../../../contracts/${name}.schema.json`, import.meta.url), 'utf8'));
const ajv = new Ajv2020({ allErrors: true, strict: false });
const validate = {
  'overlay.upsert': ajv.compile(schema('overlay-upsert')),
  'overlay.retract': ajv.compile(schema('overlay-retract')),
  'clock.sync': ajv.compile(schema('clock-sync')),
  'match.status': ajv.compile(schema('match-status')),
  frame: ajv.compile(schema('tracked-frame')),
};

const feed = showcaseFeed();
const overlays: Overlay[] = feed.overlays;

test('every message matches its contract', () => {
  const failures: string[] = [];
  for (const { msg } of feed.timeline) {
    const check = validate[msg.type];
    const ok = check(msg.type === 'frame' ? msg.frame : msg);
    if (!ok) failures.push(`${msg.type}: ${ajv.errorsText(check.errors)}`);
  }
  expect(failures.slice(0, 5)).toEqual([]);
  expect(feed.timeline.length).toBeGreaterThan(200);
});

test('the committed JSONL feed is the emitter’s output (npm run feed:export refreshes it)', () => {
  const committed = readFileSync(new URL('../../public/feeds/showcase.jsonl', import.meta.url), 'utf8');
  expect(committed).toBe(`${showcaseJsonl()}
`);
});

test('the JSONL replay is the same feed, one message per line', () => {
  const lines = showcaseJsonl().split('\n');
  expect(lines).toHaveLength(feed.timeline.length);
  const parsed = lines.map((l) => JSON.parse(l) as ClientMessage);
  expect(parsed).toEqual(feed.timeline.map((m) => m.msg));
});

test('frames run at 25 Hz in order, with every player on the pitch', () => {
  const frames = feed.frames;
  const problems: string[] = [];
  frames.forEach((f, i) => {
    const prev = frames[i - 1];
    if (prev && f.frame_id !== prev.frame_id + 1) problems.push(`frame ${f.frame_id} follows ${prev.frame_id}`);
    if (prev && Math.abs(f.t_ms - prev.t_ms - 40) > 0.5) problems.push(`frame ${f.frame_id} is ${f.t_ms - prev.t_ms} ms after the last`);
    if (Object.keys(f.players).length !== PLAYERS.length) problems.push(`frame ${f.frame_id} has ${Object.keys(f.players).length} players`);
    for (const [id, [x, y]] of Object.entries(f.players)) if (x < 0 || x > 105 || y < 0 || y > 68) problems.push(`${id} off the pitch in frame ${f.frame_id}`);
    if (f.ball[2] < 0) problems.push(`ball underground in frame ${f.frame_id}`);
  });
  expect(problems.slice(0, 5)).toEqual([]);
  expect(frames.length).toBeGreaterThan(200);
});

test('overlay IDs, revisions, timing and evidence follow the conventions', () => {
  const seen = new Set<string>();
  for (const o of overlays) {
    expect(o.overlay_id).toMatch(/^m07-o\d{4}$/);
    expect(seen.has(`${o.overlay_id}:${o.rev}`)).toBe(false);
    seen.add(`${o.overlay_id}:${o.rev}`);
    expect(o.t_end_ms).toBeGreaterThan(o.t_start_ms);
    // Frames, events and counterfactual runs (PRD 12.8).
    for (const e of o.evidence_ids) expect(e).toMatch(/^m07-(f\d-\d+|e\d{4}|c\d{4})$/);
    if (o.counterfactual_id) expect(o.counterfactual_id).toMatch(/^m07-c\d{4}$/);
  }
});

test('every graphic with words has them in all ten languages, with accessible text', () => {
  const missing: string[] = [];
  for (const o of overlays) {
    if (!o.text.en) continue;
    for (const lang of LANG_IDS) {
      if (!o.text[lang]?.trim()) missing.push(`${o.overlay_id} text.${lang}`);
      if (!o.a11y_text[lang]?.trim()) missing.push(`${o.overlay_id} a11y_text.${lang}`);
    }
  }
  expect(missing.slice(0, 8)).toEqual([]);
});

test('every mode has captions, and every caption cites its evidence and says it is AI-generated', () => {
  for (const mode of MODE_IDS) {
    const captions = overlays.filter((o) => o.mode === mode && o.kind === 'caption');
    expect(captions.length, mode).toBeGreaterThan(0);
    for (const c of captions) {
      expect(c.evidence_ids.length, c.overlay_id).toBeGreaterThan(0);
      expect(c.ai_generated, c.overlay_id).toBe(true);
    }
  }
});

test('the score follows the status messages: 0–0, then 1–0 at the goal', () => {
  const statuses = feed.timeline.flatMap(({ msg }) => (msg.type === 'match.status' ? [msg] : []));
  expect(statuses.map((s) => `${s.score.kes}-${s.score.ash}`)).toEqual(['0-0', '1-0']);
});
