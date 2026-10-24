// The showcase moment: Kestrel Bay's 63rd-minute decoy-run goal against Ashmoor (match m07, round 27).
// Coordinates are metres on a 105 × 68 m pitch: x runs left to right, y bottom to top (PRD 12.8).
// Kestrel Bay attack left to right. Player IDs follow the contract: club ID and a two-digit shirt number.

export type Team = 'kes' | 'ash';
export type XY = [number, number];
export type Key = readonly [t: number, x: number, y: number];
export type Role = 'GK' | 'RB' | 'CB' | 'LB' | 'DM' | 'CM' | 'AM' | 'RM' | 'LM' | 'RW' | 'LW' | 'ST';

export const MATCH_ID = 'm07';
export const PERIOD = 2;
/** 63:00 is 18 minutes into the second half; the moment's t is seconds after that. */
export const BASE_MS = 18 * 60_000;
export const T_END = 9;
export const HZ = 25;
export const FRAME_MS = 1000 / HZ;

export const CLUBS: Record<Team, { name: string; short: string }> = {
  kes: { name: 'Kestrel Bay', short: 'KES' },
  ash: { name: 'Ashmoor', short: 'ASH' },
};

export interface PlayerDef {
  id: string;
  team: Team;
  num: number;
  name: string;
  role: Role;
  keys: readonly Key[];
}

export const pid = (team: Team, num: number) => `${team}-${String(num).padStart(2, '0')}`;
const p = (team: Team, num: number, name: string, role: Role, keys: Key[]): PlayerDef => ({ id: pid(team, num), team, num, name, role, keys });

// Fictional players only (rule 4.7).
export const PLAYERS: readonly PlayerDef[] = [
  p('kes', 1, 'E. Thorncastle', 'GK', [[0, 6, 34]]),
  p('kes', 2, 'D. Ferrow', 'RB', [[0, 62, 10], [9, 66, 10]]),
  p('kes', 3, 'K. Ambrose', 'LB', [[0, 58, 60], [9, 62, 61]]),
  p('kes', 4, 'S. Brannagh', 'CB', [[0, 42, 26], [9, 46, 26]]),
  p('kes', 5, 'L. Marrow', 'CB', [[0, 42, 44], [9, 46, 44]]),
  p('kes', 6, 'O. Castellane', 'DM', [[0, 50, 34], [9, 54, 35]]),
  p('kes', 7, 'P. Quillan', 'RW', [[0, 86, 13], [4, 88, 14], [9, 90, 15]]),
  p('kes', 8, 'R. Delacorte', 'CM', [[0, 55, 39.5], [4.2, 60, 40.4], [6, 63, 41], [9, 66, 41]]),
  p('kes', 9, 'J. Velmar', 'ST', [[0, 84, 34], [1, 84, 34], [4.6, 91, 53], [9, 92, 54]]),
  p('kes', 10, 'T. Arkwell', 'AM', [[0, 73, 44], [3.8, 76, 42], [5.6, 88, 40.3], [6.4, 89, 40], [9, 92, 39]]),
  p('kes', 11, 'N. Penhallow', 'LW', [[0, 82, 58], [4, 84, 60], [9, 86, 60]]),
  p('ash', 1, 'B. Aldwyn', 'GK', [[0, 101, 34], [6.4, 101.5, 36], [9, 101, 35]]),
  p('ash', 2, 'C. Fennimore', 'RB', [[0, 89, 58], [9, 90, 59]]),
  p('ash', 3, 'H. Strand', 'LB', [[0, 88, 13], [9, 88, 14]]),
  p('ash', 4, 'G. Tallow', 'CB', [[0, 91, 29], [9, 92, 30]]),
  p('ash', 5, 'L. Hendricx', 'CB', [[0, 90, 37], [1.5, 90, 37], [4.6, 93.5, 47.2], [9, 93.7, 47]]),
  p('ash', 6, 'V. Pryor', 'DM', [[0, 79, 37], [3.5, 74, 39], [9, 75, 39]]),
  p('ash', 7, 'A. Kettering', 'LM', [[0, 70, 14], [9, 71, 15]]),
  p('ash', 8, 'I. Rowntree', 'CM', [[0, 78, 26], [9, 79, 27]]),
  p('ash', 9, 'E. Wyndham', 'ST', [[0, 60, 30], [9, 61, 31]]),
  p('ash', 10, 'S. Moravec', 'AM', [[0, 77, 49], [9, 79, 50]]),
  p('ash', 11, 'F. Danvers', 'RM', [[0, 69, 57], [9, 70, 57]]),
];

const BY_ID = new Map(PLAYERS.map((pl) => [pl.id, pl]));

export function player(id: string): PlayerDef {
  const pl = BY_ID.get(id);
  if (!pl) throw new Error(`Unknown player ${id}`);
  return pl;
}

export const hasPlayer = (id: string) => BY_ID.has(id);

/** "Kestrel Bay No. 9, J. Velmar": the accessible name of a player. */
export const playerLabel = (id: string) => {
  const pl = player(id);
  return `${CLUBS[pl.team].name} No. ${pl.num}, ${pl.name}`;
};

/** Where No. 9 and No. 5 would have been without the run (the Tactician's median re-run). */
export const COUNTERFACTUAL: Readonly<Record<string, readonly Key[]>> = {
  'kes-09': [[0, 84, 34], [9, 85, 35]],
  'ash-05': [[0, 90, 37], [9, 90.5, 37.5]],
};

export const BALL: readonly Key[] = [
  [0, 55.8, 39.3],
  [4.2, 60.6, 40.4],
  [5.6, 88, 40.3],
  [6.4, 89.4, 40],
  [6.9, 105.3, 36.2],
  [9, 105.3, 36.2],
];

export const PASS_FROM: XY = [60.6, 40.4];
export const PASS_TO: XY = [88, 40.3];
export const RUN_FROM: XY = [84, 34];
export const RUN_TO: XY = [91, 53];
export const GAP_CENTRE: XY = [88.5, 40];
export const A5_START: XY = [90, 37];
export const GOAL_AT: XY = [105.3, 36.2];
export const T_GOAL = 6.9;

const smooth = (u: number) => u * u * (3 - 2 * u);

/** Position at time t, interpolated between keyframes. */
export function at(keys: readonly Key[], t: number, ease = true): XY {
  if (t <= keys[0][0]) return [keys[0][1], keys[0][2]];
  for (let i = 0; i < keys.length - 1; i++) {
    const a = keys[i];
    const b = keys[i + 1];
    if (t <= b[0]) {
      let u = (t - a[0]) / (b[0] - a[0]);
      if (ease) u = smooth(u);
      return [a[1] + (b[1] - a[1]) * u, a[2] + (b[2] - a[2]) * u];
    }
  }
  const last = keys[keys.length - 1];
  return [last[1], last[2]];
}

/** Ball height in metres: a driven pass and a low shot. */
export function ballZ(t: number): number {
  const lift = (t0: number, t1: number, h: number) => (t > t0 && t < t1 ? h * Math.sin((Math.PI * (t - t0)) / (t1 - t0)) : 0);
  return 0.11 + lift(4.2, 5.6, 0.35) + lift(6.4, 6.9, 0.25);
}

/** Beats of the moment: 0 build-up, 1 run, 2 follow, 3 gap, 4 pass, 5 goal. */
export const STEP_TIMES = [0, 1, 2.5, 3.8, 4.2, 6.4] as const;

export function stepAt(t: number): number {
  let s = 0;
  STEP_TIMES.forEach((start, i) => {
    if (t >= start) s = i;
  });
  return s;
}

/** Timeline markers: the beats after the build-up. */
export const MOMENTS: readonly number[] = STEP_TIMES.slice(1);

export const distance = (a: XY, b: XY) => Math.hypot(a[0] - b[0], a[1] - b[1]);

/** x of Ashmoor's deepest outfield player: their back line. */
export function backLineX(pos: Record<string, XY>): number {
  let max = 0;
  for (const pl of PLAYERS) {
    if (pl.team === 'ash' && pl.role !== 'GK') max = Math.max(max, pos[pl.id][0]);
  }
  return max;
}

/** Match clock label for a moment time, such as 63:04. */
export const clockLabel = (t: number) => `63:${String(Math.min(59, Math.floor(t))).padStart(2, '0')}`;

/** Frame and event evidence IDs in the contract's format (PRD 12.8). */
export const frameId = (t: number) => Math.round((BASE_MS + t * 1000) / FRAME_MS);
export const frameRef = (t: number) => `${MATCH_ID}-f${PERIOD}-${frameId(t)}`;
export const EVENT_PASS = `${MATCH_ID}-e0912`;
export const EVENT_SHOT = `${MATCH_ID}-e0918`;
export const CF_ID = `${MATCH_ID}-c0007`;
