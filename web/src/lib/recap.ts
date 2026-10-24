// The recap package (PRD 10.8): halftime and full-time recaps of the match's top space moments, which the producer
// can curate and publish (15.6) and any viewer can read spoiler-safe (8.2). Synthetic match, like everything here.
import { useEffect, useState } from 'react';
import { LEADERS, type Leader } from './content';
import { MATCH_ID, type Team, type XY } from './match';

export type RecapKind = 'halftime' | 'fulltime';

export interface MomentDiagram {
  /** The players that matter in the moment, in metres. */
  players: readonly { id: string; at: XY }[];
  /** The run that made the space. */
  run: { id: string; from: XY; to: XY };
  /** Where the space opened. */
  ring: XY;
  /** The pass into it, if there was one. */
  pass?: { from: XY; to: XY };
  ball: XY;
}

export interface RecapMoment {
  /** The detected moment's ID (contract: detected_moment_id). */
  id: string;
  minute: number;
  half: 1 | 2;
  team: Team;
  /** Who made the space, and who used it. */
  creator: string;
  finisher: string;
  title: string;
  /** The same moment told without its result, for spoiler-safe recaps. */
  safeTitle: string;
  text: string;
  safeText: string;
  /** Space Created in m², with its 90% interval (PRD 10.3). */
  space: readonly [value: number, lo: number, hi: number];
  /** Gain in space value. */
  threat: number;
  outcome: 'goal' | 'saved' | 'off target' | 'blocked';
  /** Only the 63′ moment has its full tracking replay in this build. */
  replay: boolean;
  diagram: MomentDiagram;
}

export const RECAP_MOMENTS: readonly RecapMoment[] = [
  {
    id: `${MATCH_ID}-d0001`,
    minute: 12,
    half: 1,
    team: 'kes',
    creator: 'kes-07',
    finisher: 'kes-09',
    title: 'No. 7 holds the width, and a lane opens for No. 9',
    safeTitle: 'No. 7 holds the width, and a lane opens for No. 9',
    text: 'Quillan stays out on the right touchline, so Ashmoor’s left-back can’t tuck in. The lane between full-back and centre-back opens, and Velmar gets a shot away. Saved.',
    safeText: 'Quillan stays out on the right touchline, so Ashmoor’s left-back can’t tuck in. The lane between full-back and centre-back opens, and Velmar gets a shot away.',
    space: [38, 29, 47],
    threat: 0.06,
    outcome: 'saved',
    replay: false,
    diagram: {
      players: [
        { id: 'kes-07', at: [88, 6] },
        { id: 'kes-09', at: [90, 27] },
        { id: 'kes-08', at: [74, 30] },
        { id: 'ash-03', at: [84, 10] },
        { id: 'ash-04', at: [90, 33] },
        { id: 'ash-01', at: [102, 34] },
      ],
      run: { id: 'kes-09', from: [84, 32], to: [92, 26] },
      ring: [89, 19],
      pass: { from: [74, 30], to: [91, 24] },
      ball: [91, 24],
    },
  },
  {
    id: `${MATCH_ID}-d0002`,
    minute: 27,
    half: 1,
    team: 'ash',
    creator: 'ash-10',
    finisher: 'ash-10',
    title: 'Moravec drops between the lines, and Ashmoor’s best chance follows',
    safeTitle: 'Moravec drops between the lines',
    text: 'Ashmoor’s No. 10 drops off the front line and Kestrel Bay’s No. 6 follows him up the pitch. The space Castellane leaves behind is where Ashmoor’s best chance of the half comes from. Thorncastle saves.',
    safeText: 'Ashmoor’s No. 10 drops off the front line and Kestrel Bay’s No. 6 follows him up the pitch. The space Castellane leaves behind is where Ashmoor’s best chance of the half comes from.',
    space: [44, 34, 55],
    threat: 0.09,
    outcome: 'saved',
    replay: false,
    // Ashmoor attack towards Kestrel Bay's goal at x = 0.
    diagram: {
      players: [
        { id: 'ash-10', at: [35, 30] },
        { id: 'ash-09', at: [25, 38] },
        { id: 'kes-06', at: [38, 31] },
        { id: 'kes-04', at: [19, 26] },
        { id: 'kes-05', at: [19, 40] },
        { id: 'kes-01', at: [4, 34] },
      ],
      run: { id: 'ash-10', from: [25, 30], to: [35, 30] },
      ring: [25, 30],
      pass: { from: [35, 30], to: [13, 35] },
      ball: [13, 35],
    },
  },
  {
    id: `${MATCH_ID}-d0003`,
    minute: 41,
    half: 1,
    team: 'kes',
    creator: 'kes-09',
    finisher: 'kes-10',
    title: 'No. 9’s first decoy run, and No. 10 shoots from the gap',
    safeTitle: 'No. 9’s first decoy run',
    text: 'Velmar runs across the line, Hendricx goes with him, and Arkwell shoots from the gap they leave. Saved. The same run comes back in the second half.',
    safeText: 'Velmar runs across the line, Hendricx goes with him, and Arkwell steps into the gap they leave.',
    space: [36, 27, 45],
    threat: 0.07,
    outcome: 'saved',
    replay: false,
    diagram: {
      players: [
        { id: 'kes-09', at: [91, 48] },
        { id: 'ash-05', at: [92, 45] },
        { id: 'kes-10', at: [88, 37] },
        { id: 'ash-04', at: [93, 30] },
        { id: 'kes-08', at: [72, 38] },
        { id: 'ash-01', at: [102, 35] },
      ],
      run: { id: 'kes-09', from: [85, 35], to: [91, 48] },
      ring: [89, 39],
      pass: { from: [72, 38], to: [88, 37] },
      ball: [88, 37],
    },
  },
  {
    id: `${MATCH_ID}-d0004`,
    minute: 55,
    half: 2,
    team: 'kes',
    creator: 'kes-02',
    finisher: 'kes-07',
    title: 'Ferrow’s overlap pins Ashmoor’s left-back',
    safeTitle: 'Ferrow’s overlap pins Ashmoor’s left-back',
    text: 'Kestrel Bay’s right-back runs outside Quillan, Strand has to choose, and Quillan cuts inside into the space. His shot is blocked.',
    safeText: 'Kestrel Bay’s right-back runs outside Quillan, Strand has to choose, and Quillan cuts inside into the space.',
    space: [21, 15, 28],
    threat: 0.03,
    outcome: 'blocked',
    replay: false,
    diagram: {
      players: [
        { id: 'kes-02', at: [88, 5] },
        { id: 'kes-07', at: [86, 20] },
        { id: 'ash-03', at: [87, 10] },
        { id: 'ash-04', at: [92, 27] },
        { id: 'ash-07', at: [79, 16] },
        { id: 'ash-01', at: [102, 34] },
      ],
      run: { id: 'kes-02', from: [72, 6], to: [88, 5] },
      ring: [88, 17],
      ball: [86, 20],
    },
  },
  {
    id: `${MATCH_ID}-d0005`,
    minute: 63,
    half: 2,
    team: 'kes',
    creator: 'kes-09',
    finisher: 'kes-10',
    title: 'The decoy run: No. 9 pulls No. 5 wide, and No. 10 scores',
    safeTitle: 'The decoy run: No. 9 pulls No. 5 wide',
    text: 'Velmar’s run isn’t to get the ball. Hendricx follows him 10.8 m wide, the gap opens behind him, and Arkwell runs into it to score. Without the run, the Tactician’s re-runs keep the gap shut.',
    safeText: 'Velmar’s run isn’t to get the ball. Hendricx follows him 10.8 m wide, the gap opens behind him, and Arkwell runs into it. Without the run, the Tactician’s re-runs keep the gap shut.',
    space: [41, 33, 48],
    threat: 0.14,
    outcome: 'goal',
    replay: true,
    diagram: {
      players: [
        { id: 'kes-09', at: [91, 53] },
        { id: 'ash-05', at: [93.5, 47.2] },
        { id: 'kes-10', at: [88, 40.3] },
        { id: 'ash-04', at: [92, 30] },
        { id: 'kes-08', at: [60, 40.4] },
        { id: 'ash-01', at: [101, 34] },
      ],
      run: { id: 'kes-09', from: [84, 34], to: [91, 53] },
      ring: [88.5, 40],
      pass: { from: [60.6, 40.4], to: [88, 40.3] },
      ball: [88, 40.3],
    },
  },
];

export const RECAP_SCORE: Record<RecapKind, { kes: number; ash: number }> = { halftime: { kes: 0, ash: 0 }, fulltime: { kes: 1, ash: 0 } };

/** Space Created up to each recap, with 90% intervals: the halftime board knows nothing of the second half. */
export const RECAP_LEADERS: Record<RecapKind, readonly Leader[]> = {
  halftime: [
    { id: 'kes-09', v: 63, lo: 49, hi: 78 },
    { id: 'ash-10', v: 48, lo: 37, hi: 61 },
    { id: 'kes-07', v: 41, lo: 31, hi: 52 },
    { id: 'kes-10', v: 19, lo: 12, hi: 27 },
    { id: 'ash-05', v: 17, lo: 10, hi: 24 },
  ],
  fulltime: LEADERS,
};

/** The last minute each recap covers. */
export const RECAP_UNTIL: Record<RecapKind, number> = { halftime: 45, fulltime: 90 };

export interface RecapPackage {
  kind: RecapKind;
  /** Moment IDs, in the order the recap tells them. */
  moments: readonly string[];
  spoilerSafe: boolean;
  /** When the producer published it; null for the automatic package. */
  publishedAt: string | null;
}

/** The automatic package: the period's moments, biggest space first, until the producer publishes one. */
export function autoPackage(kind: RecapKind): RecapPackage {
  const moments = RECAP_MOMENTS.filter((m) => kind === 'fulltime' || m.half === 1)
    .slice()
    .sort((a, b) => b.space[0] - a.space[0])
    .map((m) => m.id);
  return { kind, moments, spoilerSafe: false, publishedAt: null };
}

const key = (kind: RecapKind) => `offball.recap.${MATCH_ID}.${kind}`;
const CHANNEL = `offball:recap:${MATCH_ID}`;

export function loadPublished(kind: RecapKind): RecapPackage | null {
  try {
    const raw = localStorage.getItem(key(kind));
    return raw ? (JSON.parse(raw) as RecapPackage) : null;
  } catch {
    return null;
  }
}

/** Publishes a recap package to every open view on this device (the recap screen updates at once). */
export function publishRecap(pkg: RecapPackage): void {
  try {
    localStorage.setItem(key(pkg.kind), JSON.stringify(pkg));
  } catch {
    // Storage full or blocked: the package still reaches open views.
  }
  try {
    const ch = new BroadcastChannel(CHANNEL);
    ch.postMessage(pkg);
    ch.close();
  } catch {
    // No BroadcastChannel: other views see it on their next load.
  }
}

export function withdrawRecap(kind: RecapKind): void {
  try {
    localStorage.removeItem(key(kind));
  } catch {
    // Nothing stored.
  }
  try {
    const ch = new BroadcastChannel(CHANNEL);
    ch.postMessage({ kind, withdrawn: true });
    ch.close();
  } catch {
    // Other views update on their next load.
  }
}

/** The package for a period: the producer's if published, else the automatic one. Follows publishing in other tabs. */
export function useRecapPackage(kind: RecapKind): RecapPackage {
  const [pkg, setPkg] = useState<RecapPackage>(() => loadPublished(kind) ?? autoPackage(kind));
  useEffect(() => {
    setPkg(loadPublished(kind) ?? autoPackage(kind));
    let ch: BroadcastChannel | null = null;
    try {
      ch = new BroadcastChannel(CHANNEL);
      ch.onmessage = (e: MessageEvent<RecapPackage | { kind: RecapKind; withdrawn: true }>) => {
        if (e.data.kind !== kind) return;
        setPkg('withdrawn' in e.data ? autoPackage(kind) : e.data);
      };
    } catch {
      ch = null;
    }
    return () => ch?.close();
  }, [kind]);
  return pkg;
}

export const momentById = (id: string) => RECAP_MOMENTS.find((m) => m.id === id);
