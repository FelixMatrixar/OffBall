// Learn mode's personal glossary (PRD 8.1): it grows as the viewer watches and lives on the device only.
import { useEffect, useRef, useState } from 'react';
import type { Concept } from './i18n';

const KEY = 'offball.glossary';
export const CONCEPT_AT_STEP: Partial<Record<number, Concept>> = { 1: 'decoy', 2: 'follow', 3: 'gap', 4: 'timed' };
export const CONCEPTS: readonly Concept[] = ['decoy', 'follow', 'gap', 'timed'];

type Seen = Record<Concept, number>;
const empty = (): Seen => ({ decoy: 0, follow: 0, gap: 0, timed: 0 });
const today = () => new Date().toISOString().slice(0, 10);

function load(): Seen {
  try {
    const raw = JSON.parse(localStorage.getItem(KEY) ?? 'null') as { day: string; seen: Seen } | null;
    if (raw && raw.day === today()) return { ...empty(), ...raw.seen };
  } catch {
    // Start fresh.
  }
  return empty();
}

/**
 * Counts each idea once per play-through of the moment. `loop` changes when the moment restarts.
 * Returns today's counts and whether the current step's idea is new to the viewer today.
 */
export function useGlossary(step: number, loop: number, active: boolean): { seen: Seen; fresh: boolean } {
  const [seen, setSeen] = useState<Seen>(load);
  const counted = useRef(new Set<string>());
  const concept = CONCEPT_AT_STEP[step];
  useEffect(() => {
    if (!active || !concept) return;
    const key = `${loop}:${concept}`;
    if (counted.current.has(key)) return;
    counted.current.add(key);
    setSeen((s) => {
      const next = { ...s, [concept]: s[concept] + 1 };
      try {
        localStorage.setItem(KEY, JSON.stringify({ day: today(), seen: next }));
      } catch {
        // Counts last for this visit.
      }
      return next;
    });
  }, [active, concept, loop]);
  return { seen, fresh: !!concept && seen[concept] <= 1 };
}
