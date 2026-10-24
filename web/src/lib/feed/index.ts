// React glue for the feed: the shared store, the source, and the match clock that drives every layer (VIS-1).
import { startTransition, useCallback, useEffect, useRef, useState, useSyncExternalStore } from 'react';
import { PRIO, onFrame } from '../frame-loop';
import { MOMENTS, T_END } from '../match';
import { T_LOOP, ms, tOf } from './emitter';
import { startSource, type SourceHandle, type SourceSpec } from './sources';
import { getStore, type FeedStore } from './store';

export { getStore, textOf, a11yOf, momentT, type ActiveOverlay, type FeedStore, type Retraction } from './store';
export { showcaseFeed, showcaseJsonl, T_LOOP, HOLD, ms, tOf } from './emitter';
export { sourceFromLocation, type SourceSpec, type SourceHandle } from './sources';
export { frameState, type FrameState } from './frame-state';
export { LIVE_BUFFER_MS } from './store';
export type { Overlay, OverlayKind, ClientMessage, TrackedFrame, Approval } from './types';

export const SPEEDS = [0.25, 0.5, 1, 2, 4, 10, 60] as const;
export type Speed = (typeof SPEEDS)[number];
/** One 25 Hz frame. */
export const FRAME_S = 0.04;
const STALL_AFTER_MS = 2000;
const RECOVERED_FOR_MS = 3500;
/** While playing, React hears about the clock ten times a second; renderers read it every frame through `now()`. */
const COMMIT_MS = 100;

/** The shared store; re-renders when overlays, retractions or status change. */
export function useFeedStore(): FeedStore {
  const store = getStore();
  useSyncExternalStore(store.subscribe, store.getVersion);
  return store;
}

/** Starts a feed source for as long as the component is mounted, and restarts it when the spec changes. */
export function useFeedSource(spec: SourceSpec): SourceHandle | null {
  const store = getStore();
  const [handle, setHandle] = useState<SourceHandle | null>(null);
  // Compared by value, so an equal spec built on every render doesn't restart the source.
  const key = JSON.stringify(spec);
  useEffect(() => {
    const h = startSource(store, JSON.parse(key) as SourceSpec);
    setHandle(h);
    return () => {
      h.stop();
      if (h.live) store.loadReplay();
    };
  }, [store, key]);
  return handle;
}

/** Reads ?t=4.5 (start paused at that moment time) for tests and deep links. */
function initialFromLocation(): { t: number; paused: boolean } {
  const query = new URLSearchParams(window.location.hash.split('?')[1] ?? '');
  const t = Number(query.get('t'));
  return Number.isFinite(t) && query.has('t') ? { t: Math.max(0, Math.min(T_END, t)), paused: true } : { t: 0, paused: query.get('play') === '0' };
}

/** A clock a renderer can follow: `t` for text and React, `now()` for drawing every display frame. */
export interface TimeSource {
  /** Moment time in seconds after 63:00 for React-rendered text: exact when paused, refreshed ten times a second while playing. */
  t: number;
  /** The exact moment time for this display frame. */
  now: () => number;
  /**
   * The clock entrances and live indicators run on, in milliseconds. Omitted, it's the display frame's own time; a
   * clip being rendered frame by frame passes its timeline, so every frame is exact however long it takes to capture.
   */
  wall?: () => number;
}

/** A clock that stands still, for static previews. */
export const fixedTime = (t: number): TimeSource => ({ t, now: () => t });

export interface MatchClock extends TimeSource {
  t_ms: number;
  playing: boolean;
  speed: Speed;
  live: boolean;
  /** No data for 2 s: the picture holds its last frame (VIS-9). */
  stalled: boolean;
  /** Just recovered from a stall; `missed` graphics were dropped meanwhile. */
  recovered: boolean;
  missed: number;
  /** Seconds behind the live edge when paused in a live feed. */
  behind: number;
  toggle: () => void;
  play: () => void;
  pause: () => void;
  scrub: (t: number) => void;
  step: (frames: number) => void;
  jump: (dir: 1 | -1) => void;
  setSpeed: (s: Speed) => void;
  goLive: () => void;
}

/**
 * One clock for every layer (VIS-1). Replay runs from 0.25x to 60x with scrubbing and frame steps and loops the
 * moment; live follows the server clock 1.5 s behind the newest data and never extrapolates past it. It moves first
 * in each display frame, so everything drawn in that frame reads the same time.
 */
export function useMatchClock(store: FeedStore, live: boolean, { loop = true }: { loop?: boolean } = {}): MatchClock {
  const init = useRef(initialFromLocation()).current;
  const [t, setT] = useState(init.t);
  const [playing, setPlaying] = useState(!init.paused);
  const [speed, setSpeedState] = useState<Speed>(1);
  const [stalled, setStalled] = useState(false);
  const [recovered, setRecovered] = useState(false);
  const [missed, setMissed] = useState(0);
  const [behind, setBehind] = useState(0);
  const tRef = useRef(t);
  const playingRef = useRef(playing);
  playingRef.current = playing;
  const speedRef = useRef(speed);
  speedRef.current = speed;
  const committedAt = useRef(0);
  const stallRef = useRef<{
    since: number | null;
    dropped: number;
    recoveredAt: number;
  }>({ since: null, dropped: 0, recoveredAt: 0 });
  const pausedAt = useRef<number | null>(null);

  /**
   * Moves the clock. `commit` also re-renders React: at once for the viewer's own actions, and for playback at most
   * every 100 ms as a transition, so React renders the text in slices between frames instead of holding one up.
   */
  const set = useCallback((v: number, commit = true, urgent = true) => {
    tRef.current = v;
    if (!commit) return;
    committedAt.current = performance.now();
    if (urgent) setT(v);
    else startTransition(() => setT(v));
  }, []);

  useEffect(() => {
    let last = performance.now();
    const tick = (now: number) => {
      const dt = Math.min(0.25, Math.max(0, (now - last) / 1000));
      last = now;
      const due = now - committedAt.current >= COMMIT_MS;
      if (live) {
        const target = store.liveTarget();
        const latest = store.frames.latest;
        const s = stallRef.current;
        const isStalled = performance.now() - store.lastDataAt > STALL_AFTER_MS;
        if (isStalled && s.since === null) {
          s.since = now;
          s.dropped = store.dropped;
        }
        if (!isStalled && s.since !== null) {
          s.since = null;
          s.recoveredAt = now;
          setMissed(store.dropped - s.dropped);
        }
        // Same values bail out in React, so these only re-render when the state actually changes.
        setStalled(isStalled);
        setRecovered(s.recoveredAt > 0 && now - s.recoveredAt < RECOVERED_FOR_MS);
        if (target !== null && latest) {
          const edge = Math.min(target, latest.t_ms + 200);
          if (playing) {
            pausedAt.current = null;
            set(Math.max(0, Math.min(T_END, tOf(edge))), due, false);
            if (due) setBehind(0);
          } else {
            pausedAt.current ??= tRef.current;
            if (due) {
              committedAt.current = now;
              setBehind(Math.max(0, tOf(edge) - tRef.current));
            }
          }
        }
      } else if (playing) {
        let next = tRef.current + dt * speedRef.current;
        let commit = due;
        if (next > T_LOOP) {
          commit = true;
          if (loop) next = 0;
          else {
            next = T_END;
            setPlaying(false);
          }
        }
        set(next, commit, next !== 0 && next !== T_END);
      }
    };
    return onFrame(tick, PRIO.clock);
  }, [live, playing, loop, store, set]);

  const toggle = useCallback(() => {
    if (playingRef.current) {
      setPlaying(false);
      set(tRef.current);
      return;
    }
    if (!live && tRef.current >= T_END) set(0);
    setPlaying(true);
  }, [live, set]);
  const play = useCallback(() => setPlaying(true), []);
  const pause = useCallback(() => {
    setPlaying(false);
    set(tRef.current);
  }, [set]);
  const scrub = useCallback(
    (v: number) => {
      setPlaying(false);
      set(Math.max(0, Math.min(T_END, v)));
    },
    [set],
  );
  const step = useCallback(
    (n: number) => {
      setPlaying(false);
      set(Math.max(0, Math.min(T_END, Math.round((tRef.current + n * FRAME_S) / FRAME_S) * FRAME_S)));
    },
    [set],
  );
  const jump = useCallback(
    (dir: 1 | -1) => {
      const now = tRef.current;
      const targets = [0, ...MOMENTS];
      const next = dir > 0 ? targets.find((m) => m > now + 0.05) : [...targets].reverse().find((m) => m < now - 0.05);
      setPlaying(false);
      set(next ?? (dir > 0 ? T_END : 0));
    },
    [set],
  );
  const setSpeed = useCallback((s: Speed) => setSpeedState(s), []);
  const goLive = useCallback(() => setPlaying(true), []);
  const now = useCallback(() => Math.min(tRef.current, T_END), []);

  const shown = Math.min(t, T_END);
  return {
    t: shown,
    t_ms: ms(shown),
    now,
    playing,
    speed,
    live,
    stalled,
    recovered,
    missed,
    behind,
    toggle,
    play,
    pause,
    scrub,
    step,
    jump,
    setSpeed,
    goLive,
  };
}
