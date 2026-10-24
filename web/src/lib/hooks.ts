import { useEffect, useRef, useState } from 'react';

/** Current time, refreshed every `ms`. */
export function useNow(ms: number): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), ms);
    return () => clearInterval(id);
  }, [ms]);
  return now;
}

/** A counter that increments every `ms`; use it as a React key to replay an animation. */
export function useCycle(ms: number): number {
  const [n, setN] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setN((v) => v + 1), ms);
    return () => clearInterval(id);
  }, [ms]);
  return n;
}

/** Milliseconds since this component mounted, updated each animation frame until `until` ms. */
export function useSinceMount(until: number): number {
  const start = useRef(performance.now());
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    let frame = 0;
    const tick = (now: number) => {
      const e = now - start.current;
      setElapsed(e);
      if (e < until) frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [until]);
  return elapsed;
}

export function useMediaQuery(query: string): boolean {
  const [on, setOn] = useState(() => typeof window.matchMedia === 'function' && window.matchMedia(query).matches);
  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return;
    const m = window.matchMedia(query);
    const onChange = () => setOn(m.matches);
    onChange();
    m.addEventListener('change', onChange);
    return () => m.removeEventListener('change', onChange);
  }, [query]);
  return on;
}

/** Screen classes from PRD 16.5. */
export function useScreenClass() {
  const phonePortrait = useMediaQuery('(max-width: 599px) and (orientation: portrait)');
  const phoneLandscape = useMediaQuery('(max-height: 500px) and (orientation: landscape) and (max-width: 1000px)');
  const tablet = useMediaQuery('(max-width: 1023px)');
  return { phonePortrait, phoneLandscape, tablet: tablet && !phonePortrait && !phoneLandscape, compact: phonePortrait || phoneLandscape };
}

/** navigator.onLine, kept current; a ?offline=1 query previews the offline state. */
export function useOnline(): boolean {
  const forced = new URLSearchParams(window.location.hash.split('?')[1] ?? '').get('offline') === '1';
  const [online, setOnline] = useState(() => navigator.onLine);
  useEffect(() => {
    const on = () => setOnline(true);
    const off = () => setOnline(false);
    window.addEventListener('online', on);
    window.addEventListener('offline', off);
    return () => {
      window.removeEventListener('online', on);
      window.removeEventListener('offline', off);
    };
  }, []);
  return online && !forced;
}

/** The latest value of something, readable from callbacks without re-subscribing. */
export function useLatest<T>(value: T) {
  const ref = useRef(value);
  ref.current = value;
  return ref;
}

/** A value from the hash route's query string, such as #/match?state=loading. */
const readHashQuery = (name: string) => new URLSearchParams(window.location.hash.split('?')[1] ?? '').get(name);

export function useHashQuery(name: string): string | null {
  const [value, setValue] = useState(() => readHashQuery(name));
  useEffect(() => {
    const onChange = () => setValue(readHashQuery(name));
    window.addEventListener('hashchange', onChange);
    return () => window.removeEventListener('hashchange', onChange);
  }, [name]);
  return value;
}
