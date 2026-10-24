// Collision-avoided labels (PRD 15.2): each tag tries above, below, right and left of its anchor and takes the first
// spot that clears other labels and player dots. It keeps last frame's spot while that still works, so tags don't jitter.
import type { XY } from '../../lib/match';

let measurer: CanvasRenderingContext2D | OffscreenCanvasRenderingContext2D | null | undefined;
const measured = new Map<string, number>();

/**
 * A label's advance width at 100 px in a CSS font, measured on an offscreen canvas: no page layout, so it's safe to
 * call every frame. Returns null where canvases can't measure text.
 */
export function textWidth100(text: string, weight: number, family: string): number | null {
  const font = `${weight} 100px ${family}`;
  // Labels set figures tabular, so every digit is as wide as 0: live numbers don't need measuring again.
  text = text.replace(/[0-9]/g, '0');
  const key = `${font}|${text}`;
  const hit = measured.get(key);
  if (hit !== undefined) return hit;
  if (measurer === undefined) measurer = typeof OffscreenCanvas !== 'undefined' ? new OffscreenCanvas(1, 1).getContext('2d') : document.createElement('canvas').getContext('2d');
  if (!measurer) return null;
  measurer.font = font;
  const w = measurer.measureText(text).width;
  if (measured.size > 2000) measured.clear();
  measured.set(key, w);
  return w;
}

/** Forget measurements, when web fonts arrive and widths change. */
export const clearTextWidths = () => measured.clear();

/** A place a label may go, and which way its text runs from there. */
export interface Spot {
  at: XY;
  align?: 'start' | 'end';
}

export interface LabelIn {
  key: string;
  anchor: XY;
  text: string;
  size?: number;
  /** Preferred offset from the anchor, in SVG units. */
  dy?: number;
  /** The rendered width in SVG units, when it has been measured; otherwise it's estimated from the text. */
  width?: number;
  /**
   * The only places this label may go, best first, instead of the spots around its anchor: a ring's label goes above
   * the ring, below it or beside it, but never away from it.
   */
  spots?: readonly Spot[];
}

export interface LabelOut extends LabelIn {
  x: number;
  y: number;
  align?: 'start' | 'end';
}

export interface Box {
  x0: number;
  y0: number;
  x1: number;
  y1: number;
}

const DOT_R = 16;

/** A label's width in SVG units: measured if known, else estimated from its text, plus room for the halo. */
const widthOf = (text: string, size: number, measured?: number) => (measured ?? Math.max(24, text.length * size * 0.56)) + 10;

/** The space a label takes, halo included; `align` says which way the text runs from x. */
export function labelBox(x: number, y: number, text: string, size: number, align: 'middle' | 'start' | 'end' = 'middle', measured?: number): Box {
  const w = widthOf(text, size, measured);
  const h = size * 1.2;
  const x0 = align === 'start' ? x - 5 : align === 'end' ? x - w + 5 : x - w / 2;
  return { x0, y0: y - h * 0.82 - 3, x1: x0 + w, y1: y + h * 0.28 + 3 };
}

const overlap = (a: Box, b: Box) => Math.max(0, Math.min(a.x1, b.x1) - Math.max(a.x0, b.x0)) * Math.max(0, Math.min(a.y1, b.y1) - Math.max(a.y0, b.y0));
/** How much of a box lies outside the bounds. */
const outside = (b: Box, bounds: Box) => (b.x1 - b.x0) * (b.y1 - b.y0) - overlap(b, bounds);

/**
 * Places each label at the spot around its anchor that overlaps least: other labels count three times and player
 * dots twice, so a label covers a player only when every other spot is worse, and spots off the pitch count most.
 * `obstacles` are labels and cards already fixed in place. A label keeps last frame's spot unless another is clearly
 * better, so tags don't jitter.
 */
export function layoutLabels(items: readonly LabelIn[], dots: readonly XY[], memory: Map<string, number>, obstacles: readonly Box[] = [], bounds?: Box, dotR = DOT_R): LabelOut[] {
  const placed: Box[] = [...obstacles];
  const out: LabelOut[] = [];
  const dotBoxes = dots.map(([x, y]) => ({ x0: x - dotR, y0: y - dotR, x1: x + dotR, y1: y + dotR }));
  for (const item of items) {
    const size = item.size ?? 20;
    const [ax, ay] = item.anchor;
    const w = widthOf(item.text, size, item.width);
    const prefer = item.dy ?? -26;
    const away = prefer < 0 ? 40 : -26;
    const side = w / 2 + 20;
    const candidates: readonly Spot[] = item.spots ?? [
      { at: [ax, ay + prefer] },
      { at: [ax, ay + away] },
      { at: [ax + side, ay + 6] },
      { at: [ax - side, ay + 6] },
      { at: [ax, ay + (prefer < 0 ? prefer - 26 : prefer + 26)] },
      { at: [ax + side, ay + prefer] },
      { at: [ax - side, ay + prefer] },
      { at: [ax + side, ay + away] },
      { at: [ax - side, ay + away] },
      { at: [ax, ay + (prefer < 0 ? away + 26 : away - 26)] },
    ];
    const boxOf = (s: Spot) => labelBox(s.at[0], s.at[1], item.text, size, s.align ?? 'middle', item.width);
    /** How much a spot collides; the spot's rank only breaks ties. */
    const clash = (i: number) => {
      const b = boxOf(candidates[i]);
      let c = 0;
      for (const p of placed) c += overlap(p, b) * 3;
      // The anchor's own dot doesn't count: the label is about that player.
      for (const d of dotBoxes) if (Math.hypot((d.x0 + d.x1) / 2 - ax, (d.y0 + d.y1) / 2 - ay) > 1) c += overlap(d, b) * 2;
      if (bounds) c += outside(b, bounds) * 6;
      return c;
    };
    const clashes = candidates.map((_, i) => clash(i));
    const costs = clashes.map((c, i) => c + i * 4);
    let pick = costs.indexOf(Math.min(...costs));
    const remembered = memory.get(item.key);
    // The preferred spot whenever it's clear; otherwise last frame's spot while it's nearly as good, so tags don't jitter.
    if (clashes[0] === 0) pick = 0;
    else if (remembered !== undefined && remembered < candidates.length && clashes[remembered] <= clashes[pick] + 60) pick = remembered;
    memory.set(item.key, pick);
    const spot = candidates[pick];
    placed.push(boxOf(spot));
    out.push({ ...item, x: spot.at[0], y: spot.at[1], align: spot.align });
  }
  return out;
}
