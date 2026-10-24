import type { Metric } from '../../../lib/prefs';

/** The number a viewer cares about (PRD 8.2): shown first, and highlighted, wherever it appears. */
export const METRIC_LABEL: Record<Metric, string> = {
  space: 'Space created',
  pass: 'Pass difficulty',
  sprint: 'Sprint speed',
};

export interface StatItem {
  key: string;
  label: string;
  value: string;
  unit?: string;
  /** Which viewer metric this tile answers, if any. */
  metric?: Metric;
  ready?: boolean;
  /** Until it's ready, what it's waiting for: "After the pass". */
  waiting?: string;
}

/** Puts the viewer's chosen metric first. */
export function byMetric(items: readonly StatItem[], metric: Metric): StatItem[] {
  return [...items].sort((a, b) => Number(b.metric === metric) - Number(a.metric === metric));
}
