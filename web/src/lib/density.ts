import type { ActiveOverlay, OverlayKind } from './feed';
import type { Density, Mode } from './prefs';

/**
 * Adaptive density (PRD 8.2): the viewer hides whole groups of pitch graphics, one at a time, and on this device the
 * app remembers it for each mode. Hiding two groups tells it the mode is too busy, so that mode also steps down one
 * density level. What-if worlds and changed decisions always show everything: the viewer asked to see them.
 */
export type OverlayGroup = 'field' | 'rings' | 'runs' | 'passes' | 'line' | 'tags';
export const OVERLAY_GROUPS: readonly OverlayGroup[] = ['field', 'rings', 'runs', 'passes', 'line', 'tags'];

export const GROUP_LABEL: Record<OverlayGroup, string> = {
  field: 'Space field',
  rings: 'Space rings',
  runs: 'Runs',
  passes: 'Passes',
  line: 'Back line',
  tags: 'Player tags',
};

/** Which group each pitch graphic belongs to. Captions, cards and charts sit off the pitch and are never hidden. */
export const GROUP_OF: Partial<Record<OverlayKind, OverlayGroup>> = {
  gap_ring: 'rings',
  run_arrow: 'runs',
  pass_line: 'passes',
  offside_line: 'line',
  shape_lines: 'line',
  player_tag: 'tags',
  badge: 'tags',
};

/** What the app has learned, per mode: the groups hidden there. */
export type HiddenByMode = Partial<Record<Mode, readonly OverlayGroup[]>>;

/** Hiding this many groups in a mode steps its density down a level. */
export const STEP_DOWN_AT = 2;

const LEVELS: readonly Density[] = ['minimal', 'standard', 'rich'];

/** The density a mode draws at: the viewer's choice, one level lower once they've hidden enough there. */
export function learnedDensity(base: Density, hidden: readonly OverlayGroup[], adapt: boolean): Density {
  if (!adapt || hidden.length < STEP_DOWN_AT) return base;
  return LEVELS[Math.max(0, LEVELS.indexOf(base) - 1)];
}

/** The overlays left to draw once the hidden groups are taken out. */
export function withoutHidden(items: ActiveOverlay[], hidden: ReadonlySet<OverlayGroup>): ActiveOverlay[] {
  if (!hidden.size) return items;
  return items.filter((a) => {
    const group = GROUP_OF[a.overlay.kind];
    return !group || !hidden.has(group);
  });
}

/** The groups a mode's feed actually draws, so the menu offers only what's there. The field is always there. */
export function groupsIn(kinds: Iterable<OverlayKind>): OverlayGroup[] {
  const present = new Set<OverlayGroup>(['field']);
  for (const k of kinds) {
    const g = GROUP_OF[k];
    if (g) present.add(g);
  }
  return OVERLAY_GROUPS.filter((g) => present.has(g));
}

/** A list in plain English: "runs", "runs and passes", "runs, passes and tags". */
export function listOf(groups: readonly OverlayGroup[]): string {
  const words = groups.map((g, i) => (i === 0 ? GROUP_LABEL[g] : GROUP_LABEL[g].toLowerCase()));
  return words.length < 2 ? (words[0] ?? '') : `${words.slice(0, -1).join(', ')} and ${words[words.length - 1]}`;
}

/** Saved groups from an older or edited store: only known groups, no repeats. */
export function cleanHidden(raw: unknown): HiddenByMode {
  if (!raw || typeof raw !== 'object') return {};
  const out: HiddenByMode = {};
  for (const [mode, groups] of Object.entries(raw as Record<string, unknown>)) {
    if (!Array.isArray(groups)) continue;
    const kept = [...new Set(groups.filter((g): g is OverlayGroup => OVERLAY_GROUPS.includes(g as OverlayGroup)))];
    if (kept.length) out[mode as Mode] = kept;
  }
  return out;
}
