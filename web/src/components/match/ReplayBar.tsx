import { useEffect, useRef, type ReactNode } from 'react';
import { FRAME_S, SPEEDS, type MatchClock, type Speed } from '../../lib/feed';
import { onFrame } from '../../lib/frame-loop';
import { useI18n } from '../../lib/i18n';
import { MOMENTS, T_END, stepAt } from '../../lib/match';
import { Button } from '../ui';

const fmt = (t: number) => `63:${t < 10 ? '0' : ''}${t.toFixed(1)}`;

const Icon = ({ d, label }: { d: string; label?: string }) => (
  <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
    {label && <title>{label}</title>}
    <path d={d} style={{ fill: 'currentColor' }} />
  </svg>
);

const PLAY = 'M4 2 L14 8 L4 14 Z';
const PAUSE = 'M3 2 H6.5 V14 H3 Z M9.5 2 H13 V14 H9.5 Z';
const PREV = 'M3 2 H5 V14 H3 Z M14 2 V14 L6 8 Z';
const NEXT = 'M11 2 H13 V14 H11 Z M2 2 V14 L10 8 Z';
const BACK = 'M9 3 V13 L3 8 Z M14 3 V13 L9 8 Z';
const FWD = 'M7 3 V13 L13 8 Z M2 3 V13 L7 8 Z';

/**
 * Replay controls (PRD 15.1): play, step a frame, jump between moments, speeds from 0.25x to 60x, and a scrubber
 * with the moment's beats marked. The bar stays left to right in every language: it follows the match clock. `tools`
 * go at the end of the controls, such as the snapshot buttons.
 */
export function ReplayBar({ clock, tools }: { clock: MatchClock; tools?: ReactNode }) {
  const { ui, pack } = useI18n();
  // The scrubber's fill and head follow the clock every frame by transform alone, so they glide without repainting
  // the page; the native slider over them is invisible and handles pointer, keyboard and screen readers.
  const fill = useRef<HTMLDivElement>(null);
  const head = useRef<HTMLDivElement>(null);
  const now = clock.now;
  useEffect(() => {
    let last = '';
    return onFrame(() => {
      const u = Math.max(0, Math.min(1, now() / T_END)).toFixed(4);
      if (u === last) return;
      last = u;
      if (fill.current) fill.current.style.transform = `scaleX(${u})`;
      if (head.current) head.current.style.transform = `translateX(${Number(u) * 100}%)`;
    });
  }, [now]);
  const step = stepAt(clock.t);
  const beat = step > 0 ? pack.steps[step - 1] : '';
  const live = clock.live;
  return (
    <div className="replay-bar" dir="ltr">
      <div className="replay-controls">
        <Button icon round variant="ghost" onClick={() => clock.jump(-1)} aria-label="Previous moment" disabled={live}>
          <Icon d={PREV} />
        </Button>
        <Button icon round variant="ghost" onClick={() => clock.step(-1)} aria-label="Back one frame" disabled={live}>
          <Icon d={BACK} />
        </Button>
        <Button variant="solid" icon round onClick={clock.toggle} aria-label={clock.playing ? ui.pause : ui.play}>
          <span key={clock.playing ? 'pause' : 'play'} className="anim-pop" style={{ display: 'inline-flex' }}>
            <Icon d={clock.playing ? PAUSE : PLAY} />
          </span>
        </Button>
        <Button icon round variant="ghost" onClick={() => clock.step(1)} aria-label="Forward one frame" disabled={live}>
          <Icon d={FWD} />
        </Button>
        <Button icon round variant="ghost" onClick={() => clock.jump(1)} aria-label="Next moment" disabled={live}>
          <Icon d={NEXT} />
        </Button>
        {live ? (
          clock.behind > 0.3 ? (
            <Button variant="primary" className="btn-sm" onClick={clock.goLive}>
              Go live · {clock.behind.toFixed(0)} s behind
            </Button>
          ) : (
            <span className="map-chip">Live · 1.5 s buffer</span>
          )
        ) : (
          <>
            <label htmlFor="replay-speed" className="sr-only">
              Playback speed
            </label>
            <select id="replay-speed" className="select speed-select" value={clock.speed} onChange={(e) => clock.setSpeed(Number(e.target.value) as Speed)}>
              {SPEEDS.map((s) => (
                <option key={s} value={s}>
                  {s}×
                </option>
              ))}
            </select>
          </>
        )}
        <span className="mono tabular spacer" style={{ fontSize: 14 }} aria-hidden="true">
          {fmt(clock.t)}
        </span>
        {tools}
      </div>
      <div className="timeline">
        <div className="timeline-track">
          {MOMENTS.map((m, i) => {
            const reached = clock.t >= m;
            return (
              <button
                key={m}
                type="button"
                className="timeline-marker"
                data-reached={reached}
                data-row={i % 2}
                style={{ left: `calc(8px + (100% - 16px) * ${m / T_END})` }}
                onClick={() => clock.scrub(m)}
                disabled={live}
                aria-label={`Jump to ${ui.markers[i]}, ${fmt(m)}`}
              >
                <span key={String(reached)} className={reached ? 'marker-dot anim-pop' : 'marker-dot'} data-reached={reached} />
                {ui.markers[i]}
              </button>
            );
          })}
          <label htmlFor="match-scrub" className="sr-only">
            Moment time
          </label>
          <div className="scrub">
            <div className="scrub-rail" aria-hidden="true">
              <div className="scrub-track">
                <div ref={fill} className="scrub-fill" />
              </div>
              <div ref={head} className="scrub-head">
                <span className="scrub-thumb" />
              </div>
            </div>
            <input
              id="match-scrub"
              className="scrub-input"
              type="range"
              min={0}
              max={Math.round(T_END / FRAME_S)}
              step={1}
              value={Math.round(clock.t / FRAME_S)}
              disabled={live}
              aria-valuetext={`${fmt(clock.t)}${beat ? `, ${beat}` : ''}`}
              onChange={(e) => clock.scrub(Number(e.target.value) * FRAME_S)}
            />
          </div>
        </div>
      </div>
    </div>
  );
}
