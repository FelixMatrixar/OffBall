import { useCallback, useEffect, useState, type ReactNode } from 'react';
import { ChartFrame, VegaChart, benchSpec, benchTrendSpec, fidelitySpec, reliabilitySpec } from '../components/charts';
import { Stage2D, Stage3D } from '../components/match';
import { Button, Card, CheckIcon, Chip, LinkButton, Logo, Segmented } from '../components/ui';
import { BRIER, BRIER_GAIN_TARGET, ECE_TARGET, FIDELITY_RESULTS, GATES, JITTER_MS, KS_GATE, RELEASES, RELIABILITY_RESULTS, TARGETS, frameReport, quantile, recordFrames, type FrameReport, type Status } from '../lib/eval';
import { useFeedStore, useMatchClock } from '../lib/feed';
import { useScreenClass } from '../lib/hooks';
import { useI18n } from '../lib/i18n';
import { usePrefs } from '../lib/prefs';
import { BENCH, BENCH_RUNS } from '../lib/stats';
import { TIERS, type Tier } from '../lib/tiers';

const pct = (v: number, digits = 0) => `${(v * 100).toFixed(digits)}%`;
const DECILES = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9];
/** How long the frame-time test records, after the scene has been playing for a moment. */
const MEASURE_MS = 4000;
const WARM_UP_MS = 400;

function StatusChip({ status }: { status: Status }) {
  if (status === 'pass')
    return (
      <Chip tone="space">
        <CheckIcon size={11} /> Passes
      </Chip>
    );
  if (status === 'fail') return <Chip tone="danger">Fails</Chip>;
  return <Chip tone="muted">Not run yet</Chip>;
}

function Section({ id, title, intro, children }: { id: string; title: string; intro: ReactNode; children: ReactNode }) {
  return (
    <section aria-labelledby={id} className="stack-lg eval-section">
      <div className="eval-section-head">
        <h2 id={id} className="display" style={{ fontSize: 30, margin: 0 }}>
          {title}
        </h2>
        <p className="muted" style={{ fontSize: 15, lineHeight: 1.55, margin: 0 }}>
          {intro}
        </p>
      </div>
      {children}
    </section>
  );
}

/**
 * A card for a table of sample results, labelled as such. On a phone each row stacks into a block: the row's name with
 * its status beside it, then each cell under its column's name (cells carry it as data-label).
 */
function TableCard({ id, title, caption, children }: { id?: string; title: string; caption: string; children: ReactNode }) {
  return (
    <Card>
      <div className="cluster" style={{ justifyContent: 'space-between', marginBottom: 12 }}>
        <h3 id={id} className="card-title eval-section" style={{ margin: 0, fontSize: 20 }}>
          {title}
        </h3>
        <Chip tone="muted">Sample data</Chip>
      </div>
      <div className="eval-table-wrap">
        <table className="chart-table eval-table">
          <caption className="sr-only">{caption}</caption>
          {children}
        </table>
      </div>
    </Card>
  );
}

interface Measurement {
  scene: string;
  tier: Tier;
  budget: number;
  report: FrameReport;
  within: boolean;
}

/**
 * The evaluation dashboard (PRD 16.4, 19): the synthetic data against real football, the models against what
 * happened, the agents against OffBall-Bench, and the renderer's frame time on the viewer's own device. Everything but
 * the frame-time test is sample data until the CI gate reports and Foundry evaluation runs publish, and says so.
 */
export function EvalView() {
  const { prefs, reducedMotion } = usePrefs();
  const i18n = useI18n();
  const { phonePortrait } = useScreenClass();
  const store = useFeedStore();
  const clock = useMatchClock(store, false);
  const [scene, setScene] = useState<'2d' | '3d'>('2d');
  const [threeD, setThreeD] = useState<{ tier: Tier | null; failed: string | null }>({ tier: null, failed: null });
  const [running, setRunning] = useState(false);
  const [history, setHistory] = useState<Measurement[]>([]);
  const [error, setError] = useState<string | null>(null);

  // The reference scene holds still at the gap until a test plays it.
  const { scrub, play, pause } = clock;
  useEffect(() => scrub(4.5), [scrub]);

  const onFail = useCallback((reason: string) => {
    setThreeD({ tier: null, failed: reason });
    setScene('2d');
  }, []);
  const onTier = useCallback((tier: Tier) => setThreeD((s) => (s.tier === tier ? s : { ...s, tier })), []);

  const tier: Tier = scene === '2d' ? 'C' : (threeD.tier ?? 'B');
  const ready = scene === '2d' || threeD.tier !== null;
  const measure = async () => {
    setRunning(true);
    setError(null);
    scrub(0);
    play();
    try {
      await new Promise((resolve) => setTimeout(resolve, WARM_UP_MS));
      const { intervals, work } = await recordFrames(MEASURE_MS);
      const report = frameReport(intervals, work);
      const budget = TIERS[tier].budget;
      setHistory((h) => [{ scene: scene === '2d' ? '2D view' : '3D broadcast view', tier, budget, report, within: report.p95Ms <= budget + JITTER_MS }, ...h].slice(0, 6));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      pause();
      setRunning(false);
    }
  };
  const last = history[0];

  const gatesPassing = GATES.filter((g) => g.status === 'pass').length;
  const space = RELIABILITY_RESULTS.find((r) => r.name === 'Space value');
  const latest = BENCH[BENCH.length - 1];
  const first = BENCH_RUNS[0];
  const final = BENCH_RUNS[BENCH_RUNS.length - 1];
  const notRun = TARGETS.filter((t) => t.status === 'not run').length;
  const stageProps = { store, time: clock, mode: 'analyst', density: 'standard', theme: prefs.theme, fav: prefs.fav, i18n, variant: 'real', ghosts: false, onFollow: () => {} } as const;
  const sceneChip = <span className="map-chip">Reference scene · Analyst · tier {tier}</span>;

  return (
    <div className="screen">
      <div className="container stack-lg">
        <header className="cluster anim-rise" style={{ justifyContent: 'space-between', gap: 16 }}>
          <Logo suffix="Evaluation" />
          <LinkButton href="#/match">Match view</LinkButton>
        </header>

        <section className="card eval-hero anim-rise" aria-labelledby="eval-title">
          <h1 id="eval-title" className="display" style={{ fontSize: 'clamp(36px, 6vw, 56px)', lineHeight: 1, margin: 0 }}>
            How we know it’s right
          </h1>
          <p style={{ fontSize: 16, lineHeight: 1.55, maxWidth: '70ch', margin: 0 }}>
            The match is synthetic, so every moment has a known answer. This page holds OffBall to it: the data against real football, the models against what actually happened, and the agents against OffBall-Bench, an open benchmark with answer keys.
          </p>
          <div className="eval-notice">
            <Chip tone="muted">Sample data</Chip>
            <span>
              The charts and tables hold sample data until the CI gate reports and Foundry evaluation runs publish results. The statistics are worked out on this page from the data shown, the way those reports work them out. The frame-time test at the end measures your device for real.
            </span>
          </div>
          <ul className="eval-kpis" aria-label="At a glance, from sample data">
            <li className="tile">
              <div className="tile-label">Quality gates passing</div>
              <div className="tile-value">{gatesPassing}</div>
              <div className="tile-unit">Of {GATES.length}; all must pass</div>
            </li>
            <li className="tile">
              <div className="tile-label">Planted moments found</div>
              <div className="tile-value">{pct(latest.recall)}</div>
              <div className="tile-unit">Target 85% or more</div>
            </li>
            <li className="tile">
              <div className="tile-label">Unverified claims aired</div>
              <div className="tile-value">0</div>
              <div className="tile-unit">Target none</div>
            </li>
            <li className="tile">
              <div className="tile-label">Space value calibration error</div>
              <div className="tile-value">{space ? space.ece.toFixed(3) : '—'}</div>
              <div className="tile-unit">Target {ECE_TARGET} or less</div>
            </li>
          </ul>
        </section>

        <Section
          id="fidelity-title"
          title="The data, against real football"
          intro={
            <>
              Gate 1, realism. Each chart shows the share of values at or below each point, for synthetic matches and for the calibration data from real ones. Where the two curves run together, the synthetic matches look real. The Kolmogorov–Smirnov statistic is the widest gap between them; the gate allows {KS_GATE.toFixed(2)}.
            </>
          }
        >
          <div className="eval-charts">
            {FIDELITY_RESULTS.map((f, i) => (
              <div key={f.metric} className="card stack" style={{ gap: 10 }}>
                <ChartFrame
                  title={f.metric}
                  name={`fidelity-${i + 1}`}
                  sample
                  summary={`Synthetic median ${quantile(f.synthetic, 0.5)} ${f.unit}, calibration median ${quantile(f.calibration, 0.5)} ${f.unit}. The widest gap between the curves is ${f.ks.toFixed(3)}, ${f.status === 'pass' ? 'inside' : 'outside'} the gate's ${KS_GATE.toFixed(2)}.`}
                  columns={['Share at or below', `Synthetic (${f.unit})`, `Calibration (${f.unit})`]}
                  rows={DECILES.map((p) => [pct(p), quantile(f.synthetic, p), quantile(f.calibration, p)])}
                >
                  <VegaChart spec={fidelitySpec(i)} label={`${f.metric}: cumulative distributions of synthetic and calibration values, solid and dashed.`} palette="measures" />
                </ChartFrame>
                <div className="cluster" style={{ gap: 8 }}>
                  <span className="tabular" style={{ fontSize: 14, fontWeight: 600 }}>
                    KS {f.ks.toFixed(3)}
                  </span>
                  <StatusChip status={f.status} />
                </div>
              </div>
            ))}
          </div>

          <TableCard title="The nine quality gates" caption="The nine quality gates: what each checks, when it passes, and the latest result">
            <thead>
              <tr>
                <th scope="col">Gate</th>
                <th scope="col">Checks</th>
                <th scope="col">Passes when</th>
                <th scope="col">Result</th>
                <th scope="col">Status</th>
              </tr>
            </thead>
            <tbody>
              {GATES.map((g) => (
                <tr key={g.n}>
                  <th scope="row" className="eval-nowrap" style={{ color: 'var(--text)' }}>
                    {g.n}. {g.name}
                  </th>
                  <td data-label="Checks">{g.checks}</td>
                  <td data-label="Passes when">{g.threshold}</td>
                  <td data-label="Result">{g.result}</td>
                  <td data-status="">
                    <StatusChip status={g.status} />
                  </td>
                </tr>
              ))}
            </tbody>
          </TableCard>
        </Section>

        <Section
          id="calibration-title"
          title="The models, against what happened"
          intro="A model that says 30% should be right 30% of the time. Each diagram groups the model’s predictions and plots how often the event really happened: points on the diagonal are well calibrated, and bigger points hold more predictions. Calibration error is the average distance from the diagonal, weighted by how many predictions each point holds."
        >
          <div className="eval-charts">
            {RELIABILITY_RESULTS.map((r) => (
              <div key={r.name} className="card stack" style={{ gap: 10 }}>
                <ChartFrame
                  title={r.name}
                  name={`reliability-${r.name.split(' ')[0].toLowerCase()}`}
                  sample
                  summary={`Calibration error ${r.ece.toFixed(3)}${r.target === null ? '' : `, ${r.status === 'pass' ? 'within' : 'over'} the ${r.target} target`}. The biggest gap is ${pct(Math.max(...r.bins.map((b) => Math.abs(b.observed - b.predicted))))} at a predicted ${pct(r.bins.reduce((a, b) => (Math.abs(b.observed - b.predicted) > Math.abs(a.observed - a.predicted) ? b : a)).predicted)}.`}
                  columns={['Predicted', 'Observed', 'Predictions']}
                  rows={r.bins.map((b) => [pct(b.predicted), pct(b.observed), b.n])}
                >
                  <VegaChart spec={reliabilitySpec(r.name)} label={`${r.name}: predicted against observed rates, with the diagonal for perfect calibration.`} palette="measures" />
                </ChartFrame>
                <div className="cluster" style={{ gap: 8 }}>
                  <span className="tabular" style={{ fontSize: 14, fontWeight: 600 }}>
                    Calibration error {r.ece.toFixed(3)}
                  </span>
                  {r.status ? (
                    <StatusChip status={r.status} />
                  ) : (
                    // No calibration target of its own: the chip says where its pass or fail is, and takes you there.
                    <button type="button" className="chip chip-outline eval-jump press" onClick={() => document.getElementById('brier-title')?.scrollIntoView({ behavior: reducedMotion ? 'auto' : 'smooth', block: 'start' })}>
                      Judged by Brier score ↓
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>

          <TableCard id="brier-title" title="Better than the simplest model" caption="Brier scores for pass difficulty and xG against their baselines; lower is better">
            <thead>
              <tr>
                <th scope="col">Model</th>
                <th scope="col">Baseline</th>
                <th scope="col">Brier score</th>
                <th scope="col">Baseline Brier</th>
                <th scope="col">Better by</th>
                <th scope="col">Status</th>
              </tr>
            </thead>
            <tbody>
              {BRIER.map((b) => (
                <tr key={b.model}>
                  <th scope="row" style={{ color: 'var(--text)' }}>
                    {b.model}
                  </th>
                  <td data-label="Baseline">{b.baseline}</td>
                  <td data-label="Brier score">{b.score.toFixed(3)}</td>
                  <td data-label="Baseline Brier">{b.baselineScore.toFixed(3)}</td>
                  <td data-label="Better by">
                    {pct(b.gain, 1)} <span className="muted">(target {pct(BRIER_GAIN_TARGET)})</span>
                  </td>
                  <td data-status="">
                    <StatusChip status={b.status} />
                  </td>
                </tr>
              ))}
            </tbody>
          </TableCard>
        </Section>

        <Section
          id="bench-title"
          title="The agents, against OffBall-Bench"
          intro="A hundred synthetic matches with answer keys: 70 with moments planted, 20 with nothing planted (to count invented moments), and 10 unscripted. Scores are on the 60-match test split, whose keys stay private, next to a rules-only baseline and a single agent with the same tools."
        >
          <div className="eval-pair">
            <div className="card">
              <ChartFrame
                title="Crew against the baselines"
                name="bench-versions"
                sample
                summary={`${latest.short}, the latest crew after Agent Optimizer, finds ${pct(latest.recall)} of planted moments, against ${pct(BENCH[1].recall)} for a single agent and ${pct(BENCH[0].recall)} for rules alone; ${pct(latest.precision)} of its aired claims check out.`}
                columns={['Version', 'Moment recall', 'Claim precision', 'Median credit error', 'Graphic latency p95']}
                rows={BENCH.map((b) => [b.version, pct(b.recall), pct(b.precision), `${b.creditError}%`, `${b.latency} s`])}
              >
                <VegaChart spec={benchSpec()} label="Moment recall and claim precision for the rules-only baseline, the single-agent baseline, the first crew and the latest crew." height={220} palette="measures" />
              </ChartFrame>
            </div>
            <div className="card">
              <ChartFrame
                title="Every release beats the last"
                name="bench-releases"
                sample
                summary={`From ${first.version} to ${final.version}, recall rose from ${pct(first.recall)} to ${pct(final.recall)} and credit within ±25% from ${pct(first.credit)} to ${pct(final.credit)}; dotted lines are their targets. The third measure, invented moments, is in the table: it fell from ${first.invented} to ${final.invented} per null match. ${RELEASES.every((r) => r.better) ? 'Each version beat the one before on all three, as the release gate requires.' : 'Not every version beat the one before.'}`}
                columns={['Version', 'Released', 'Planted moment recall', 'Invented per null match', 'Credit within ±25%', 'Beat the last version']}
                rows={RELEASES.map((r) => [r.version, r.date, pct(r.recall), r.invented.toFixed(2), pct(r.credit), r.better ? 'Yes' : 'No'])}
              >
                <VegaChart spec={benchTrendSpec()} label="Planted moment recall and credit accuracy for each released version, rising past their targets." height={220} palette="measures" />
              </ChartFrame>
            </div>
          </div>

          <TableCard title="Against the targets" caption={`PRD 19.2's targets for ${latest.version} on the test split, with ${notRun} human studies not run yet`}>
            <thead>
              <tr>
                <th scope="col">Measure</th>
                <th scope="col">Target</th>
                <th scope="col">{latest.short}</th>
                <th scope="col">Status</th>
              </tr>
            </thead>
            <tbody>
              {TARGETS.map((t, i) => (
                <tr key={t.measure} data-group-start={i === 0 || TARGETS[i - 1].group !== t.group || undefined}>
                  <th scope="row" style={{ color: 'var(--text)' }}>
                    <span className="eval-group">{t.group}</span>
                    {t.measure}
                  </th>
                  <td data-label="Target">{t.target}</td>
                  <td data-label={latest.short}>{t.result}</td>
                  <td data-status="">
                    <StatusChip status={t.status} />
                  </td>
                </tr>
              ))}
            </tbody>
          </TableCard>
        </Section>

        <Section
          id="render-title"
          title="Drawing it, on this device"
          intro={`Each rendering tier has a frame-time budget at the 95th percentile: ${TIERS.A.budget} ms for the 3D views on a mid-range laptop, ${TIERS.C.budget} ms for the 2D view on a four-year-old mid-range phone. The build's own tests hold it to those. Here you can measure your device: the test plays the moment for ${MEASURE_MS / 1000} seconds in Analyst mode, the heaviest, and times every frame.`}
        >
          <div className="eval-render">
            <div className="card stack" style={{ gap: 12 }}>
              <div className="cluster" style={{ justifyContent: 'space-between', gap: 10 }}>
                <Segmented
                  options={[
                    { value: '2d', label: '2D view' },
                    { value: '3d', label: '3D broadcast' },
                  ]}
                  value={scene}
                  onChange={(v) => {
                    setScene(v);
                    setError(null);
                    // A fresh 3D view says which tier it got once it's drawing; until then there's nothing to time.
                    if (v === '3d') setThreeD((s) => ({ ...s, tier: null }));
                  }}
                  label="Reference scene"
                />
                <Button variant="primary" onClick={() => void measure()} disabled={running || !ready}>
                  {running ? 'Measuring…' : 'Measure this device'}
                </Button>
              </div>
              <div className="pitch-card">
                {scene === '2d' ? (
                  <Stage2D {...stageProps} orientation={phonePortrait ? 'v' : 'h'} chips={sceneChip} />
                ) : (
                  <Stage3D {...stageProps} view="broadcast" tier="A" onFail={onFail} onTier={onTier} chips={sceneChip} portrait={phonePortrait} />
                )}
              </div>
              {threeD.failed && (
                <p className="muted" style={{ fontSize: 13, margin: 0 }}>
                  The 3D view can’t start on this device ({threeD.failed}), so only the 2D view can be measured.
                </p>
              )}
              <p role="status" style={{ fontSize: 15, lineHeight: 1.5, margin: 0, minHeight: 24 }}>
                {running
                  ? `Measuring the ${scene === '2d' ? '2D' : '3D'} view for ${MEASURE_MS / 1000} seconds…`
                  : error
                    ? error
                    : last
                      ? `${last.scene}, tier ${last.tier}: 95% of frames within ${last.report.p95Ms.toFixed(1)} ms, against a ${last.budget} ms budget. ${last.within ? 'Within budget.' : 'Over budget on this device.'}`
                      : 'No measurement yet.'}
              </p>
            </div>

            <Card>
              <div className="cluster" style={{ justifyContent: 'space-between', marginBottom: 12 }}>
                <h3 className="card-title" style={{ margin: 0, fontSize: 20 }}>
                  Your measurements
                </h3>
                <Chip tone="outline">Measured on this device</Chip>
              </div>
              {history.length === 0 ? (
                <p className="muted" style={{ fontSize: 14, lineHeight: 1.5 }}>
                  Results appear here, newest first. They stay on this page and aren’t sent anywhere.
                </p>
              ) : (
                <div className="eval-table-wrap">
                  <table className="chart-table eval-table">
                    <caption className="sr-only">Frame-time measurements on this device, newest first</caption>
                    <thead>
                      <tr>
                        <th scope="col">Scene</th>
                        <th scope="col">p95</th>
                        <th scope="col">Dropped</th>
                        <th scope="col">Work p95</th>
                        <th scope="col">Result</th>
                      </tr>
                    </thead>
                    <tbody>
                      {history.map((m, i) => (
                        <tr key={i}>
                          <th scope="row" style={{ color: 'var(--text)' }}>
                            {m.scene}, tier {m.tier}
                            <span className="eval-sub">
                              {m.report.hz} Hz display · {m.report.frames} frames
                            </span>
                          </th>
                          <td className="tabular" data-label="p95">
                            {m.report.p95Ms.toFixed(1)} ms<span className="eval-sub">budget {m.budget} ms</span>
                          </td>
                          <td className="tabular" data-label="Dropped">
                            {m.report.dropped}
                          </td>
                          <td className="tabular" data-label="Work p95">
                            {m.report.workP95Ms.toFixed(1)} ms
                          </td>
                          <td data-status="">{m.within ? <StatusChip status="pass" /> : <Chip tone="danger">Over budget</Chip>}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              <p className="muted" style={{ fontSize: 12, lineHeight: 1.5, marginTop: 12 }}>
                p95 is the time between frames that 95% of frames beat, with {JITTER_MS} ms allowed for timer jitter. Dropped frames are ones the display showed twice because the next wasn’t ready. Work is the time OffBall’s own frame loop took inside each frame. Your device isn’t the reference device, so read the budget as a guide.
              </p>
            </Card>
          </div>
        </Section>
      </div>
    </div>
  );
}
