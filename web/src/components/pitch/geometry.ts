import { createContext, useContext } from 'react';
import type { XY } from '../../lib/match';

/**
 * Pitch SVGs use 10 units per metre with a 3 m margin for the goals and labels. Horizontal: Kestrel Bay attack
 * left to right. Vertical, for phones in portrait (PRD 15.1): Kestrel Bay attack upwards.
 */
export type Orientation = 'h' | 'v';

export const VIEWBOX: Record<Orientation, string> = { h: '-30 -30 1110 740', v: '-30 -30 740 1110' };
export const SIZE: Record<Orientation, readonly [number, number]> = { h: [1110, 740], v: [740, 1110] };

/** Metres to SVG units. */
export const project = (o: Orientation, x: number, y: number): XY => (o === 'h' ? [x * 10, (68 - y) * 10] : [(68 - y) * 10, (105 - x) * 10]);

/** The horizontal markings, turned for the vertical pitch: (x, y) becomes (y, 1050 - x). */
export const MARKINGS_TRANSFORM: Record<Orientation, string | undefined> = { h: undefined, v: 'translate(0 1050) rotate(-90)' };

/** Where the playing area sits inside the viewBox, as fractions, for HTML layers over the SVG. */
export const FIELD_BOX: Record<Orientation, { left: number; top: number; width: number; height: number }> = {
  h: { left: 30 / 1110, top: 30 / 740, width: 1050 / 1110, height: 680 / 740 },
  v: { left: 30 / 740, top: 30 / 1110, width: 680 / 740, height: 1050 / 1110 },
};

/** Arrowhead points for a line from a to b, both in SVG units. */
export function arrowHead(a: XY, b: XY, size = 20): string {
  const len = Math.hypot(b[0] - a[0], b[1] - a[1]) || 1;
  const ux = (b[0] - a[0]) / len;
  const uy = (b[1] - a[1]) / len;
  const bx = b[0] - ux * size;
  const by = b[1] - uy * size;
  const half = size / 2;
  return [
    [b[0], b[1]],
    [bx - uy * half, by + ux * half],
    [bx + uy * half, by - ux * half],
  ]
    .map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`)
    .join(' ');
}

export const translate = ([x, y]: XY) => `translate(${x.toFixed(1)}px, ${y.toFixed(1)}px)`;

export interface PitchGeometry {
  o: Orientation;
  /** Metres to SVG units for this pitch. */
  P: (p: XY) => XY;
}

export const PitchContext = createContext<PitchGeometry>({ o: 'h', P: (p) => project('h', p[0], p[1]) });
export const usePitch = () => useContext(PitchContext);
