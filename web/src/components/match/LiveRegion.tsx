import { useCallback, useEffect, useRef, useState } from 'react';

const MIN_GAP_MS = 2500;

/**
 * Screen-reader announcements at a rate limit, so they never flood (PRD 15.4): at most one every 2.5 s, and only
 * the newest waiting message is read.
 */
export function useAnnouncer() {
  const [msg, setMsg] = useState('');
  const last = useRef(0);
  const pending = useRef<string | null>(null);
  const timer = useRef<number>();
  useEffect(() => () => window.clearTimeout(timer.current), []);
  const announce = useCallback((text: string) => {
    if (!text) return;
    pending.current = text;
    window.clearTimeout(timer.current);
    const wait = Math.max(0, last.current + MIN_GAP_MS - Date.now());
    timer.current = window.setTimeout(() => {
      if (pending.current) {
        setMsg(pending.current);
        last.current = Date.now();
        pending.current = null;
      }
    }, wait);
  }, []);
  return { msg, announce };
}

export function LiveRegion({ msg }: { msg: string }) {
  return (
    <div className="live-region" role="status" aria-live="polite" aria-atomic="true">
      {msg}
    </div>
  );
}
