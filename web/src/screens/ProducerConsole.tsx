import { useEffect, useMemo, useState } from 'react';
import { AgentTrace, type TraceRow } from '../components/charts';
import { QueueChip, Stage2D, broadcastQueue, decideAll, kindLabel, queueState } from '../components/match';
import { RecapBuilder } from '../components/recap';
import { Button, Card, Chip, Logo, PulseDot, Switch } from '../components/ui';
import { apiBase, getJson } from '../lib/api';
import { sourceFromLocation, useFeedSource, useFeedStore, useMatchClock, type Overlay } from '../lib/feed';
import { useNow } from '../lib/hooks';
import { useI18n } from '../lib/i18n';
import { BASE_MS, MATCH_ID, PERIOD, clockLabel } from '../lib/match';
import { usePrefs } from '../lib/prefs';

const REVERT_SECONDS = 462;
const AUTO_THRESHOLD = 0.85;
const DASHBOARD_URL = import.meta.env.VITE_FABRIC_DASHBOARD_URL as string | undefined;

/** The trace behind each kind of graphic: the crew's steps, retries and fallbacks, in seconds after the moment. */
function traceFor(o: Overlay): { rows: TraceRow[]; note?: string } {
  const kind = kindLabel(o);
  if (kind === 'gap_ring')
    return {
      rows: [
        { agent: 'Scout', start: 0, end: 0.28 },
        { agent: 'Explainer', start: 0.3, end: 1.15 },
        { agent: 'Fact-checker', start: 1.15, end: 1.62, kind: 'rejected' },
        { agent: 'Explainer · retry', start: 1.62, end: 2.05 },
        { agent: 'Fact-checker', start: 2.05, end: 2.36 },
        { agent: 'Persona × 4', start: 2.36, end: 2.74 },
        { agent: 'Producer', start: 2.74, end: 2.9 },
      ],
      note: 'Fact-checker rejected one claim. The draft said “No. 5 tracked 12 m”; recomputed from the frames it was 10.8 m. The Explainer rewrote it and the second check passed.',
    };
  if (kind === 'ghost_replay')
    return {
      rows: [
        { agent: 'Scout', start: 0, end: 0.28 },
        { agent: 'Tactician', start: 0.3, end: 9.7, kind: 'async', note: '9.4 s' },
        { agent: 'Fact-checker', start: 2.6, end: 2.9 },
      ],
      note: 'The Tactician re-ran the moment 32 times with the run and 32 without, off the critical path. Ready within its 15 s target.',
    };
  if (kind === 'stat_card')
    return {
      rows: [
        { agent: 'Scout', start: 0, end: 0.2 },
        { agent: 'Fact-checker', start: 0.2, end: 0.5 },
        { agent: 'Producer', start: 0.5, end: 0.62 },
      ],
    };
  return {
    rows: [
      { agent: 'Scout', start: 0, end: 0.26 },
      { agent: 'Explainer', start: 0.28, end: 0.98 },
      { agent: 'Fact-checker', start: 0.98, end: 1.3 },
      { agent: 'Persona × 4', start: 1.3, end: 1.66 },
      { agent: 'Producer', start: 1.66, end: 1.8 },
    ],
  };
}

/** On a live run, the crew's real trace for a graphic from the backend (INTEGRATION.md 6.3); null until it arrives. */
function useServedTrace(o: Overlay | undefined, live: boolean): { rows: TraceRow[]; note?: string } | null {
  const [got, setGot] = useState<{ id: string; rows: TraceRow[] } | null>(null);
  const id = o?.overlay_id;
  useEffect(() => {
    if (!id || !live || !apiBase()) return;
    const ctl = new AbortController();
    getJson<{ rows: TraceRow[] }>(`/api/matches/${MATCH_ID}/overlays/${encodeURIComponent(id)}/trace`, ctl.signal)
      .then((t) => t.rows.length && setGot({ id, rows: t.rows }))
      .catch(() => setGot(null));
    return () => ctl.abort();
  }, [id, live]);
  return got && got.id === id ? { rows: got.rows, note: 'The crew’s steps for this graphic, from the live run’s envelopes.' } : null;
}

/** The fatigue-gap graphic the Activator alert suggests (PRD 17.4). */
const fatigueGraphic = (): Overlay => ({
  schema_version: '2.0',
  overlay_id: `${MATCH_ID}-o0090`,
  rev: 1,
  match_id: MATCH_ID,
  period: PERIOD,
  t_start_ms: BASE_MS + 7000,
  t_end_ms: BASE_MS + 11000,
  kind: 'stat_card',
  layer: 'dom',
  priority: 2,
  mode: 'broadcaster',
  anchors: { player_id: 'ash-02' },
  text: { en: 'RECOVERY SPEED' },
  speech: {},
  a11y_text: { en: 'Ashmoor No. 2’s recovery speed is down 17% since 55 minutes.' },
  chart: null,
  data: { value: -17, unit: '%', player: 'No. 2' },
  evidence_ids: [`${MATCH_ID}-activator-fatigue`],
  confidence: 0.82,
  approval: 'pending',
  ai_generated: true,
  labels: ['synthetic-data', 'ai-generated', 'activator'],
});

/** The producer's console (PRD 10.6, 15.6). Every decision here is a contract message that reaches every open view. */
export function ProducerConsole() {
  const { prefs } = usePrefs();
  const i18n = useI18n();
  // The same feed as the match view (`?feed=`), so a producer can run a live match from here (INTEGRATION.md 9).
  const spec = useMemo(() => sourceFromLocation(), []);
  const source = useFeedSource(spec);
  const store = useFeedStore();
  const clock = useMatchClock(store, !!source?.live);
  const now = useNow(1000);
  const [openedAt] = useState(() => Date.now());
  const [auto, setAuto] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [traceRun, setTraceRun] = useState(0);
  const [flag, setFlag] = useState<'fast' | 'kept' | 'undone'>('fast');
  const [steps, setSteps] = useState<{ at: number; text: string }[]>([]);
  const queue = broadcastQueue(store);
  const current = queue.find((o) => o.overlay_id === selected) ?? queue.find((o) => o.kind === 'gap_ring') ?? queue[0];
  const served = useServedTrace(current, !!source?.live);
  const trace = served ?? (current ? traceFor(current) : null);
  const fatigueQueued = store.overlays.has(`${MATCH_ID}-o0090`);

  // Automatic mode: anything pending at or above the threshold is approved (PRD 15.6).
  useEffect(() => {
    if (!auto) return;
    for (const o of queue) if (o.approval === 'pending' && o.confidence >= AUTO_THRESHOLD) decideAll(store, o, 'approved');
  }, [auto, queue, store]);

  const left = Math.max(0, REVERT_SECONDS - Math.floor((now - openedAt) / 1000));
  const circumference = 2 * Math.PI * 7;
  const fast = flag !== 'undone';
  const flags = [
    { key: 'explainer.model_tier', value: fast ? `fast · ${flag === 'kept' ? 'kept by you' : 'by Engineer'}` : 'reasoning', changed: fast },
    { key: 'persona.live_languages', value: 'all active', changed: false },
    { key: 'producer.density', value: 'standard', changed: false },
    { key: 'tactician.enabled', value: 'on', changed: false },
    { key: 'voice.enabled', value: 'on', changed: false },
  ];
  const score = store.scoreAt(clock.t_ms);
  const correct = () => {
    const start = Date.now();
    setSteps([]);
    store.correct((text) => setSteps((s) => [...s, { at: Date.now() - start, text }]));
  };

  return (
    <div className="screen">
      <div className="container">
        <h1 className="sr-only">Producer console</h1>
        <header className="cluster anim-rise" style={{ gap: '12px 20px', marginBottom: 16 }}>
          <Logo suffix="Producer" size={26} />
          <span className="display" style={{ fontSize: 22, fontWeight: 600, background: 'var(--surface)', border: '1px solid var(--line)', borderRadius: 10, padding: '6px 12px' }} dir="ltr">
            KES {score.kes}–{score.ash} ASH <span className="tabular muted">{clockLabel(clock.t)}</span>
          </span>
          {[
            ['Graphic latency p95', '2.4 s', 80, 'var(--kes)'],
            ['Verified', '99.1%', 99, 'var(--space)'],
            ['Tokens', '41% of budget', 41, 'var(--ash)'],
          ].map(([label, value, pct, color], i) => (
            <span key={String(label)} className="cluster" style={{ gap: 8, fontSize: 13, padding: '6px 10px', borderRadius: 8, background: 'var(--surface)', border: '1px solid var(--line)' }}>
              {label} <strong className="tabular">{value}</strong>
              <span className="meter" style={{ width: 60, height: 6 }} aria-hidden="true">
                <span className="meter-fill anim-grow" style={{ width: `${pct}%`, background: String(color), animationDelay: `calc(var(--dur-smooth) + var(--stagger) * ${i * 2})` }} />
              </span>
            </span>
          ))}
          <div className="spacer cluster">
            <Switch checked={auto} onChange={setAuto} label={auto ? `Automatic: graphics at ${AUTO_THRESHOLD} confidence or more air` : 'Manual approval for rings and replays'} />
          </div>
        </header>

        <main className="row" style={{ gap: 18 }}>
          <Card className="side" style={{ flexBasis: 380 }} order={1}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 12 }}>
              <h2 className="card-title" style={{ margin: 0 }}>
                Graphics queue
              </h2>
              <span className="muted" style={{ fontSize: 12 }}>
                In order of airing
              </span>
            </div>
            <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexDirection: 'column', gap: 10 }}>
              {queue.map((o) => {
                const s = queueState(o, clock.t, store.retractions.has(o.overlay_id));
                const open = s === 'Waiting' || s === 'Held';
                const airing = s === 'On air' || s === 'Queued' || s === 'Done';
                const text = o.a11y_text.en ?? o.text.en ?? '';
                return (
                  <li key={o.overlay_id} className="tile queue-item" aria-current={current?.overlay_id === o.overlay_id ? 'true' : undefined} style={{ padding: '12px 14px', borderRadius: 12, opacity: s === 'Skipped' || s === 'Retracted' ? 0.65 : 1 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8 }}>
                      <button type="button" className="btn btn-ghost btn-sm press mono" onClick={() => (setSelected(o.overlay_id), setTraceRun((n) => n + 1))} aria-label={`Show the trace for ${kindLabel(o)} ${o.overlay_id}`}>
                        {kindLabel(o)}
                      </button>
                      <QueueChip state={s} approved={o.approval === 'approved'} />
                    </div>
                    <p style={{ margin: '8px 0 6px', fontSize: 14, lineHeight: 1.4 }}>
                      <span key={s} className={s === 'Retracted' || s === 'Skipped' ? 'strike' : undefined}>
                        {text}
                      </span>
                    </p>
                    <div className="cluster muted" style={{ gap: 8, fontSize: 12 }}>
                      <span>Confidence {o.confidence.toFixed(2)}</span>
                      <span className="meter" style={{ flex: 1, height: 6 }} aria-hidden="true">
                        <span className="meter-fill" style={{ width: `${o.confidence * 100}%`, background: 'var(--kes)' }} />
                      </span>
                    </div>
                    <div className="mono muted" style={{ fontSize: 11, marginTop: 6 }}>
                      {o.evidence_ids.join(' · ')}
                    </div>
                    {open && (
                      <div className="cluster" style={{ marginTop: 10, gap: 6 }}>
                        <Button variant="primary" onClick={() => decideAll(store, o, 'approved')}>
                          Approve
                        </Button>
                        {s !== 'Held' && (
                          <Button variant="ghost" onClick={() => decideAll(store, o, 'held')}>
                            Hold
                          </Button>
                        )}
                        <Button variant="ghost" onClick={() => decideAll(store, o, 'skipped')}>
                          Skip
                        </Button>
                      </div>
                    )}
                    {airing && o.approval !== 'pending' && (
                      <div style={{ marginTop: 10 }}>
                        <Button variant="danger" className="btn-sm" onClick={() => store.retract(o.overlay_id, 'producer')}>
                          Retract
                        </Button>
                      </div>
                    )}
                  </li>
                );
              })}
            </ul>
            <Button variant="ghost" className="btn-sm" style={{ marginTop: 12 }} onClick={() => store.clearDecisions()}>
              Reset all decisions
            </Button>
          </Card>

          <section aria-label="Program and agent trace" className="grow stack-lg" style={{ flexBasis: 560, gap: 18 }}>
            <Card order={2} style={{ padding: 12 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', margin: '0 4px 10px' }}>
                <h2 className="card-h3" style={{ margin: 0 }}>
                  Program preview · what viewers see
                </h2>
                <Chip tone="alert" style={{ borderRadius: 4 }}>
                  <span className="anim-blink" style={{ width: 7, height: 7, borderRadius: 4, background: 'currentColor' }} />
                  ON AIR
                </Chip>
              </div>
              <Stage2D store={store} time={clock} mode="broadcaster" density="standard" theme={prefs.theme} fav="kes-09" i18n={i18n} orientation="h" variant="real" ghosts={false} onFollow={() => {}} />
            </Card>

            {current && trace && (
              <Card order={3}>
                <div className="cluster" style={{ justifyContent: 'space-between', marginBottom: 12 }}>
                  <h2 className="card-title" style={{ margin: 0 }}>
                    Agent trace · {kindLabel(current)} {current.overlay_id}
                  </h2>
                  <Button variant="ghost" onClick={() => setTraceRun((n) => n + 1)}>
                    Replay trace
                  </Button>
                </div>
                <AgentTrace key={`${current.overlay_id}-${traceRun}`} rows={trace.rows} />
                {trace.note && (
                  <div className="tile anim-rise" style={{ marginTop: 14, fontSize: 13, lineHeight: 1.5, animationDelay: 'calc(var(--dur-hero) * 2)' }}>
                    {trace.note}
                  </div>
                )}
              </Card>
            )}

            <Card order={4} aria-labelledby="recap-builder-title">
              <h2 id="recap-builder-title" className="card-title" style={{ marginBottom: 4 }}>
                Recap builder
              </h2>
              <p className="muted" style={{ fontSize: 13, lineHeight: 1.5, marginBottom: 12 }}>
                Choose the moments and their order. Until you publish, viewers get the automatic recap: the period’s moments, biggest space first.
              </p>
              <RecapBuilder />
            </Card>
          </section>

          <section aria-label="Operations" className="side stack-lg" style={{ gap: 18 }}>
            <Card heading="Engineer" order={4}>
              <p className="muted" style={{ marginTop: -4, marginBottom: 12, fontSize: 13, lineHeight: 1.5 }}>
                {flag === 'undone' ? 'Explainer is back on the reasoning tier, as you asked. I’ll keep watching its latency.' : 'Explainer p95 rose to 2.6 s at 58:40. I switched it to the fast model tier through Azure MCP Server. p95 is back to 1.9 s.'}
              </p>
              <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexDirection: 'column', gap: 8 }}>
                {flags.map((f) => (
                  <li key={f.key} style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: 13 }}>
                    <span className="mono" style={{ fontSize: 12, flex: 1, minWidth: 0 }}>
                      {f.key}
                    </span>
                    <Chip tone={f.changed ? 'space' : 'outline'}>{f.value}</Chip>
                  </li>
                ))}
              </ul>
              {flag === 'fast' && (
                <div className="cluster muted" style={{ justifyContent: 'space-between', marginTop: 12, fontSize: 12 }}>
                  <span className="cluster" style={{ gap: 8 }}>
                    <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true">
                      <circle cx={9} cy={9} r={7} style={{ fill: 'none', stroke: 'var(--line)', strokeWidth: 2 }} />
                      <circle cx={9} cy={9} r={7} style={{ fill: 'none', stroke: 'var(--space)', strokeWidth: 2, strokeLinecap: 'round', transform: 'rotate(-90deg)', transformOrigin: '9px 9px', strokeDasharray: circumference, strokeDashoffset: circumference * (1 - left / 600), transition: 'stroke-dashoffset var(--dur-hero) var(--ease-linear)' }} />
                    </svg>
                    Reverts in {Math.floor(left / 60)}:{String(left % 60).padStart(2, '0')} unless kept
                  </span>
                  <span className="cluster" style={{ gap: 6 }}>
                    <Button variant="ghost" className="btn-sm" onClick={() => setFlag('kept')}>
                      Keep
                    </Button>
                    <Button variant="ghost" className="btn-sm" onClick={() => setFlag('undone')}>
                      Undo
                    </Button>
                  </span>
                </div>
              )}
            </Card>

            <Card order={5}>
              <div className="cluster" style={{ gap: 10, marginBottom: 6 }}>
                <PulseDot color="var(--ash)" />
                <h2 className="card-h3" style={{ margin: 0 }}>
                  Fabric Activator alert
                </h2>
              </div>
              <p style={{ marginBottom: 10, fontSize: 13, lineHeight: 1.5 }}>Fatigue gap forming: Ashmoor No. 2’s recovery speed is down 17% since 55′. Kestrel’s attacks down that flank are up 22 points.</p>
              <div className="cluster">
                <Button variant="primary" className="btn-sm" disabled={fatigueQueued} onClick={() => store.queue(fatigueGraphic())}>
                  {fatigueQueued ? 'Queued for approval' : 'Queue a fatigue-gap graphic'}
                </Button>
                {DASHBOARD_URL ? (
                  <a className="btn btn-ghost btn-sm press" href={DASHBOARD_URL} target="_blank" rel="noreferrer">
                    Fabric Real-Time Dashboard
                  </a>
                ) : (
                  <span className="btn btn-ghost btn-sm" aria-disabled="true" title="Set VITE_FABRIC_DASHBOARD_URL to link the dashboard">
                    Fabric dashboard · not connected
                  </span>
                )}
              </div>
            </Card>

            <Card order={6}>
              <h2 className="card-h3" style={{ marginBottom: 6 }}>
                Corrections
              </h2>
              <p className="muted" style={{ fontSize: 13, lineHeight: 1.5, marginBottom: 10 }}>
                When the feed corrects an event, the Fact-checker re-verifies every aired claim that cited it and the Producer retracts or patches the graphic, inside 5 s.
              </p>
              <Button variant="ghost" className="btn-sm" onClick={correct} disabled={steps.length > 0 && steps.length < 3}>
                Simulate a feed correction
              </Button>
              {steps.length > 0 && (
                <ol className="decision-log" style={{ marginTop: 10 }} role="status">
                  {steps.map((s) => (
                    <li key={s.text} className="anim-fade">
                      <span className="mono muted">+{(s.at / 1000).toFixed(1)} s</span> {s.text}
                    </li>
                  ))}
                </ol>
              )}
            </Card>

            <Card order={7}>
              <h2 className="card-h3" style={{ marginBottom: 6 }}>
                Decision log
              </h2>
              {store.decisions.length === 0 ? (
                <p className="muted" style={{ fontSize: 13 }}>
                  No decisions yet. Every approval, hold, skip and retraction is logged here and in the trace.
                </p>
              ) : (
                <ul className="decision-log">
                  {store.decisions.map((d, i) => (
                    <li key={i}>
                      <span className="mono muted">{d.at}</span> {d.action} · <span className="mono">{d.overlay_id}</span> · {d.by}
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          </section>
        </main>
      </div>
    </div>
  );
}
