// The evaluation screen's numbers (PRD 12.10, 16.4, 19). The statistics are computed here from the data shown, the
// way the CI gate reports and Foundry evaluation runs compute them; the data itself is sample data until those runs
// publish results. The frame-time test is the exception: it measures the viewer's own device.
import { onFrame } from './frame-loop';
import { BENCH, BENCH_RUNS, FIDELITY, RELIABILITY } from './stats';

/** The realism gate's limit on the Kolmogorov–Smirnov statistic (PRD 12.10, gate 1). */
export const KS_GATE = 0.1;
/** The space-value model's limit on expected calibration error (PRD 19.2). */
export const ECE_TARGET = 0.02;
/** How much better than its baseline a probability model's Brier score must be (PRD 19.2). */
export const BRIER_GAIN_TARGET = 0.1;

export type Status = 'pass' | 'fail' | 'not run';

/** The two-sample Kolmogorov–Smirnov statistic: the largest gap between the two samples' cumulative distributions. */
export function ks(a: readonly number[], b: readonly number[]): number {
  const x = [...a].sort((p, q) => p - q);
  const y = [...b].sort((p, q) => p - q);
  let i = 0;
  let j = 0;
  let d = 0;
  while (i < x.length && j < y.length) {
    const v = Math.min(x[i], y[j]);
    while (i < x.length && x[i] <= v) i++;
    while (j < y.length && y[j] <= v) j++;
    d = Math.max(d, Math.abs(i / x.length - j / y.length));
  }
  return d;
}

/** A sample's value at a share of the way through it (nearest rank). */
export function quantile(sorted: readonly number[], p: number): number {
  return sorted[Math.min(sorted.length - 1, Math.max(0, Math.ceil(p * sorted.length) - 1))];
}

export interface Bin {
  predicted: number;
  observed: number;
  n: number;
}

/** Expected calibration error: the gap between predicted and observed rates, averaged over bins by their size. */
export function ece(bins: readonly Bin[]): number {
  const total = bins.reduce((s, b) => s + b.n, 0);
  return total ? bins.reduce((s, b) => s + b.n * Math.abs(b.observed - b.predicted), 0) / total : 0;
}

/** Each fidelity statistic with its KS against the gate. */
export const FIDELITY_RESULTS = FIDELITY.map((f) => {
  const d = ks(f.synthetic, f.calibration);
  return { ...f, ks: d, status: (d <= KS_GATE ? 'pass' : 'fail') as Status };
});

/** Each reliability diagram with its calibration error; only space value has a target of its own. */
export const RELIABILITY_RESULTS = (Object.keys(RELIABILITY) as (keyof typeof RELIABILITY)[]).map((name) => {
  const e = ece(RELIABILITY[name]);
  const target = name === 'Space value' ? ECE_TARGET : null;
  return { name, bins: RELIABILITY[name], ece: e, target, status: (target === null ? null : e <= target ? 'pass' : 'fail') as Status | null };
});

/** Brier scores against the baselines PRD 19.2 names. Lower is better. Sample values. */
export const BRIER = [
  { model: 'Pass difficulty', baseline: 'Distance only', score: 0.152, baselineScore: 0.181 },
  { model: 'Shot xG', baseline: 'Distance and angle', score: 0.069, baselineScore: 0.079 },
].map((b) => {
  const gain = 1 - b.score / b.baselineScore;
  return { ...b, gain, status: (gain >= BRIER_GAIN_TARGET ? 'pass' : 'fail') as Status };
});

export interface Gate {
  n: number;
  name: string;
  checks: string;
  threshold: string;
  result: string;
  status: Status;
}

const worstKs = Math.max(...FIDELITY_RESULTS.map((f) => f.ks));

/** The nine quality gates (PRD 12.10). The realism result is computed from the statistics above; the rest are sample values. */
export const GATES: readonly Gate[] = [
  {
    n: 1,
    name: 'Realism',
    checks: 'Synthetic against calibration distributions',
    threshold: 'KS at most 0.10 per statistic; team totals inside the 5th–95th percentile in 90% of matches',
    result: `KS at most ${worstKs.toFixed(2)} on the statistics shown; team totals inside in 94% of matches`,
    status: worstKs <= KS_GATE ? 'pass' : 'fail',
  },
  { n: 2, name: 'Physics', checks: 'Speed, acceleration, turning, ball speed, spacing', threshold: 'Players at most 10.5 m/s; no two closer than 0.5 m outside duels', result: 'No violations in 1,200 matches', status: 'pass' },
  { n: 3, name: 'Consistency', checks: 'Events and tracking agree', threshold: 'Passer and receiver within 1.5 m of the ball; score equals goals', result: 'No mismatches', status: 'pass' },
  { n: 4, name: 'Behaviour', checks: 'Off-ball behaviour matches football', threshold: 'Run, follow and press rates inside the SkillCorner season ranges', result: 'Inside the ranges for every phase', status: 'pass' },
  { n: 5, name: 'Discriminator', checks: 'A model can’t tell synthetic from real', threshold: 'ROC AUC at most 0.65 on held-out windows', result: 'ROC AUC 0.61', status: 'pass' },
  { n: 6, name: 'Detectability', checks: 'Every labelled moment can be found from the data', threshold: 'Signals 2 SD above baseline; an oracle detector finds 95%', result: 'Signals 2.6 SD above; the oracle finds 97%', status: 'pass' },
  { n: 7, name: 'Novelty', checks: 'The data is genuinely synthetic', threshold: 'No near-copy of a calibration possession; no real names', result: 'No near-copies; no real names', status: 'pass' },
  { n: 8, name: 'Diversity', checks: 'No collapse into one kind of match', threshold: 'A style classifier names the club 80% of the time', result: 'The club named 84% of the time', status: 'pass' },
  { n: 9, name: 'Determinism', checks: 'Runs can be reproduced', threshold: 'Same seed and version give identical file hashes', result: 'Identical hashes on re-run', status: 'pass' },
];

export interface Target {
  group: string;
  measure: string;
  target: string;
  result: string;
  status: Status;
}

const latest = BENCH[BENCH.length - 1];
const lastRun = BENCH_RUNS[BENCH_RUNS.length - 1];
const spaceValue = RELIABILITY_RESULTS.find((r) => r.name === 'Space value');
const single = BENCH.find((b) => b.version === 'Single-agent baseline');
const pct = (v: number) => `${Math.round(v * 100)}%`;

/**
 * PRD 19.2's targets for the latest crew version on the test split: sample values, except where computed from the
 * charts above. Human studies haven't been run, and say so.
 */
export const TARGETS: readonly Target[] = [
  { group: 'Detection', measure: 'Planted moment recall', target: '85% or more', result: pct(latest.recall), status: latest.recall >= 0.85 ? 'pass' : 'fail' },
  { group: 'Detection', measure: 'Emergent moment recall', target: '70% or more', result: '72%', status: 'pass' },
  { group: 'Detection', measure: 'Invented moments', target: '0.3 or fewer per null match', result: lastRun.invented.toFixed(2), status: lastRun.invented <= 0.3 ? 'pass' : 'fail' },
  { group: 'Detection', measure: 'Moment type accuracy', target: '80% or more', result: '86%', status: 'pass' },
  { group: 'Credit', measure: 'Creator named correctly', target: '80% or more', result: '83%', status: 'pass' },
  { group: 'Credit', measure: 'Counterfactual credit', target: 'Within ±25% on 80% of moments; rank correlation 0.8', result: `${pct(lastRun.credit)}; rank correlation 0.84`, status: lastRun.credit >= 0.8 ? 'pass' : 'fail' },
  { group: 'Explanation', measure: 'Traceable claims', target: 'Every number cites an event or frame', result: '100%', status: 'pass' },
  { group: 'Explanation', measure: 'Unverified claims aired', target: 'None', result: '0', status: 'pass' },
  { group: 'Explanation', measure: 'Fact-check pass rate', target: '98% or more', result: '98.6%', status: 'pass' },
  { group: 'Explanation', measure: 'Groundedness', target: '4.5 or more of 5', result: '4.6', status: 'pass' },
  { group: 'Models', measure: 'Run classification', target: 'Macro-F1 0.80 or more', result: '0.83', status: 'pass' },
  {
    group: 'Models',
    measure: 'Pass difficulty and xG',
    target: 'Brier at least 10% better than baselines',
    result: BRIER.map((b) => `${pct(b.gain)} better`).join(', '),
    status: BRIER.every((b) => b.status === 'pass') ? 'pass' : 'fail',
  },
  { group: 'Models', measure: 'Space value calibration', target: 'Calibration error 0.02 or less', result: spaceValue ? spaceValue.ece.toFixed(3) : '—', status: spaceValue?.status ?? 'not run' },
  {
    group: 'Agents',
    measure: 'Crew against a single agent',
    target: 'Better recall, fewer inventions and unverified claims',
    result: single ? `Recall ${pct(latest.recall)} against ${pct(single.recall)}; better on all three` : '—',
    status: single && latest.recall > single.recall ? 'pass' : 'fail',
  },
  { group: 'Agents', measure: 'Pundit accuracy', target: '90% or more of 300 questions', result: '92%', status: 'pass' },
  { group: 'Agents', measure: 'Prompt-injection resistance', target: 'Attacks succeed 2% of the time or less', result: '1.1%', status: 'pass' },
  { group: 'Agents', measure: 'Chaos recovery', target: 'No unverified claim on screen; recovered in 10 s', result: 'All faults; 7.2 s worst', status: 'pass' },
  { group: 'Personalization', measure: 'Mode distinctness', target: 'Raters name the mode 90% of the time', result: 'Blind rating study not run yet', status: 'not run' },
  { group: 'Personalization', measure: 'Translation quality', target: 'Adequacy 4 or more of 5 per language', result: 'Native-speaker review not run yet', status: 'not run' },
  { group: 'Experience', measure: 'Fan comprehension', target: '70% can say why the goal happened', result: 'A/B study not run yet', status: 'not run' },
  { group: 'Experience', measure: 'Usability', target: 'System Usability Scale 75 or more', result: 'Study not run yet', status: 'not run' },
];

/** Each release against the one before it (PRD 14.9: a version ships only if it beats the last on the test split). */
export const RELEASES = BENCH_RUNS.map((r, i) => {
  const prev = BENCH_RUNS[i - 1];
  const better = !prev || (r.recall > prev.recall && r.invented < prev.invented && r.credit > prev.credit);
  return { ...r, better };
});

export interface FrameReport {
  frames: number;
  /** The display's frame interval, and its rate. */
  refreshMs: number;
  hz: number;
  /** 95th-percentile time between frames. */
  p95Ms: number;
  /** Frames the display showed twice because a new one wasn't ready. */
  dropped: number;
  /** 95th-percentile time the app's frame work took, within each frame. */
  workP95Ms: number;
}

/** The report for a run of frames: intervals between them, and the work done in each. Pure, for the tests. */
export function frameReport(intervals: readonly number[], work: readonly number[]): FrameReport {
  const sorted = [...intervals].sort((a, b) => a - b);
  // The display interval: the quarter-way point, which dropped frames can't pull up.
  const refreshMs = quantile(sorted, 0.25) || 16.7;
  const dropped = intervals.reduce((n, d) => n + Math.max(0, Math.round(d / refreshMs) - 1), 0);
  return {
    frames: intervals.length,
    refreshMs,
    hz: Math.round(1000 / refreshMs),
    p95Ms: quantile(sorted, 0.95) ?? 0,
    dropped,
    workP95Ms: quantile([...work].sort((a, b) => a - b), 0.95) ?? 0,
  };
}

/** Timer jitter allowed over a budget, so a display that's exactly on budget passes. */
export const JITTER_MS = 1;

/**
 * Records `ms` of frames: the time between display frames, and how long the app's frame loop took in each (every
 * renderer runs inside it). Rejects if the tab was hidden meanwhile, since hidden tabs barely draw.
 */
export function recordFrames(ms: number): Promise<{ intervals: number[]; work: number[] }> {
  return new Promise((resolve, reject) => {
    const intervals: number[] = [];
    const work: number[] = [];
    let last = 0;
    let begun = 0;
    let hidden = document.visibilityState !== 'visible';
    const onHide = () => {
      if (document.visibilityState !== 'visible') hidden = true;
    };
    document.addEventListener('visibilitychange', onHide);
    // First in every frame, and last: everything between is the app's own work.
    const stopFirst = onFrame((now) => {
      if (last) intervals.push(now - last);
      last = now;
      begun = performance.now();
    }, -1);
    const stopLast = onFrame(() => {
      if (begun) work.push(performance.now() - begun);
    }, 99);
    setTimeout(() => {
      stopFirst();
      stopLast();
      document.removeEventListener('visibilitychange', onHide);
      if (hidden) reject(new Error('The tab was hidden during the test, so the browser slowed its drawing. Try again with the tab in view.'));
      else resolve({ intervals, work });
    }, ms);
  });
}
