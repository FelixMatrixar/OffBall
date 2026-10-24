import type { Lang, Mode } from '../prefs';

/** One caption per beat of the showcase moment: build-up, run, follow, gap, pass, goal. */
export type Six = readonly [string, string, string, string, string, string];

/** Favourites with a scripted Player focus story. Every other player gets the generic lines. */
export const STORY_PLAYERS = ['kes-09', 'kes-10', 'kes-07', 'ash-05', 'ash-10'] as const;
export type StoryPlayer = (typeof STORY_PLAYERS)[number];

export type Concept = 'decoy' | 'follow' | 'gap' | 'timed';

export interface UiStrings {
  spaceCentre: string;
  language: string;
  whatIf: string;
  personalize: string;
  ask: string;
  pair: string;
  shortcuts: string;
  /** The header's menu for everything that isn't used every minute. */
  more: string;
  /** The loading checks, in the order they tick off (PRD 15.11). */
  loading: readonly [string, string, string];
  viewingMode: string;
  factChecked: string;
  voiceOn: string;
  voiceOff: string;
  /** {n}: number of data points. */
  aiCaption: string;
  draft: string;
  attacking: string;
  defending: string;
  howGoal: string;
  howGoalHint: string;
  real: string;
  without: string;
  stall: string;
  synced: string;
  /** {n}: graphics dropped while the feed was down. */
  syncedMissed: string;
  offline: string;
  goal: string;
  newIdea: string;
  glossary: string;
  pauseExplain: string;
  /** {n}: times seen. */
  seen: string;
  next: string;
  synthetic: string;
  play: string;
  pause: string;
  markers: readonly [string, string, string, string, string];
}

/** Change one decision (PRD 10.10): the decisions a viewer can change in the showcase moment, and their options. */
export type DecisionPointId = 'k9-run' | 'a5-follow' | 'k8-pass';
export type DecisionOptionId = 'k9-decoy' | 'k9-behind' | 'k9-stay' | 'k9-check' | 'a5-track' | 'a5-pass-on' | 'a5-hold' | 'k8-gap' | 'k8-switch' | 'k8-carry';

/** One option in words. What happened needs only its label and detail; the others say what their re-runs showed. */
export interface DecisionChoice {
  label: string;
  detail: string;
  /** The changed world, as it finishes a sentence: "if No. 9 stays central". */
  world?: string;
  /** The verdict in one plain sentence (Casual, Learn, Audio-described; Analyst's stays English, with its numbers). */
  plain?: string;
  /** The ring's label in the changed world. */
  ring?: string;
}

/** The decision panel's words (PRD 15.12). Templates take {n}, {total}, {who}, {clock}, {world} and {num}. */
export interface DecideStrings {
  open: string;
  close: string;
  kicker: string;
  title: string;
  back: string;
  steps: readonly [string, string, string, string];
  whose: string;
  pickHint: string;
  pickChip: string;
  noDecision: string;
  optionCount: string;
  happened: string;
  instead: string;
  nearly: string;
  rerun: string;
  anotherPlayer: string;
  chooseHint: string;
  keyReal: string;
  keyChanged: string;
  keyHold: string;
  running: string;
  runningLine: string;
  outOf: string;
  reRuns: string;
  cancel: string;
  cancelled: string;
  asPlayed: string;
  changed: string;
  measure: string;
  gap: string;
  shots: string;
  goals: string;
  space: string;
  offside: string;
  compare: string;
  from: string;
  again: string;
  sideBySide: string;
  otherOption: string;
  note: string;
  field: string;
  meta: string;
  /** A Kestrel Bay player, and an Ashmoor one, as the panel names them. */
  who: string;
  whoAway: string;
  points: Record<DecisionPointId, { what: string; question: string }>;
  choices: Record<DecisionOptionId, DecisionChoice>;
}

export interface Pack {
  lang: Lang;
  /** Native-speaker review of captions and glossary (PRD 15.3). Unreviewed packs are labelled as drafts. */
  reviewed: boolean;
  ui: UiStrings;
  modes: Record<Mode, { label: string; desc: string }>;
  steps: readonly [string, string, string, string, string];
  casual: Six;
  /** The last line takes {count}: decoy runs spotted today. */
  learn: Six;
  whatIf: readonly [string, string];
  /** The first line takes {depth}: metres from Ashmoor's back line to their goal. */
  analyst: Six;
  audio: Six;
  player: Record<StoryPlayer, Six>;
  /** For players without a scripted story. {num}, {name}, {speed}, {dist}, {metres}. */
  generic: { follow: string; moving: string; holding: string; goal: string };
  glossary: Record<Concept, { term: string; def: string }>;
  /** The first casual line, used by the first-run preview. */
  preview: string;
  decide: DecideStrings;
}
