import { useEffect, useState } from 'react';

/** A duration token from tokens.css in milliseconds, so timers in code use the same values as CSS (PRD 16.10). */
export function tokenMs(name: string): number {
  const raw = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  if (raw.endsWith('ms')) return parseFloat(raw);
  if (raw.endsWith('s')) return parseFloat(raw) * 1000;
  return 0;
}

/** Keeps something mounted while it animates out: `closing` is true for the exit duration after `open` turns off. */
export function usePresence(open: boolean, exitToken = '--dur-quick'): { mounted: boolean; closing: boolean } {
  const [state, setState] = useState<'open' | 'closing' | 'closed'>(open ? 'open' : 'closed');
  useEffect(() => {
    if (open) {
      setState('open');
      return;
    }
    setState((s) => (s === 'closed' ? 'closed' : 'closing'));
    const id = window.setTimeout(() => setState('closed'), tokenMs(exitToken));
    return () => window.clearTimeout(id);
  }, [open, exitToken]);
  return { mounted: state !== 'closed', closing: state === 'closing' };
}
