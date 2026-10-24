// tokens-ok-file: kit colours are club data, not styling; checkFixture tunes them per theme before they're drawn.
// Fictional kits and the per-fixture colour-vision check (PRD 16.3). For each fixture, the two teams' colours must
// stay distinguishable under simulated deuteranopia, protanopia and tritanopia and against the pitch; if not, the
// away team switches to its alternate kit, and if that fails too, its markers get a pattern.
import { VISIONS, adjustForContrast, contrast, deltaE, hex, parseColor, simulate, type RGB, type Vision } from './color';

export type Pattern = 'plain' | 'hoops' | 'stripes' | 'halves' | 'sash';

export interface Kit {
  primary: string;
  secondary: string;
  pattern: Pattern;
}

export interface Club {
  id: string;
  name: string;
  short: string;
  kit: Kit;
}

const club = (id: string, name: string, short: string, primary: string, secondary: string): Club => ({ id, name, short, kit: { primary, secondary, pattern: 'plain' } });

/** Every club in the OffBall League. Fictional names and colours (rule 4.7). */
export const LEAGUE: Record<string, Club> = Object.fromEntries(
  [
    club('kes', 'Kestrel Bay', 'KES', '#4da6ff', '#f2f2f2'),
    club('ash', 'Ashmoor', 'ASH', '#e2733a', '#1f2a5c'),
    club('bra', 'Brackenford', 'BRA', '#d7263d', '#f5f5f5'),
    club('sal', 'Saltmere', 'SAL', '#2e9e4f', '#f2c230'),
    club('mor', 'Morrowdale', 'MOR', '#7b3fbf', '#f5f5f5'),
    club('qua', 'Quarrystone', 'QUA', '#8c8c8c', '#1a1a1a'),
    club('nor', 'Northcairn', 'NOR', '#1f3c88', '#8fd3ff'),
    club('oak', 'Oakhallow', 'OAK', '#1d6b3a', '#e0b43a'),
    club('fen', 'Fenwyck', 'FEN', '#f2d000', '#1a1a1a'),
    club('gle', 'Glenhollow', 'GLE', '#1aa6a6', '#f5f5f5'),
    club('cor', 'Corvenna', 'COR', '#b5123a', '#f5f5f5'),
    club('wre', 'Wrenhallow', 'WRE', '#8a5a2b', '#f0e2c0'),
    club('dun', 'Duncliffe', 'DUN', '#222222', '#f5f5f5'),
    club('lar', 'Larkhaven', 'LAR', '#6fc3ff', '#1f2a5c'),
    club('har', 'Harbourne', 'HAR', '#f5f5f5', '#c8102e'),
    club('ive', 'Ivelmouth', 'IVE', '#d9d9d9', '#7a1f2b'),
    club('jun', 'Juniper Vale', 'JUN', '#7fd13b', '#6b3fa0'),
    club('low', 'Lowmarsh', 'LOW', '#c9a227', '#9bc53d'),
    club('pel', 'Pellston', 'PEL', '#6d1a36', '#8fd3ff'),
    club('riv', 'Rivenmoor', 'RIV', '#2d6a4f', '#f5f5f5'),
  ].map((c) => [c.id, c]),
);

export const clubByName = (name: string): Club | undefined => Object.values(LEAGUE).find((c) => c.name === name);

/** Distinct enough under every simulated vision, in OKLab. */
export const MIN_DELTA = 0.1;
/** Markers need 3:1 against the pitch (WCAG non-text contrast). */
export const MIN_PITCH_CONTRAST = 3;

export interface FixtureCheck {
  home: { colour: string; pattern: Pattern };
  away: { colour: string; pattern: Pattern; kit: 'primary' | 'secondary' };
  decision: 'primary' | 'away alternate' | 'pattern added';
  /** The smallest team-to-team distance across the four visions, and where it occurred. */
  minDelta: number;
  worst: Vision;
}

/** A kit colour tuned for this theme's pitch: lighter on a dark pitch, darker on a light one, hue kept. */
export const displayColour = (kitHex: string, pitch: string): string => hex(adjustForContrast(parseColor(kitHex), parseColor(pitch), MIN_PITCH_CONTRAST));

function separation(a: RGB, b: RGB): { min: number; worst: Vision } {
  let min = Infinity;
  let worst: Vision = 'typical';
  for (const v of VISIONS) {
    const d = deltaE(simulate(a, v), simulate(b, v));
    if (d < min) {
      min = d;
      worst = v;
    }
  }
  return { min, worst };
}

/** The colour-vision check for one fixture against one theme's pitch colour. */
export function checkFixture(homeId: string, awayId: string, pitch: string): FixtureCheck {
  const home = LEAGUE[homeId];
  const away = LEAGUE[awayId];
  const pitchRgb = parseColor(pitch);
  const h = parseColor(displayColour(home.kit.primary, pitch));
  const tryAway = (kitHex: string) => parseColor(displayColour(kitHex, pitch));
  const a1 = tryAway(away.kit.primary);
  const s1 = separation(h, a1);
  if (s1.min >= MIN_DELTA && contrast(a1, pitchRgb) >= MIN_PITCH_CONTRAST) {
    return { home: { colour: hex(h), pattern: 'plain' }, away: { colour: hex(a1), pattern: 'plain', kit: 'primary' }, decision: 'primary', minDelta: s1.min, worst: s1.worst };
  }
  const a2 = tryAway(away.kit.secondary);
  const s2 = separation(h, a2);
  if (s2.min >= MIN_DELTA) {
    return { home: { colour: hex(h), pattern: 'plain' }, away: { colour: hex(a2), pattern: 'plain', kit: 'secondary' }, decision: 'away alternate', minDelta: s2.min, worst: s2.worst };
  }
  const best = s2.min > s1.min ? { rgb: a2, s: s2, kit: 'secondary' as const } : { rgb: a1, s: s1, kit: 'primary' as const };
  return { home: { colour: hex(h), pattern: 'plain' }, away: { colour: hex(best.rgb), pattern: 'hoops', kit: best.kit }, decision: 'pattern added', minDelta: best.s.min, worst: best.s.worst };
}
