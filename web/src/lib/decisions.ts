// Change one decision (PRD 10.10, 15.12): the decisions a viewer can change in the showcase moment, the options each
// player had, and the Tactician's re-run of each. The options come from the observed state, ranked by modelled value,
// never from the generator's held-out decision log (PRD 12.9). In replay the results are precomputed, as here; live
// they come back from `run_counterfactual` within 15 s. Their words live in each language pack's `decide`; only the
// Analyst verdicts, with their numbers, are here, in English like the rest of the Analyst panel.
import type { Overlay } from './feed/types';
import type { DecisionChoice, DecisionOptionId, DecisionPointId } from './i18n/types';
import { GAP_CENTRE, MATCH_ID, PASS_FROM, PERIOD, BASE_MS, at, player, type Key, type XY } from './match';
import type { Mode } from './prefs';

export const RERUNS = 32;
/** The end of the replayed moment, in seconds, as the feed's loop. */
const T_STOP = 11.5;

/** What 32 re-runs of the moment gave, as played or with one decision changed. */
export interface Result {
  /** Re-runs, out of 32, in which the gap opened, a shot was taken, and a goal was scored. */
  gapOpens: number;
  shots: number;
  goals: number;
  /** Space created for the attack in the changed world, m²: median and 90% interval. */
  space: readonly [median: number, lo: number, hi: number];
  /** The best chance's xG, median over the re-runs. */
  xg: number;
  /** Re-runs in which the change ended offside, where that can happen. */
  offside?: number;
}

/** As played: the Tactician's 32 re-runs of the moment with nothing changed (PRD 10.2). */
export const AS_PLAYED: Result = { gapOpens: 30, shots: 24, goals: 11, space: [41, 33, 48], xg: 0.31 };

export interface Option {
  id: DecisionOptionId;
  /** What happened. */
  actual?: boolean;
  /** Modelled value of the option at the time: the space value it was expected to gain, 0–1. */
  value: number;
  /** Where each affected player goes instead, from the decision on. Everyone else plays as the engine would. */
  tracks: Readonly<Record<string, readonly Key[]>>;
  /** A pass that wasn't played, and where the ball goes instead. */
  pass?: { to: XY; difficulty: number };
  ball?: readonly Key[];
  /** Where space opens, or stays shut, in the changed world. */
  ring: { at: XY; open: boolean };
  result: Result;
  /** The verdict with its numbers, for Analyst. */
  analyst: string;
}

export interface DecisionPoint {
  id: DecisionPointId;
  player: string;
  /** Moment time of the decision, in seconds. */
  t: number;
  options: readonly Option[];
}

/** A changed track: exactly what happened up to the decision, then the new keyframes. */
function branch(id: string, t: number, after: readonly Key[]): Key[] {
  const keys = player(id).keys;
  const [x, y] = at(keys, t);
  return [...keys.filter((k) => k[0] < t), [t, x, y], ...after];
}

export const DECISIONS: readonly DecisionPoint[] = [
  {
    id: 'k9-run',
    player: 'kes-09',
    t: 1,
    options: [
      {
        id: 'k9-decoy',
        actual: true,
        value: 0.62,
        tracks: {},
        ring: { at: GAP_CENTRE, open: true },
        result: AS_PLAYED,
        analyst: 'As played: gap opens in 30 of 32 re-runs; space 41 m² (33–48); goals in 11 of 32.',
      },
      {
        id: 'k9-behind',
        value: 0.55,
        tracks: {
          'kes-09': branch('kes-09', 1, [[4.6, 96, 36.5], [9, 98, 36.5]]),
          'ash-05': branch('ash-05', 1.5, [[4.6, 95.5, 38.5], [9, 96.5, 38.5]]),
          'ash-04': branch('ash-04', 1.5, [[4.6, 95, 31], [9, 96, 31]]),
        },
        ring: { at: [83, 40], open: true },
        result: { gapOpens: 14, shots: 15, goals: 4, space: [23, 16, 31], xg: 0.12, offside: 9 },
        analyst: 'Run in behind: both centre-backs drop about 5 m; space 23 m² (16–31) at the edge of the box, not in it; offside in 9 of 32; goals in 4 of 32.',
      },
      {
        id: 'k9-stay',
        value: 0.41,
        tracks: {
          'kes-09': branch('kes-09', 1, [[9, 85, 35]]),
          'ash-05': branch('ash-05', 1.5, [[9, 90.5, 37.5]]),
        },
        ring: { at: GAP_CENTRE, open: false },
        result: { gapOpens: 3, shots: 7, goals: 1, space: [6, 2, 11], xg: 0.07 },
        analyst: 'Stay central: No. 5 holds; gap opens in 3 of 32; space 6 m² (2–11); best chance xG 0.07 against 0.31 as played.',
      },
      {
        id: 'k9-check',
        value: 0.33,
        tracks: {
          'kes-09': branch('kes-09', 1, [[4.2, 78.5, 37], [9, 77.5, 37]]),
          'ash-05': branch('ash-05', 1.5, [[4.2, 85.5, 37.5], [9, 85, 37.5]]),
          'ash-04': branch('ash-04', 2.5, [[5, 89.5, 35], [9, 89, 35.5]]),
        },
        ring: { at: [91.5, 40], open: false },
        result: { gapOpens: 11, shots: 12, goals: 3, space: [17, 11, 24], xg: 0.1 },
        analyst: 'Check short: No. 5 steps out 4.5 m; No. 4 covers in 21 of 32; gap opens in 11 of 32; space 17 m² (11–24).',
      },
    ],
  },
  {
    id: 'a5-follow',
    player: 'ash-05',
    t: 2.5,
    options: [
      {
        id: 'a5-track',
        actual: true,
        value: 0.58,
        tracks: {},
        ring: { at: GAP_CENTRE, open: true },
        result: AS_PLAYED,
        analyst: 'As played: gap opens in 30 of 32 re-runs; space 41 m² (33–48); goals in 11 of 32.',
      },
      {
        id: 'a5-pass-on',
        value: 0.57,
        tracks: {
          'ash-05': branch('ash-05', 2.5, [[4.6, 90.8, 38.5], [9, 90.8, 38.5]]),
          'ash-02': branch('ash-02', 2.5, [[4.6, 91, 51.5], [9, 92, 51]]),
        },
        ring: { at: GAP_CENTRE, open: false },
        result: { gapOpens: 2, shots: 6, goals: 1, space: [5, 1, 9], xg: 0.05 },
        analyst: 'Pass on: modelled value 0.57 against 0.58 for tracking, a near tie. Gap opens in 2 of 32; space 5 m² (1–9); goals in 1 of 32.',
      },
      {
        id: 'a5-hold',
        value: 0.44,
        tracks: {
          'ash-05': branch('ash-05', 2.5, [[4.6, 90.5, 38.5], [9, 90.5, 38.5]]),
        },
        ring: { at: [91.5, 52], open: true },
        result: { gapOpens: 2, shots: 13, goals: 3, space: [26, 19, 33], xg: 0.11 },
        analyst: 'Hold the line: gap opens in 2 of 32, but 26 m² (19–33) opens wide for No. 9; shots in 13 of 32, mostly from crosses; goals in 3 of 32.',
      },
    ],
  },
  {
    id: 'k8-pass',
    player: 'kes-08',
    t: 4.2,
    options: [
      {
        id: 'k8-gap',
        actual: true,
        value: 0.66,
        tracks: {},
        ring: { at: GAP_CENTRE, open: true },
        result: AS_PLAYED,
        analyst: 'As played: gap opens in 30 of 32 re-runs; space 41 m² (33–48); goals in 11 of 32.',
      },
      {
        id: 'k8-switch',
        value: 0.48,
        tracks: {
          'kes-07': branch('kes-07', 4.2, [[5.8, 88.5, 15.5], [9, 92, 21]]),
          'ash-03': branch('ash-03', 4.2, [[5.8, 89.5, 16.5], [9, 92.5, 19.5]]),
        },
        pass: { to: [88.5, 15.5], difficulty: 7.2 },
        ball: [[4.2, 60.6, 40.4], [5.8, 88.5, 15.5], [9, 92.6, 20.8]],
        ring: { at: [90, 19], open: true },
        result: { gapOpens: 30, shots: 10, goals: 2, space: [18, 12, 25], xg: 0.08 },
        analyst: 'Switch: difficulty 7.2; the gap opens in 30 of 32 but goes unused; space 18 m² (12–25) on the wing; best chance xG 0.08.',
      },
      {
        id: 'k8-carry',
        value: 0.39,
        tracks: {
          'kes-08': branch('kes-08', 4.2, [[6, 68, 40.5], [9, 72, 40.5]]),
          'ash-06': branch('ash-06', 4.2, [[6, 70.5, 40], [9, 72.5, 40]]),
          'ash-05': branch('ash-05', 4.6, [[6.5, 90.5, 41], [9, 90, 40]]),
        },
        ball: [[4.2, 60.6, 40.4], [6, 68.8, 40.4], [9, 72.8, 40.4]],
        ring: { at: GAP_CENTRE, open: false },
        result: { gapOpens: 6, shots: 8, goals: 1, space: [9, 4, 15], xg: 0.06 },
        analyst: 'Carry: No. 6 steps up to meet him; No. 5 recovers 6 m in 1.9 s; gap open in 6 of 32; space 9 m² (4–15).',
      },
    ],
  },
];

const OPTIONS = new Map<string, { point: DecisionPoint; option: Option }>(DECISIONS.flatMap((d) => d.options.map((o) => [o.id, { point: d, option: o }] as const)));

export function decisionOf(optionId: string): { point: DecisionPoint; option: Option } | null {
  return OPTIONS.get(optionId) ?? null;
}

/** The changed tracks of an option, for the control field of the changed world (PRD 10.10). */
export const scenarioTracks = (optionId: string): Readonly<Record<string, readonly Key[]>> | null => OPTIONS.get(optionId)?.option.tracks ?? null;

/** The options a player could have chosen instead, best modelled value first; what happened is listed apart. */
export const alternatives = (point: DecisionPoint) => point.options.filter((o) => !o.actual).sort((a, b) => b.value - a.value);
export const actualOf = (point: DecisionPoint) => point.options.find((o) => o.actual)!;
/** An option's rank among all the player's options by modelled value: 1 is the highest. */
export const rankOf = (point: DecisionPoint, option: Option) => [...point.options].sort((a, b) => b.value - a.value).indexOf(option) + 1;

export const counterfactualId = (optionId: string) => `${MATCH_ID}-c${String(110 + [...OPTIONS.keys()].indexOf(optionId)).padStart(4, '0')}`;

/** A changed decision on the pitch: the ghosts, the pass not played, and the ring of the changed world. */
export interface Scenario {
  id: string;
  /** Preview while choosing: the path ahead only. Result: the changed world playing out. */
  phase: 'preview' | 'result';
  tracks: Readonly<Record<string, readonly Key[]>>;
  ball?: readonly Key[];
  overlays: readonly Overlay[];
  world: string;
}

const msOf = (t: number) => BASE_MS + Math.round(t * 1000);

/** A changed decision's words in the viewer's language. */
export interface ScenarioWords {
  /** The tag on the ghost of the player whose decision changed: "No. 9 · Stay central". */
  tag: string;
  ring: string;
  plain: string;
  world: string;
}

/** An option's words in a pack, falling back to English for any the pack leaves out. */
export const wordsOf = (choices: Record<DecisionOptionId, DecisionChoice>, english: Record<DecisionOptionId, DecisionChoice>, id: DecisionOptionId): Required<DecisionChoice> => {
  const mine = choices[id];
  const en = english[id];
  return { label: mine.label, detail: mine.detail, world: mine.world ?? en.world ?? '', plain: mine.plain ?? en.plain ?? '', ring: mine.ring ?? en.ring ?? '' };
};

/**
 * Overlays for a changed decision in the feed's own shape, so the 2D and 3D views draw them as any other (PRD 15.2),
 * with its words in the viewer's language (`lang`).
 */
export function scenarioFor(optionId: string, mode: Mode, phase: Scenario['phase'], words: ScenarioWords, lang: string): Scenario | null {
  const found = OPTIONS.get(optionId);
  if (!found || found.option.actual) return null;
  const { point, option } = found;
  const cf = counterfactualId(optionId);
  let n = 0;
  const make = (kind: Overlay['kind'], t0: number, t1: number, fields: Partial<Overlay>): Overlay => ({
    overlay_id: `${cf}-o${++n}`,
    rev: 1,
    match_id: MATCH_ID,
    period: PERIOD,
    t_start_ms: msOf(t0),
    t_end_ms: msOf(t1),
    kind,
    layer: kind === 'gap_ring' || kind === 'ghost' || kind === 'pass_line' ? 'pitch' : 'labels',
    priority: kind === 'gap_ring' ? 0 : 1,
    mode,
    anchors: {},
    text: {},
    a11y_text: {},
    data: null,
    evidence_ids: [cf],
    confidence: 0.84,
    approval: 'auto',
    counterfactual_id: cf,
    ai_generated: true,
    labels: ['synthetic-data', 'ai-generated', 'simulation'],
    ...fields,
  });
  // Ghosts appear at the decision: before it, the changed world is the real one.
  const overlays: Overlay[] = Object.entries(option.tracks).map(([id, track]) =>
    make('ghost', point.t, T_STOP, {
      anchors: { player_id: id, ghost_track_id: `${cf}:${id}` },
      // The ghost of the player whose decision changed is named; the others it moved stay quiet.
      text: phase === 'result' && id === point.player ? { [lang]: words.tag } : {},
      data: { track, from: point.t, path: phase === 'preview' ? 'ahead' : 'trail', reruns: RERUNS, ...(phase === 'preview' ? { real: player(id).keys } : {}) },
    }),
  );
  if (option.pass) overlays.push(make('pass_line', point.t, phase === 'preview' ? T_STOP : 6.4, { anchors: { from_xy: PASS_FROM, to_xy: option.pass.to }, data: { difficulty: option.pass.difficulty, planned: true } }));
  if (phase === 'result') {
    overlays.push(
      make('gap_ring', Math.max(point.t + 0.6, 3.8), T_STOP, {
        anchors: { centre_xy: option.ring.at, radius_m: 6 },
        text: { [lang]: words.ring },
        a11y_text: { [lang]: words.plain },
        data: { rx_m: 5.4, ry_m: 6.8, shut: !option.ring.open, reruns: RERUNS },
      }),
    );
  }
  return { id: optionId, phase, tracks: option.tracks, ball: option.ball, overlays, world: words.world };
}
