import { useMemo, type CSSProperties, type ReactNode } from 'react';
import { cx } from '../../lib/cx';
import { FIELD_BOX, MARKINGS_TRANSFORM, PitchContext, VIEWBOX, project, type Orientation } from './geometry';

const chalk = { fill: 'none', stroke: 'var(--chalk)', strokeWidth: 2 } as const;

/**
 * Stripes and markings for a full 105 × 68 m pitch, turned for the vertical layout. With `drawIn`, each chalk line
 * draws itself in, one after another (the loading state, PRD 15.11).
 */
export function PitchMarkings({ orientation = 'h', drawIn = false }: { orientation?: Orientation; drawIn?: boolean }) {
  const [w, h] = orientation === 'h' ? [1110, 740] : [740, 1110];
  let n = 0;
  // Every line measures 100 so one dash pattern draws any of them; --i staggers them.
  const d = () => (drawIn ? { pathLength: 100, className: 'chalk-draw', style: { '--i': n++ } as CSSProperties } : {});
  return (
    <>
      <rect x={-30} y={-30} width={w} height={h} rx={10} style={{ fill: 'var(--edge)', transition: 'fill var(--dur-smooth)' }} />
      <g transform={MARKINGS_TRANSFORM[orientation]}>
        {Array.from({ length: 10 }, (_, i) => (
          <rect key={i} x={i * 105} y={0} width={105} height={680} style={{ fill: i % 2 ? 'var(--stripe)' : 'var(--pitch)', transition: 'fill var(--dur-smooth)' }} />
        ))}
        <g style={chalk}>
          <rect {...d()} x={0} y={0} width={1050} height={680} />
          <line {...d()} x1={525} y1={0} x2={525} y2={680} />
          <circle {...d()} cx={525} cy={340} r={91.5} />
          <rect {...d()} x={0} y={138.4} width={165} height={403.2} />
          <rect {...d()} x={0} y={248.4} width={55} height={183.2} />
          <rect {...d()} x={885} y={138.4} width={165} height={403.2} />
          <rect {...d()} x={995} y={248.4} width={55} height={183.2} />
          <path {...d()} d="M165 266.87 A91.5 91.5 0 0 1 165 413.13" />
          <path {...d()} d="M885 266.87 A91.5 91.5 0 0 0 885 413.13" />
          <rect {...d()} x={-20} y={303.4} width={20} height={73.2} />
          <rect {...d()} x={1050} y={303.4} width={20} height={73.2} />
        </g>
        <g style={{ fill: 'var(--chalk)' }}>
          <circle cx={525} cy={340} r={3.5} />
          <circle cx={110} cy={340} r={3.5} />
          <circle cx={940} cy={340} r={3.5} />
        </g>
      </g>
    </>
  );
}

interface PitchProps {
  /** Describes the scene for screen readers. */
  label: string;
  orientation?: Orientation;
  /** HTML drawn over the playing area, under the overlays: the control field. */
  field?: ReactNode;
  /** SVG overlays drawn in pitch units: players, ball, rings, arrows, tags. */
  children?: ReactNode;
  /** HTML layers over the whole pitch, such as the tier C canvas and its label layer. */
  layers?: ReactNode;
  chips?: ReactNode;
  corner?: ReactNode;
  scrim?: ReactNode;
  /** The feed stalled: the picture dims and holds its last frame (VIS-9). */
  dim?: boolean;
  className?: string;
  style?: CSSProperties;
}

/**
 * The 2D tactical pitch: markings, an optional control field, and an SVG overlay layer. It stays left to right in
 * right-to-left languages, because attacking direction is part of the picture (PRD 15.3).
 */
export function Pitch({ label, orientation = 'h', field, children, layers, chips, corner, scrim, dim = false, className, style }: PitchProps) {
  const geometry = useMemo(() => ({ o: orientation, P: ([x, y]: [number, number]) => project(orientation, x, y) }), [orientation]);
  const box = FIELD_BOX[orientation];
  // On the vertical pitch (phones) the chips sit in a row above it: over the pitch they would cover a goal and a
  // keeper, and there is no empty corner on a narrow screen.
  const outside = orientation === 'v';
  return (
    <PitchContext.Provider value={geometry}>
      {outside && chips && <div className="pitch-chips pitch-chips-above">{chips}</div>}
      <div className={cx('pitch', orientation === 'v' && 'pitch-v', dim && 'pitch-dim', className)} dir="ltr" style={style}>
        <svg viewBox={VIEWBOX[orientation]} role="img" aria-label={label} className="pitch-layer">
          <PitchMarkings orientation={orientation} />
        </svg>
        {field && (
          <div className="pitch-field" aria-hidden="true" style={{ left: `${box.left * 100}%`, top: `${box.top * 100}%`, width: `${box.width * 100}%`, height: `${box.height * 100}%` }}>
            {field}
          </div>
        )}
        {children && (
          <svg viewBox={VIEWBOX[orientation]} className="pitch-layer pitch-overlays">
            {children}
          </svg>
        )}
        {layers}
        {scrim}
        {!outside && chips && <div className="pitch-chips">{chips}</div>}
        {corner && <div className="pitch-corner">{corner}</div>}
      </div>
    </PitchContext.Provider>
  );
}
