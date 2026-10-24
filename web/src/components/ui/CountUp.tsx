import { useSinceMount } from '../../lib/hooks';
import { tokenMs } from '../../lib/motion';
import { usePrefs } from '../../lib/prefs';

/**
 * New numbers roll up from zero over the hero duration; once on screen they update in place (PRD 16.10).
 * With reduced motion they appear at once.
 */
export function CountUp({ value, decimals = 0, suffix = '', format }: { value: number; decimals?: number; suffix?: string; format?: (n: number) => string }) {
  const { reducedMotion } = usePrefs();
  const duration = tokenMs('--dur-hero') || 900;
  const elapsed = useSinceMount(duration);
  const u = reducedMotion ? 1 : Math.min(1, elapsed / duration);
  const eased = 1 - Math.pow(1 - u, 3);
  const n = value * eased;
  return (
    <span className="tabular">
      {format ? format(n) : n.toFixed(decimals)}
      {suffix}
    </span>
  );
}
