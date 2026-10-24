// The showcase feed: turns the scripted moment into contract messages (frames, overlays, status and clock
// sync), as the interpret service and the broadcast crew would emit them. It stands in for the backend until
// the live services exist; every renderer reads these messages, never the script directly.
import { LANG_IDS, MODE_IDS, type Lang, type Mode } from '../prefs';
import { PACKS, STORY_PLAYERS, fill, fmtNum, type StoryPlayer } from '../i18n';
import { LABELS } from '../i18n/labels';
import {
  A5_START,
  BALL,
  BASE_MS,
  CF_ID,
  COUNTERFACTUAL,
  EVENT_PASS,
  EVENT_SHOT,
  FRAME_MS,
  GAP_CENTRE,
  MATCH_ID,
  PASS_FROM,
  PASS_TO,
  PERIOD,
  PLAYERS,
  RUN_FROM,
  RUN_TO,
  STEP_TIMES,
  T_END,
  T_GOAL,
  at,
  backLineX,
  ballZ,
  distance,
  frameRef,
  player,
  type XY,
} from '../match';
import { LAYER_OF, SCHEMA_VERSION, type Approval, type ClientMessage, type MatchStatus, type Overlay, type OverlayKind, type Speech, type TrackedFrame } from './types';

/** The picture holds on the goal for a moment before the replay loops. */
export const HOLD = 2.5;
export const T_LOOP = T_END + HOLD;

export const ms = (t: number) => BASE_MS + Math.round(t * 1000);
export const tOf = (t_ms: number) => (t_ms - BASE_MS) / 1000;
const iso = (t: number) => new Date(Date.UTC(2026, 9, 24, 15, 0) + ms(t)).toISOString();

// ---------- Frames ----------

function positionsAt(t: number): Record<string, XY> {
  const pos: Record<string, XY> = {};
  for (const pl of PLAYERS) pos[pl.id] = at(pl.keys, t);
  return pos;
}

export function buildFrames(): TrackedFrame[] {
  const frames: TrackedFrame[] = [];
  const n = Math.round(T_END * 1000 / FRAME_MS);
  for (let i = 0; i <= n; i++) {
    const t = (i * FRAME_MS) / 1000;
    const pos = positionsAt(t);
    const prev = positionsAt(Math.max(0, t - 0.1));
    const players: TrackedFrame['players'] = {};
    for (const pl of PLAYERS) {
      const [x, y] = pos[pl.id];
      const dx = x - prev[pl.id][0];
      const dy = y - prev[pl.id][1];
      const facing = Math.hypot(dx, dy) > 0.01 ? Math.atan2(dy, dx) : pl.team === 'kes' ? 0 : Math.PI;
      players[pl.id] = [round(x), round(y), round(facing)];
    }
    const [bx, by] = at(BALL, t, false);
    frames.push({ period: PERIOD, frame_id: Math.round(ms(t) / FRAME_MS), t_ms: ms(t), ball: [round(bx), round(by), round(ballZ(t))], players });
  }
  return frames;
}

const round = (v: number) => Math.round(v * 1000) / 1000;

// ---------- Overlays ----------

let counter = 40;
const nextId = () => `${MATCH_ID}-o${String(++counter).padStart(4, '0')}`;

const perLang = (f: (lang: Lang) => string): Record<string, string> => Object.fromEntries(LANG_IDS.map((l) => [l, f(l)]));

const escapeXml = (s: string) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

/** Speech markup per locale, for the Persona's voice lines (PRD 15.3). pan places an audio cue (PRD 10.5). */
function speechFor(id: string, text: Record<string, string>, pan: number | null = null): Record<string, Speech> {
  return Object.fromEntries(
    Object.entries(text).map(([lang, line]) => [
      lang,
      { ssml_ref: `${id}.${lang}.ssml`, voice: 'narrator-1', ssml: `<speak version="1.0" xml:lang="${lang}">${escapeXml(line)}</speak>`, pan },
    ]),
  );
}

interface Spec {
  kind: OverlayKind;
  mode: Mode;
  t0: number;
  t1: number;
  priority?: number;
  anchors?: Overlay['anchors'];
  text?: Record<string, string>;
  a11y?: Record<string, string>;
  speech?: boolean | number;
  data?: Record<string, unknown>;
  evidence?: string[];
  confidence?: number;
  approval?: Approval;
  cf?: boolean;
}

function overlay(s: Spec): Overlay {
  const id = nextId();
  const text = s.text ?? {};
  return {
    schema_version: SCHEMA_VERSION,
    overlay_id: id,
    rev: 1,
    match_id: MATCH_ID,
    period: PERIOD,
    t_start_ms: ms(s.t0),
    t_end_ms: ms(s.t1),
    kind: s.kind,
    layer: LAYER_OF[s.kind],
    priority: s.priority ?? 2,
    mode: s.mode,
    anchors: s.anchors ?? {},
    text,
    speech: s.speech === undefined || s.speech === false ? {} : speechFor(id, text, typeof s.speech === 'number' ? s.speech : null),
    a11y_text: s.a11y ?? text,
    chart: null,
    data: s.data ?? null,
    evidence_ids: s.evidence ?? [],
    confidence: s.confidence ?? 0.95,
    approval: s.approval ?? 'auto',
    counterfactual_id: s.cf ? CF_ID : null,
    detected_moment_id: `${MATCH_ID}-d0031`,
    ai_generated: true,
    labels: ['synthetic-data', 'ai-generated'],
  };
}

const STEP_EVIDENCE: string[][] = [[frameRef(0)], [frameRef(1)], [frameRef(2.5)], [frameRef(3.8)], [EVENT_PASS, frameRef(4.2)], [EVENT_SHOT, frameRef(T_GOAL)]];
const stepEnd = (i: number) => (i < STEP_TIMES.length - 1 ? STEP_TIMES[i + 1] : T_LOOP);
const panAt = (x: number) => Math.max(-1, Math.min(1, (x - 52.5) / 52.5));
const surname = (id: string) => player(id).name.split(' ').slice(-1)[0];
const label = (lang: Lang, key: keyof (typeof LABELS)['en'], vars: Record<string, string | number> = {}) => fill(LABELS[lang][key], vars);

function speedAt(id: string, t: number): number {
  const keys = player(id).keys;
  const [x1, y1] = at(keys, t);
  const [x0, y0] = at(keys, Math.max(0, t - 0.2));
  return t < 0.2 ? 0 : (Math.hypot(x1 - x0, y1 - y0) / 0.2) * 3.6;
}

/** When a player first crosses the sprint threshold (25.2 km/h, PRD 9.2), and when they drop below it. */
function sprintWindow(id: string): [number, number] | null {
  let start = -1;
  for (let t = 0; t <= T_END; t += 0.05) {
    const fast = speedAt(id, t) > 25.2;
    if (fast && start < 0) start = t;
    if (!fast && start >= 0) return [start, Math.max(t, start + 2.5)];
  }
  return start >= 0 ? [start, T_END] : null;
}

function metresCovered(id: string, t0: number, t1: number): number {
  let d = 0;
  let prev = at(player(id).keys, t0);
  for (let t = t0 + 0.1; t <= t1; t += 0.1) {
    const p = at(player(id).keys, t);
    d += distance(prev, p);
    prev = p;
  }
  return d;
}

/** Player focus lines for players without a scripted story, from the tracking at each beat. */
function genericLines(id: string, lang: Lang): string[] {
  const pl = player(id);
  const g = PACKS[lang].generic;
  const num = (n: number, d = 0) => fmtNum(lang, n, d);
  return STEP_TIMES.map((t, i) => {
    if (i === 0) return fill(g.follow, { num: pl.num, name: pl.name });
    if (i === 5) return fill(g.goal, { num: pl.num, metres: num(metresCovered(id, 0, T_GOAL)) });
    const speed = speedAt(id, t + 0.3);
    const dist = distance(at(pl.keys, t), at(BALL, t, false));
    return fill(speed > 7 ? g.moving : g.holding, { num: pl.num, speed: num(speed, 1), dist: num(dist) });
  });
}

function captions(mode: Mode, line: (lang: Lang, step: number) => string, extra: Partial<Spec> = {}): Overlay[] {
  return STEP_TIMES.map((t0, i) => {
    const text = perLang((l) => line(l, i));
    const pan = mode === 'audio' ? panAt(i >= 3 ? GAP_CENTRE[0] : at(BALL, t0, false)[0]) : undefined;
    return overlay({ kind: 'caption', mode, t0, t1: stepEnd(i), priority: 0, text, speech: pan ?? true, evidence: STEP_EVIDENCE[i], ...extra });
  });
}

function pitchSet(mode: Mode): Overlay[] {
  const out: Overlay[] = [];
  const casualLike = mode === 'casual' || mode === 'learn' || mode === 'audio';
  const named = mode === 'analyst';
  const run = (t1: number) =>
    overlay({
      kind: 'run_arrow',
      mode,
      t0: 0.8,
      t1,
      priority: 1,
      anchors: { player_id: 'kes-09', from_xy: RUN_FROM, to_xy: RUN_TO },
      data: { lead_s: 0.8 },
      a11y: perLang((l) => PACKS[l].casual[1]),
      evidence: [frameRef(1), frameRef(4.6)],
      confidence: 0.91,
    });
  const ring = (t1: number, withPass: boolean) =>
    overlay({
      kind: 'gap_ring',
      mode,
      t0: 3.8,
      t1,
      priority: 0,
      anchors: { centre_xy: GAP_CENTRE, radius_m: 6 },
      text: perLang((l) => (named ? label(l, 'gapZone') : label(l, 'spaceOpens'))),
      a11y: perLang((l) => PACKS[l].casual[3]),
      // In the audio-described mode the ring carries a stereo cue placed where space is opening.
      speech: mode === 'audio' ? panAt(GAP_CENTRE[0]) : false,
      data: { rx_m: 5.4, ry_m: 6.8, with_pass: withPass, ...(named ? { live: 'gap_zone' } : {}) },
      evidence: [frameRef(3.8)],
      confidence: 0.88,
    });
  const tag = (id: string, t0: number, t1: number, text: Record<string, string>, extra: Partial<Spec> = {}) =>
    overlay({ kind: 'player_tag', mode, t0, t1, priority: 3, anchors: { player_id: id }, text, confidence: 0.89, evidence: [frameRef(t0)], ...extra });

  if (casualLike) {
    // One pitch overlay at a time, each held at least 2.5 s (PRD 15.2): the run with the runner's tag, then the gap and
    // the pass into it. The defender following and the scorer are told by the captions, not more tags on the pitch, so
    // nothing shares the ring's moment.
    out.push(run(3.8), ring(7.4, true));
    out.push(tag('kes-09', 0.8, 3.3, perLang((l) => (mode === 'learn' ? label(l, 'decoy', { num: 9 }) : label(l, 'no', { num: 9 })))));
  } else if (mode === 'analyst') {
    out.push(run(6.4), ring(7.5, false));
    out.push(
      overlay({
        kind: 'run_arrow',
        mode,
        t0: 1.5,
        t1: T_LOOP,
        priority: 2,
        anchors: { player_id: 'ash-05', from_xy: A5_START },
        data: { style: 'displacement', live: 'displacement' },
        a11y: perLang((l) => PACKS[l].casual[2]),
        evidence: [frameRef(2.5), frameRef(4.6)],
        confidence: 0.9,
      }),
      overlay({
        kind: 'pass_line',
        mode,
        t0: 4.2,
        t1: 6.7,
        priority: 1,
        anchors: { from_xy: PASS_FROM, to_xy: PASS_TO, player_ids: ['kes-08', 'kes-10'] },
        data: { difficulty: 6.1, distance_m: 28 },
        a11y: perLang((l) => PACKS[l].analyst[4]),
        evidence: [EVENT_PASS],
        confidence: 0.93,
      }),
      overlay({
        kind: 'offside_line',
        mode,
        t0: 0,
        t1: T_LOOP,
        priority: 3,
        text: perLang((l) => label(l, 'line')),
        data: { live: 'back_line', team: 'ash' },
        a11y: perLang((l) => label(l, 'line')),
        evidence: [frameRef(0)],
        confidence: 0.97,
      }),
    );
    out.push(tag('kes-09', 0.8, 6.4, perLang((l) => label(l, 'named', { num: 9, name: surname('kes-09') }))));
    out.push(tag('ash-05', 2.5, 6.4, perLang((l) => label(l, 'named', { num: 5, name: surname('ash-05') }))));
    out.push(tag('kes-10', 4.2, 7.5, perLang((l) => label(l, 'named', { num: 10, name: surname('kes-10') }))));
  } else if (mode === 'player') {
    // The followed player and one key overlay (PRD 15.2 density by mode).
    out.push(run(3.8), ring(7.4, true));
  }

  // Sprint badges (PRD 9.2): analyst and player focus only, so casual viewers see no numbers they don't need.
  if (mode === 'analyst' || mode === 'player') {
    for (const pl of PLAYERS) {
      if (mode === 'analyst' && pl.id !== 'kes-09' && pl.id !== 'kes-10') continue;
      const w = sprintWindow(pl.id);
      if (!w) continue;
      out.push(
        overlay({
          kind: 'badge',
          mode,
          t0: w[0],
          t1: w[1],
          priority: 4,
          anchors: { player_id: pl.id },
          text: perLang((l) => label(l, 'sprint')),
          data: { live: 'speed', threshold_kmh: 25.2 },
          evidence: [frameRef(w[0])],
          confidence: 0.98,
        }),
      );
    }
  }
  return out;
}

/**
 * "What if they hadn't run?": ghosts, the gap that never opens, and the Tactician's result (PRD 10.2). Viewers see it
 * when they ask; on air it is a replay after the goal, so the broadcaster's copy starts at `from`.
 */
function counterfactualSet(mode: Mode, approval: Approval = 'auto', from = 0): Overlay[] {
  const ghost = (id: string, key: 'noRun' | 'stays', num: number) =>
    overlay({
      kind: 'ghost',
      mode,
      t0: from,
      t1: T_LOOP,
      priority: 1,
      anchors: { player_id: id, ghost_track_id: `${CF_ID}:${id}` },
      text: perLang((l) => label(l, key, { num })),
      data: { track: COUNTERFACTUAL[id], reruns: 32 },
      a11y: perLang((l) => PACKS[l].whatIf[0]),
      evidence: [CF_ID],
      confidence: 0.84,
      approval,
      cf: true,
    });
  return [
    ghost('kes-09', 'noRun', 9),
    ghost('ash-05', 'stays', 5),
    overlay({
      kind: 'gap_ring',
      mode,
      t0: Math.max(3.8, from),
      t1: T_LOOP,
      priority: 0,
      anchors: { centre_xy: GAP_CENTRE, radius_m: 6 },
      text: perLang((l) => label(l, 'gapShut')),
      data: { rx_m: 5.4, ry_m: 6.8, shut: true, shut_in: 29, reruns: 32 },
      a11y: perLang((l) => PACKS[l].whatIf[1]),
      evidence: [CF_ID],
      confidence: 0.84,
      approval,
      cf: true,
    }),
    ...[0, 1].map((i) =>
      overlay({
        kind: 'caption',
        mode,
        t0: from > 0 ? from + i * 2 : i === 0 ? 0 : 3.8,
        t1: from > 0 ? (i === 0 ? from + 2 : T_LOOP) : i === 0 ? 3.8 : T_LOOP,
        priority: 0,
        text: perLang((l) => PACKS[l].whatIf[i]),
        speech: true,
        evidence: [CF_ID],
        confidence: 0.86,
        approval,
        cf: true,
      }),
    ),
  ];
}

function backDepthAt(t: number): number {
  const pos: Record<string, XY> = {};
  for (const pl of PLAYERS) pos[pl.id] = at(pl.keys, t);
  return 105 - backLineX(pos);
}

export function buildOverlays(): Overlay[] {
  counter = 40;
  const out: Overlay[] = [];
  for (const mode of MODE_IDS) {
    if (mode === 'broadcaster') continue;
    out.push(...pitchSet(mode));
    if (mode === 'casual') out.push(...captions(mode, (l, i) => PACKS[l].casual[i]));
    if (mode === 'learn') out.push(...captions(mode, (l, i) => PACKS[l].learn[i]));
    if (mode === 'audio') out.push(...captions(mode, (l, i) => PACKS[l].audio[i]));
    if (mode === 'analyst') {
      const depth = backDepthAt(0);
      out.push(...captions(mode, (l, i) => fill(PACKS[l].analyst[i], { depth: fmtNum(l, depth, 1) })));
    }
    if (mode === 'player') {
      for (const pl of PLAYERS) {
        const story = (STORY_PLAYERS as readonly string[]).includes(pl.id);
        const lines = perLangLines((l) => (story ? [...PACKS[l].player[pl.id as StoryPlayer]] : genericLines(pl.id, l)));
        out.push(...captions(mode, (l, i) => lines[l][i], { anchors: { player_id: pl.id } }));
      }
    }
    out.push(...counterfactualSet(mode));
  }
  out.push(...broadcasterSet());
  return out;
}

const perLangLines = (f: (lang: Lang) => string[]): Record<string, string[]> => Object.fromEntries(LANG_IDS.map((l) => [l, f(l)]));

/** What the producer sees: auto graphics, one ring that needs approval, and the ghost replay (PRD 10.6). */
function broadcasterSet(): Overlay[] {
  const mode: Mode = 'broadcaster';
  const out = [
    overlay({ kind: 'run_arrow', mode, t0: 0.8, t1: 6.4, priority: 1, anchors: { player_id: 'kes-09', from_xy: RUN_FROM, to_xy: RUN_TO }, data: { lead_s: 0.8 }, a11y: perLang((l) => PACKS[l].casual[1]), evidence: [frameRef(1), frameRef(4.6)], confidence: 0.91 }),
    overlay({ kind: 'player_tag', mode, t0: 2.5, t1: 6.4, priority: 3, anchors: { player_id: 'ash-05' }, text: perLang((l) => label(l, 'follows', { num: 5 })), evidence: [frameRef(2.5)], confidence: 0.89 }),
    overlay({ kind: 'gap_ring', mode, t0: 3.8, t1: 7.5, priority: 0, anchors: { centre_xy: GAP_CENTRE, radius_m: 6 }, text: perLang((l) => label(l, 'spaceOpens')), a11y: perLang((l) => PACKS[l].casual[3]), data: { rx_m: 5.4, ry_m: 6.8 }, evidence: [frameRef(3.8)], confidence: 0.88, approval: 'pending' }),
    overlay({ kind: 'pass_line', mode, t0: 4.2, t1: 6.7, priority: 1, anchors: { from_xy: PASS_FROM, to_xy: PASS_TO, player_ids: ['kes-08', 'kes-10'] }, data: { difficulty: 6.1, distance_m: 28 }, a11y: perLang((l) => PACKS[l].analyst[4]), evidence: [EVENT_PASS], confidence: 0.93 }),
    overlay({ kind: 'stat_card', mode, t0: 4.6, t1: 8.2, priority: 2, anchors: { player_id: 'ash-05' }, text: perLang(() => 'DEFENDER PULLED'), data: { value: 10.8, unit: 'm', player: 'No. 5' }, evidence: [frameRef(2.5), frameRef(4.6)], confidence: 0.92 }),
    ...captions(mode, (l, i) => PACKS[l].casual[i], { confidence: 0.95 }),
    // The ghost replay airs after the goal and needs the producer's approval.
    ...counterfactualSet(mode, 'pending', 7),
  ];
  return out;
}

// ---------- The whole feed ----------

export interface Timed {
  /** Moment time, in seconds, at which the message is due on the wire. */
  at: number;
  msg: ClientMessage;
}

function status(t: number, score: [number, number]): MatchStatus {
  return { type: 'match.status', match_id: MATCH_ID, status: 'in_play', period: PERIOD, t_ms: ms(t), score: { kes: score[0], ash: score[1] }, sent_at: iso(t) };
}

let cache: { frames: TrackedFrame[]; overlays: Overlay[]; timeline: Timed[] } | null = null;

/** Every message of the showcase moment, in the order a live feed would send them. */
export function showcaseFeed() {
  if (cache) return cache;
  const frames = buildFrames();
  const overlays = buildOverlays();
  const timeline: Timed[] = [];
  for (const f of frames) timeline.push({ at: tOf(f.t_ms), msg: { type: 'frame', match_id: MATCH_ID, frame: f } });
  // Graphics leave the crew about half a second after the moment they describe; the viewer's 1.5 s buffer absorbs it.
  for (const o of overlays) timeline.push({ at: Math.max(0, tOf(o.t_start_ms) + 0.5), msg: { type: 'overlay.upsert', match_id: MATCH_ID, overlay: o, sent_at: iso(tOf(o.t_start_ms) + 0.5) } });
  // The server clock keeps ticking through the hold at the end, so a live viewer never mistakes it for a stall.
  for (let t = 0; t <= T_LOOP + 1; t++) timeline.push({ at: t, msg: { type: 'clock.sync', match_id: MATCH_ID, period: PERIOD, t_ms: ms(t), speed: 1, server_time: iso(t) } });
  timeline.push({ at: 0, msg: status(0, [0, 0]) }, { at: T_GOAL, msg: status(T_GOAL, [1, 0]) });
  timeline.sort((a, b) => a.at - b.at);
  cache = { frames, overlays, timeline };
  return cache;
}

/** The feed as JSONL, one message per line: the replay format partners load (PRD 15.7). */
export const showcaseJsonl = () => showcaseFeed().timeline.map((m) => JSON.stringify(m.msg)).join('\n');
