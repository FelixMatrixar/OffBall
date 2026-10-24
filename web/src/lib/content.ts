import { PLAYERS, player } from './match';
import type { Mode } from './prefs';

/** Glyphs for the mode cards. Labels and descriptions come from the language packs. */
export const MODE_GLYPHS: Record<Mode, string> = { casual: '1', learn: '?', analyst: '%', player: '9', audio: '♪', broadcaster: '▶' };

export interface Leader {
  id: string;
  v: number;
  lo: number;
  hi: number;
}

/** Space Created this match, with the credit model's 90% interval (PRD 10.3). */
export const LEADERS: readonly Leader[] = [
  { id: 'kes-09', v: 118, lo: 96, hi: 137 },
  { id: 'kes-07', v: 64, lo: 51, hi: 79 },
  { id: 'ash-10', v: 52, lo: 40, hi: 66 },
  { id: 'kes-10', v: 35, lo: 26, hi: 45 },
  { id: 'ash-05', v: 31, lo: 22, hi: 40 },
];

export const leaderName = (id: string) => {
  const p = player(id);
  return `No. ${p.num} ${p.name.split(' ').slice(-1)[0]} · ${p.team.toUpperCase()}`;
};

export interface FocusStats {
  /** Off-ball runs before and after this move's run, and when it starts. */
  runs: [number, number, number];
  dragged: [number, number, number];
  space: [number, number, number];
  sprints: [number, number, number];
  distanceKm: number;
  topSpeed: number;
  season: string;
  runsByType: { type: 'Decoy' | 'In behind' | 'Overlap' | 'Check to ball'; n: number }[];
}

const SCRIPTED: Record<string, FocusStats> = {
  'kes-09': {
    runs: [6, 7, 1],
    dragged: [2, 3, 2.5],
    space: [77, 118, 6.4],
    sprints: [13, 14, 4.6],
    distanceKm: 8.68,
    topSpeed: 33.4,
    season: 'Three defenders dragged ties No. 9’s season high for one match.',
    runsByType: [
      { type: 'Decoy', n: 4 },
      { type: 'In behind', n: 2 },
      { type: 'Check to ball', n: 1 },
    ],
  },
  'kes-10': {
    runs: [4, 5, 3.8],
    dragged: [1, 1, 0],
    space: [28, 35, 5.6],
    sprints: [9, 10, 4.6],
    distanceKm: 9.12,
    topSpeed: 31.8,
    season: 'His 4th goal of the season. Three of the four came straight after a teammate’s decoy run.',
    runsByType: [
      { type: 'In behind', n: 3 },
      { type: 'Check to ball', n: 2 },
    ],
  },
  'kes-07': {
    runs: [5, 5, 0],
    dragged: [2, 2, 0],
    space: [64, 64, 0],
    sprints: [11, 11, 0],
    distanceKm: 9.41,
    topSpeed: 32.6,
    season: 'No winger in the league has held the width for longer this season.',
    runsByType: [
      { type: 'Overlap', n: 2 },
      { type: 'In behind', n: 2 },
      { type: 'Decoy', n: 1 },
    ],
  },
  'ash-05': {
    runs: [9, 10, 2.5],
    dragged: [0, 0, 0],
    space: [31, 31, 0],
    sprints: [6, 7, 2.5],
    distanceKm: 8.02,
    topSpeed: 29.1,
    season: 'He has followed 71% of diagonal runs this season, against a league average of 52%.',
    runsByType: [
      { type: 'Check to ball', n: 6 },
      { type: 'In behind', n: 4 },
    ],
  },
  'ash-10': {
    runs: [6, 6, 0],
    dragged: [1, 1, 0],
    space: [52, 52, 0],
    sprints: [8, 8, 0],
    distanceKm: 9.55,
    topSpeed: 30.4,
    season: 'Ashmoor’s top creator of space this season.',
    runsByType: [
      { type: 'Check to ball', n: 3 },
      { type: 'In behind', n: 2 },
      { type: 'Decoy', n: 1 },
    ],
  },
};

/** Player focus numbers. Scripted for the five storied players, derived from the shirt number for the rest. */
export function focusStats(id: string): FocusStats {
  if (SCRIPTED[id]) return SCRIPTED[id];
  const p = player(id);
  const n = p.num;
  const keeper = p.role === 'GK';
  const runs = keeper ? 0 : 2 + (n % 4);
  return {
    runs: [runs, runs, 0],
    dragged: [n % 3, n % 3, 0],
    space: [keeper ? 0 : 8 + ((n * 7) % 30), keeper ? 0 : 8 + ((n * 7) % 30), 0],
    sprints: [keeper ? 0 : 4 + (n % 6), keeper ? 0 : 4 + (n % 6), 0],
    distanceKm: keeper ? 3.9 : 8 + ((n * 37) % 160) / 100,
    topSpeed: keeper ? 21.4 : 27 + ((n * 13) % 60) / 10,
    season: keeper ? 'Kept in position through the move.' : 'Steady off-ball work: no standout numbers in this move.',
    runsByType: keeper
      ? []
      : [
          { type: 'Check to ball', n: 1 + (n % 3) },
          { type: 'In behind', n: n % 2 },
        ],
  };
}

export const FAVOURITE_OPTIONS = PLAYERS.map((p) => p.id);

export interface MatchdayGame {
  home: string;
  away: string;
  hs: number;
  as: number;
  /** Match clock in seconds when the Space Centre opened. */
  base: number;
  type: string;
  value: number;
  text: string;
  /** Gap centre and run arrow in pitch SVG units (10 per metre). */
  gap: [number, number];
  arrow: [number, number, number, number];
}

/** Round 27: ten matches for the Space Centre, ranked by space value. Club IDs index the league's kits. */
export const MATCHDAY: readonly MatchdayGame[] = [
  { home: 'kes', away: 'ash', hs: 0, as: 0, base: 63 * 60 + 4, type: 'Decoy run', value: 41, text: 'Kestrel Bay’s No. 9 drags the centre-back wide. A gap opens in the middle.', gap: [885, 280], arrow: [840, 340, 910, 150] },
  { home: 'bra', away: 'sal', hs: 2, as: 1, base: 58 * 60 + 12, type: 'Overlap', value: 33, text: 'Brackenford’s full-back overlaps outside. It’s two against one on the flank.', gap: [880, 560], arrow: [700, 620, 900, 600] },
  { home: 'mor', away: 'qua', hs: 1, as: 0, base: 64 * 60 + 40, type: 'Press broken', value: 29, text: 'One pass beats four Quarrystone pressers. Morrowdale break three against two.', gap: [640, 330], arrow: [420, 360, 640, 330] },
  { home: 'nor', away: 'oak', hs: 2, as: 2, base: 63 * 60 + 20, type: 'Third-man run', value: 26, text: 'Northcairn’s No. 8 runs beyond the line before the lay-off arrives.', gap: [860, 300], arrow: [700, 420, 860, 300] },
  { home: 'fen', away: 'gle', hs: 3, as: 2, base: 59 * 60 + 2, type: 'Fatigue gap', value: 22, text: 'Glenhollow’s right-back is 18% slower to recover. Fenwyck keep attacking that flank.', gap: [860, 120], arrow: [620, 160, 840, 120] },
  { home: 'cor', away: 'wre', hs: 1, as: 1, base: 61 * 60 + 33, type: 'Switch of play', value: 18, text: 'Corvenna switch it fast. The far winger is one against one with 6 m of space.', gap: [860, 600], arrow: [600, 100, 860, 600] },
  { home: 'dun', away: 'lar', hs: 0, as: 2, base: 60 * 60 + 8, type: 'Cover shadow', value: 15, text: 'Larkhaven’s No. 6 cuts off the passing lane. Duncliffe have to go backwards.', gap: [420, 330], arrow: [300, 330, 410, 330] },
  { home: 'har', away: 'ive', hs: 0, as: 0, base: 62 * 60 + 51, type: 'Space lost', value: 12, text: 'Ivelmouth have dropped 9 m deeper since the red card.', gap: [700, 340], arrow: [800, 340, 700, 340] },
  { home: 'jun', away: 'low', hs: 1, as: 2, base: 57 * 60 + 17, type: 'Blind-side run', value: 10, text: 'Lowmarsh’s No. 11 arrives on the defender’s blind side.', gap: [900, 420], arrow: [760, 520, 900, 420] },
  { home: 'pel', away: 'riv', hs: 0, as: 1, base: 62 * 60 + 5, type: 'Rotation', value: 8, text: 'Pellston rotate three attackers. One marker loses track of a runner.', gap: [820, 220], arrow: [700, 300, 820, 220] },
];
