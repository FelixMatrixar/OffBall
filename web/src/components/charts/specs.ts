// Vega-Lite specs for panel and report charts (PRD 16.4). The same specs could come from the Pundit or the Producer;
// the client applies the theme (VIS-7).
import { BENCH, BENCH_RUNS, CONTROL_INDEX, FIDELITY, RELIABILITY, SHAPE } from '../../lib/stats';
import type { VegaLiteSpec } from './VegaChart';

const SCHEMA = 'https://vega.github.io/schema/vega-lite/v6.json';

/** Control versus chaos over the match (PRD 9.2). */
export function controlIndexSpec(upTo: number): VegaLiteSpec {
  const values = CONTROL_INDEX.filter((d) => d.minute <= upTo).flatMap((d) => [
    { minute: d.minute, team: 'Kestrel Bay', control: d.kes },
    { minute: d.minute, team: 'Ashmoor', control: d.ash },
  ]);
  return {
    $schema: SCHEMA,
    data: { values },
    layer: [
      { mark: { type: 'rule', strokeDash: [4, 4] }, encoding: { y: { datum: 50 } } },
      {
        mark: { type: 'line', interpolate: 'monotone' },
        encoding: {
          x: { field: 'minute', type: 'quantitative', title: 'Minute', scale: { domain: [0, 90] } },
          y: { field: 'control', type: 'quantitative', title: 'Control index', scale: { domain: [0, 100] } },
          color: { field: 'team', type: 'nominal', title: null, scale: { domain: ['Kestrel Bay', 'Ashmoor'] } },
          // Untitled rather than legend: null, which would drop the legend it shares with colour.
          strokeDash: { field: 'team', type: 'nominal', title: null, scale: { domain: ['Kestrel Bay', 'Ashmoor'], range: [[1, 0], [6, 3]] } },
        },
      },
    ],
  };
}

/** Line heights, width and compactness over time (PRD 16.4 shape and pressure). */
export function shapeSpec(): VegaLiteSpec {
  const labels: Record<string, string> = { ashLine: 'Ashmoor line height', ashWidth: 'Ashmoor width', ashCompact: 'Ashmoor compactness', kesPress: 'Kestrel press height' };
  const values = SHAPE.flatMap((d) => Object.entries(labels).map(([k, label]) => ({ minute: d.minute, measure: label, metres: d[k as keyof typeof d] })));
  return {
    $schema: SCHEMA,
    data: { values },
    mark: { type: 'line', point: true, interpolate: 'monotone' },
    encoding: {
      x: { field: 'minute', type: 'quantitative', title: 'Minute' },
      y: { field: 'metres', type: 'quantitative', title: 'Metres' },
      color: { field: 'measure', type: 'nominal', title: null },
      shape: { field: 'measure', type: 'nominal', title: null },
    },
  };
}

/** Synthetic against calibration as overlaid ECDFs (PRD 16.4 fidelity charts). */
export function fidelitySpec(i: number): VegaLiteSpec {
  const f = FIDELITY[i];
  const values = [
    ...f.synthetic.map((v, k) => ({ value: v, source: 'Synthetic', p: (k + 1) / f.synthetic.length })),
    ...f.calibration.map((v, k) => ({ value: v, source: 'Calibration', p: (k + 1) / f.calibration.length })),
  ];
  return {
    $schema: SCHEMA,
    data: { values },
    mark: { type: 'line', interpolate: 'step-after' },
    encoding: {
      x: { field: 'value', type: 'quantitative', title: `${f.metric} (${f.unit})` },
      y: { field: 'p', type: 'quantitative', title: 'Share at or below', axis: { format: '%' } },
      color: { field: 'source', type: 'nominal', title: null, scale: { domain: ['Synthetic', 'Calibration'] } },
      // One legend for colour and dash: the two curves run so close that the key has to say which is which.
      strokeDash: { field: 'source', type: 'nominal', title: null, scale: { domain: ['Synthetic', 'Calibration'], range: [[1, 0], [5, 3]] } },
    },
  };
}

/**
 * Predicted against observed rates: points on the diagonal mean well calibrated (PRD 16.4 reliability diagrams).
 * Each point's size is how many predictions it holds, and a stalk joins it to the diagonal, so the gaps that make up
 * the calibration error are drawn rather than left to the eye.
 */
export function reliabilitySpec(name: keyof typeof RELIABILITY): VegaLiteSpec {
  const x = { field: 'predicted', type: 'quantitative', title: 'Predicted', scale: { domain: [0, 1] }, axis: { format: '%' } };
  const y = { field: 'observed', type: 'quantitative', title: 'Observed', scale: { domain: [0, 1] }, axis: { format: '%' } };
  return {
    $schema: SCHEMA,
    data: { values: RELIABILITY[name] },
    layer: [
      { mark: { type: 'rule', strokeDash: [4, 4] }, encoding: { x: { datum: 0 }, y: { datum: 0 }, x2: { datum: 1 }, y2: { datum: 1 } } },
      { mark: { type: 'rule', strokeWidth: 2, opacity: 0.55 }, encoding: { x, y: { field: 'predicted', type: 'quantitative' }, y2: { field: 'observed' } } },
      { mark: { type: 'line', strokeWidth: 2 }, encoding: { x, y } },
      { mark: { type: 'circle', opacity: 1 }, encoding: { x, y, size: { field: 'n', type: 'quantitative', legend: null, scale: { range: [36, 240] } } } },
    ],
  };
}

const BENCH_METRICS = ['Moment recall', 'Claim precision'];

/** OffBall-Bench by agent version, with the two baselines (PRD 16.4 benchmark dashboard). */
export function benchSpec(): VegaLiteSpec {
  const values = BENCH.flatMap((b) => [
    { version: b.short, metric: BENCH_METRICS[0], score: b.recall },
    { version: b.short, metric: BENCH_METRICS[1], score: b.precision },
  ]);
  return {
    $schema: SCHEMA,
    data: { values },
    mark: { type: 'bar' },
    encoding: {
      y: { field: 'version', type: 'nominal', title: null, sort: null },
      x: { field: 'score', type: 'quantitative', title: 'Score', scale: { domain: [0, 1] }, axis: { format: '%' } },
      yOffset: { field: 'metric', sort: BENCH_METRICS },
      color: { field: 'metric', type: 'nominal', title: null, scale: { domain: BENCH_METRICS } },
    },
  };
}

const TREND = [
  { measure: 'Planted moment recall', short: 'Recall', key: 'recall', target: 0.85 },
  { measure: 'Credit within ±25%', short: 'Credit', key: 'credit', target: 0.8 },
] as const;

/**
 * Each released crew version on the test split, with each measure's target as a dotted line labelled at the start
 * (PRD 14.9, 16.4). Every layer gives the score axis the same 60–100% range: a layer without one would pull it down to
 * zero and flatten the climb. Nothing sets legend: null, which would drop the one legend the layers share.
 */
export function benchTrendSpec(): VegaLiteSpec {
  const domain = TREND.map((m) => m.measure);
  const y = { type: 'quantitative', title: 'Score', scale: { domain: [0.6, 1] }, axis: { format: '%' } };
  const color = { field: 'measure', type: 'nominal', title: null, scale: { domain } };
  const targets = { values: TREND.map((m) => ({ measure: m.measure, target: m.target, note: `${m.short} target ${Math.round(m.target * 100)}%` })) };
  return {
    $schema: SCHEMA,
    layer: [
      {
        data: targets,
        mark: { type: 'rule', strokeDash: [2, 4], opacity: 0.7 },
        encoding: { y: { field: 'target', ...y }, color },
      },
      {
        data: targets,
        mark: { type: 'text', align: 'left', baseline: 'bottom', dx: 4, dy: -3, fontSize: 10, fontWeight: 600 },
        encoding: { x: { value: 0 }, y: { field: 'target', ...y }, text: { field: 'note' } },
      },
      {
        data: { values: BENCH_RUNS.flatMap((r) => TREND.map((m) => ({ version: r.version, measure: m.measure, score: r[m.key] }))) },
        mark: { type: 'line', point: true },
        encoding: {
          x: { field: 'version', type: 'ordinal', title: 'Released version', sort: null, axis: { labelAngle: 0 } },
          y: { field: 'score', ...y },
          color,
          strokeDash: { field: 'measure', type: 'nominal', title: null, scale: { domain, range: [[1, 0], [6, 3]] } },
          shape: { field: 'measure', type: 'nominal', title: null, scale: { domain } },
        },
      },
    ],
  };
}

/** A small bar chart for an Ask OffBall answer. */
export function barSpec(rows: readonly { label: string; value: number; team?: string }[], title: string, max?: number): VegaLiteSpec {
  return {
    $schema: SCHEMA,
    data: { values: rows },
    mark: { type: 'bar' },
    encoding: {
      y: { field: 'label', type: 'nominal', title: null, sort: null },
      x: { field: 'value', type: 'quantitative', title, ...(max ? { scale: { domain: [0, max] } } : {}) },
      color: { field: 'team', type: 'nominal', legend: null },
    },
  };
}
