import { useEffect, useMemo, useRef } from 'react';
import { FIELD_GRID, contours, type Grid } from '../../lib/field';
import type { Theme } from '../../lib/prefs';
import { usePitch, type Orientation } from './geometry';

interface ControlFieldProps {
  /** Kestrel Bay control probability per cell, row by row from the top touchline. */
  field: Float32Array | null;
  grid?: Grid;
  /** 0–1, scaled by the theme's --field-max. */
  strength?: number;
  orientation?: Orientation;
  /** Redraws when the theme's colours change. */
  theme: Theme;
  /** Changes every frame, so a reused field buffer is redrawn. */
  stamp: number;
}

const rgbOf = (el: Element, name: string) =>
  getComputedStyle(el)
    .getPropertyValue(name)
    .trim()
    .split(/\s+/)
    .map(Number);

/**
 * The space-control field: Kestrel Bay's colour where they control space and Ashmoor's where Ashmoor do, fading
 * through transparent where it's contested, so the neutral midpoint is the pitch itself (PRD 16.3). One canvas pixel
 * per cell; the browser's smooth scaling turns the grid into a continuous surface.
 */
export function ControlField({ field, grid = FIELD_GRID, strength = 1, orientation = 'h', theme, stamp }: ControlFieldProps) {
  const ref = useRef<HTMLCanvasElement>(null);
  const colours = useRef<{ kes: number[]; ash: number[]; max: number } | null>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    colours.current = { kes: rgbOf(el, '--kes-rgb'), ash: rgbOf(el, '--ash-rgb'), max: Number(getComputedStyle(el).getPropertyValue('--field-max')) || 0.55 };
  }, [theme]);

  useEffect(() => {
    const el = ref.current;
    const c = colours.current;
    if (!el || !c || !field) return;
    const ctx = el.getContext('2d');
    if (!ctx) return;
    const w = el.width;
    const h = el.height;
    const img = ctx.createImageData(w, h);
    for (let r = 0; r < grid.rows; r++) {
      for (let col = 0; col < grid.cols; col++) {
        const p = field[r * grid.cols + col];
        const a = Math.min(1, Math.abs(p - 0.5) * 2 * strength) * c.max;
        const rgb = p >= 0.5 ? c.kes : c.ash;
        // Vertical: x becomes the row from the bottom, y the column from the left.
        const px = orientation === 'h' ? col : r;
        const py = orientation === 'h' ? r : grid.cols - 1 - col;
        const i = (py * w + px) * 4;
        img.data[i] = rgb[0];
        img.data[i + 1] = rgb[1];
        img.data[i + 2] = rgb[2];
        img.data[i + 3] = Math.round(a * 255);
      }
    }
    ctx.putImageData(img, 0, 0);
  }, [field, grid, strength, orientation, stamp, theme]);

  const [w, h] = orientation === 'h' ? [grid.cols, grid.rows] : [grid.rows, grid.cols];
  return <canvas ref={ref} className="field-canvas" width={w} height={h} />;
}

/**
 * 25%, 50% and 75% control contours, so the field reads without colour (PRD 10.1, VIS-5). They are recomputed at the
 * data's 25 Hz rather than every display frame: between data frames the paths stay the same and nothing repaints.
 */
export function Contours({ field, grid = FIELD_GRID, levels = [0.25, 0.5, 0.75], stamp }: { field: Float32Array | null; grid?: Grid; levels?: readonly number[]; stamp: number }) {
  const { P } = usePitch();
  const dataFrame = Math.floor(stamp / 40);
  const levelKey = levels.join(',');
  const paths = useMemo(
    () =>
      field
        ? levels.map((level) => ({
            level,
            d: contours(field, grid, level)
              .map(([a, b]) => {
                const [x1, y1] = P(a);
                const [x2, y2] = P(b);
                return `M${x1.toFixed(1)} ${y1.toFixed(1)}L${x2.toFixed(1)} ${y2.toFixed(1)}`;
              })
              .join(''),
          }))
        : [],
    // The field is read once per data frame on purpose; it changes every display frame.
    [dataFrame, levelKey, grid, P, field === null],
  );
  if (!field) return null;
  return (
    <g aria-hidden="true" className="contours">
      {paths.map(({ level, d }) => (
        <path key={level} d={d} className={level === 0.5 ? 'contour contour-mid' : 'contour'} />
      ))}
    </g>
  );
}
