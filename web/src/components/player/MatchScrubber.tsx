import { useRef, useState, type KeyboardEvent, type PointerEvent } from 'react';
import type { Goal, Moment, PeriodInfo } from '../../lib/player/api';
import { clockOf, type Position } from '../../lib/player/clock';

interface MatchScrubberProps {
  periods: readonly PeriodInfo[];
  total: number;
  g: number;
  toMatch: (p: Position) => number;
  toPosition: (g: number) => Position;
  moments: readonly Moment[];
  goals: readonly Goal[];
  selected: string | null;
  label: string;
  halfLabels: Record<number, string>;
  onSeek: (g: number) => void;
  onMoment: (m: Moment) => void;
}

/** The space between the halves on the bar, as a share of its width. */
const GAP = 0.012;

/**
 * The whole match on one bar (PRD 15.2): both halves end to end, a tick for every moment the models found (taller the
 * stronger, lime once the crew has explained it), a ball over every goal, and the playhead. Drag or click to seek;
 * as a slider, arrow keys move 10 s and Page keys a minute.
 */
export function MatchScrubber({ periods, total, g, toMatch, toPosition, moments, goals, selected, label, halfLabels, onSeek, onMoment }: MatchScrubberProps) {
  const barRef = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState<number | null>(null);
  const dragging = useRef(false);
  const halves = periods.length;
  const usable = 1 - GAP * Math.max(0, halves - 1);
  // Where match time sits on the bar, with the gap between halves.
  const xOf = (gm: number) => {
    let start = 0;
    for (let i = 0; i < halves; i++) {
      const d = periods[i].duration_ms;
      if (gm <= start + d || i === halves - 1) return ((start + Math.min(d, gm - start)) / total) * usable + GAP * i;
      start += d;
    }
    return 1;
  };
  const gOf = (x: number) => {
    let start = 0;
    let left = 0;
    for (let i = 0; i < halves; i++) {
      const w = (periods[i].duration_ms / total) * usable;
      if (x <= left + w || i === halves - 1) return start + Math.max(0, Math.min(1, (x - left) / w)) * periods[i].duration_ms;
      start += periods[i].duration_ms;
      left += w + GAP;
    }
    return total;
  };
  const xAt = (e: PointerEvent<HTMLDivElement>) => {
    const r = barRef.current!.getBoundingClientRect();
    return Math.max(0, Math.min(1, (e.clientX - r.left) / r.width));
  };
  const onDown = (e: PointerEvent<HTMLDivElement>) => {
    dragging.current = true;
    e.currentTarget.setPointerCapture(e.pointerId);
    onSeek(gOf(xAt(e)));
  };
  const onMove = (e: PointerEvent<HTMLDivElement>) => {
    const x = xAt(e);
    setHover(x);
    if (dragging.current) onSeek(gOf(x));
  };
  const onUp = () => {
    dragging.current = false;
  };
  const onKey = (e: KeyboardEvent<HTMLDivElement>) => {
    const step = { ArrowLeft: -10_000, ArrowRight: 10_000, PageDown: -60_000, PageUp: 60_000 }[e.key];
    if (step !== undefined) onSeek(Math.max(0, Math.min(total, g + step)));
    else if (e.key === 'Home') onSeek(0);
    else if (e.key === 'End') onSeek(total);
    else return;
    e.preventDefault();
  };
  const here = toPosition(g);
  let left = 0;

  return (
    <div className="scrubber">
      <div
        ref={barRef}
        className="scrubber-bar"
        role="slider"
        tabIndex={0}
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={Math.round(total / 1000)}
        aria-valuenow={Math.round(g / 1000)}
        aria-valuetext={`${clockOf(here)}, ${halfLabels[here.period] ?? ''}`}
        onPointerDown={onDown}
        onPointerMove={onMove}
        onPointerUp={onUp}
        onPointerCancel={onUp}
        onPointerLeave={() => setHover(null)}
        onKeyDown={onKey}
      >
        {periods.map((p) => {
          const w = (p.duration_ms / total) * usable;
          const el = (
            <div key={p.period} className="scrubber-half" style={{ left: `${left * 100}%`, width: `${w * 100}%` }}>
              <div className="scrubber-fill" style={{ transform: `scaleX(${Math.max(0, Math.min(1, (g - toMatch({ period: p.period, t_ms: 0 })) / p.duration_ms)).toFixed(4)})` }} />
            </div>
          );
          left += w + GAP;
          return el;
        })}
        <svg className="scrubber-ticks" viewBox="0 0 1000 40" preserveAspectRatio="none" aria-hidden="true">
          {moments.map((m) => {
            const x = xOf(toMatch({ period: m.period, t_ms: m.t_start_ms })) * 1000;
            const h = 10 + Math.min(1, m.strength / 3) * 18;
            const on = m.candidate_id === selected;
            return <line key={m.candidate_id} x1={x} x2={x} y1={40 - h} y2={40} className={on ? 'tick tick-on' : m.graphics === 'published' ? 'tick tick-built' : 'tick'} />;
          })}
        </svg>
        {goals.map((goal) => (
          <span key={goal.event_id} className="scrubber-goal" style={{ left: `${xOf(toMatch(goal)) * 100}%` }} aria-hidden="true" />
        ))}
        <span className="scrubber-head" style={{ left: `${xOf(g) * 100}%` }} aria-hidden="true" />
        {hover !== null && (
          <span className="scrubber-hover mono" style={{ left: `${hover * 100}%` }} aria-hidden="true">
            {clockOf(toPosition(gOf(hover)))}
          </span>
        )}
      </div>
      <div className="scrubber-moments" aria-hidden="true">
        {moments
          .filter((m) => m.outcome === 'goal')
          .map((m) => (
            <button key={m.candidate_id} type="button" tabIndex={-1} className="scrubber-pin" style={{ left: `${xOf(toMatch({ period: m.period, t_ms: m.t_start_ms })) * 100}%` }} onClick={() => onMoment(m)} />
          ))}
      </div>
    </div>
  );
}
