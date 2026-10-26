// Numbers the backend computed from the match (INTEGRATION.md 6.5), held so the panels read them the way they read
// the stand-ins. Each stand-in in content.ts and stats.ts asks here first and keeps its own value as the fallback,
// so with no backend, or one that can't answer, nothing changes (BE-2).
import { useSyncExternalStore } from 'react';
import { apiBase, getJson } from './api';
import { BASE_MS, MATCH_ID, PERIOD, T_END } from './match';

/** The end of the showcase moment: stats are computed up to here, so they agree with what the pitch shows. */
const UNTIL_MS = BASE_MS + T_END * 1000;

const values = new Map<string, unknown>();
const asked = new Set<string>();
const listeners = new Set<() => void>();
let version = 0;

function request(key: string) {
  if (asked.has(key) || !apiBase()) return;
  asked.add(key);
  const [name, playerId] = key.split(':');
  const query = new URLSearchParams({ period: String(PERIOD), t_ms: String(UNTIL_MS) });
  if (playerId) query.set('player_id', playerId);
  if (name === 'focus') query.set('from_ms', String(BASE_MS));
  getJson<unknown>(`/api/matches/${MATCH_ID}/stats/${name}?${query}`)
    .then((value) => {
      values.set(key, value);
      version++;
      listeners.forEach((l) => l());
    })
    .catch(() => {
      // The stand-in stays: the backend can't compute this one yet, or can't be reached.
    });
}

/** The backend's value for `key` (a stat name, or `name:playerId`) once it has arrived, else `fallback`. */
export function served<T>(key: string, fallback: T): T {
  request(key);
  return values.has(key) ? (values.get(key) as T) : fallback;
}

/** Whether the backend's value for `key` is what the panels are showing. */
export const isServed = (key: string) => values.has(key);

const subscribe = (l: () => void) => {
  listeners.add(l);
  return () => listeners.delete(l);
};

/** Re-renders a component when computed numbers arrive. */
export const useServed = () => useSyncExternalStore(subscribe, () => version, () => version);
