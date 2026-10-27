// The match player's clock: one position across the whole match, both halves end to end. The frame loop moves it
// every display frame (PRD 16.2); React hears about it ten times a second. It holds still while the frames it needs
// are still on their way, so a jump never shows an empty pitch ticking on.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { PRIO, onFrame } from '../frame-loop';
import type { PeriodInfo } from './api';

export interface Position {
  period: number;
  t_ms: number;
}

/** Converts between a position in a period and match time: milliseconds from kick-off with both halves end to end. */
export function matchTime(periods: readonly PeriodInfo[]) {
  const starts: number[] = [];
  let total = 0;
  for (const p of periods) {
    starts.push(total);
    total += p.duration_ms;
  }
  const toMatch = (pos: Position) => {
    const i = periods.findIndex((p) => p.period === pos.period);
    return i < 0 ? 0 : starts[i] + Math.max(0, Math.min(periods[i].duration_ms, pos.t_ms));
  };
  const toPosition = (g: number): Position => {
    let i = periods.length - 1;
    while (i > 0 && g < starts[i]) i--;
    const p = periods[Math.max(0, i)];
    return p ? { period: p.period, t_ms: Math.max(0, Math.min(p.duration_ms, g - starts[Math.max(0, i)])) } : { period: 1, t_ms: 0 };
  };
  return { total, starts, toMatch, toPosition };
}

/** The broadcast clock, as the API writes it: 63:21, or 45+2:10 in stoppage time. */
export function clockOf({ period, t_ms }: Position): string {
  const base = (period - 1) * 45;
  const s = Math.floor(t_ms / 1000);
  const min = Math.floor(s / 60);
  const sec = String(s % 60).padStart(2, '0');
  return min >= 45 ? `${base + 45}+${min - 45}:${sec}` : `${base + min}:${sec}`;
}

export const SPEEDS = [1, 2, 4, 8] as const;
export type Speed = (typeof SPEEDS)[number];

export interface MatchClock {
  /** Match time in ms, as last rendered (ten times a second). */
  g: number;
  playing: boolean;
  speed: Speed;
  /** Waiting for frames at the current time. */
  waiting: boolean;
  /** Match time now, for the frame loop. */
  now: () => number;
  play: () => void;
  pause: () => void;
  toggle: () => void;
  seek: (g: number, play?: boolean) => void;
  setSpeed: (s: Speed) => void;
}

/**
 * The clock for one match. `ready(g)` says whether the frames for a time are here; `want(g)` asks for them. With
 * `autoplay` it starts playing as soon as they are. Playback stops at full time.
 */
export function useMatchClock(total: number, start: number, ready: (g: number) => boolean, want: (g: number) => void, autoplay = false): MatchClock {
  const gRef = useRef(start);
  const playingRef = useRef(autoplay);
  const speedRef = useRef<Speed>(1);
  const [g, setG] = useState(start);
  const [playing, setPlaying] = useState(autoplay);
  const [speed, setSpeedState] = useState<Speed>(1);
  const [waiting, setWaiting] = useState(false);
  const readyRef = useRef(ready);
  const wantRef = useRef(want);
  readyRef.current = ready;
  wantRef.current = want;

  useEffect(() => {
    let last = performance.now();
    let rendered = 0;
    const stop = onFrame((now) => {
      // A slow device still plays in real time; a tab coming back from the background doesn't leap ahead.
      const dt = Math.min(1000, now - last);
      last = now;
      const here = readyRef.current(gRef.current);
      wantRef.current(gRef.current);
      if (playingRef.current && here) {
        gRef.current = Math.min(total, gRef.current + dt * speedRef.current);
        if (gRef.current >= total) {
          playingRef.current = false;
          setPlaying(false);
        }
      }
      if (now - rendered > 100) {
        rendered = now;
        setG(gRef.current);
        setWaiting(!here);
      }
    }, PRIO.clock);
    return stop;
  }, [total]);

  const seek = useCallback(
    (to: number, play?: boolean) => {
      gRef.current = Math.max(0, Math.min(total, to));
      wantRef.current(gRef.current);
      setG(gRef.current);
      if (play !== undefined) {
        playingRef.current = play;
        setPlaying(play);
      }
    },
    [total],
  );

  return useMemo(
    () => ({
      g,
      playing,
      speed,
      waiting,
      now: () => gRef.current,
      play: () => {
        if (gRef.current >= total) gRef.current = 0;
        playingRef.current = true;
        setPlaying(true);
      },
      pause: () => {
        playingRef.current = false;
        setPlaying(false);
      },
      toggle: () => {
        if (!playingRef.current && gRef.current >= total) gRef.current = 0;
        playingRef.current = !playingRef.current;
        setPlaying(playingRef.current);
      },
      seek,
      setSpeed: (s: Speed) => {
        speedRef.current = s;
        setSpeedState(s);
      },
    }),
    [g, playing, speed, waiting, seek, total],
  );
}
