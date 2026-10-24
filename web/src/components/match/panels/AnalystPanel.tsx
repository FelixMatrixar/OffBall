import { useState } from 'react';
import { LEADERS, leaderName } from '../../../lib/content';
import { momentT, type FeedStore, type FrameState } from '../../../lib/feed';
import { useI18n } from '../../../lib/i18n';
import { CF_ID, PLAYERS, RUN_FROM, distance, frameRef } from '../../../lib/match';
import type { Metric } from '../../../lib/prefs';
import { CONTROL_INDEX, SHAPE } from '../../../lib/stats';
import { ChartFrame, HeatMap, Leaderboard, PassNetwork, ShotMap, VegaChart, controlIndexSpec, heatTable, passNetworkTable, shapeSpec, shotTable } from '../../charts';
import { Card, CountUp, PendingChip, Segmented, Skeleton, Spinner, Tile, VerifiedChip } from '../../ui';
import { byMetric, type StatItem } from './shared';

type ChartId = 'control' | 'network' | 'shots' | 'shape' | 'heat';
const CHARTS: readonly { value: ChartId; label: string }[] = [
  { value: 'control', label: 'Control' },
  { value: 'network', label: 'Passes' },
  { value: 'shots', label: 'Shots' },
  { value: 'shape', label: 'Shape' },
  { value: 'heat', label: 'Heat map' },
];

interface Props {
  fs: FrameState;
  metric: Metric;
  store: FeedStore;
  passCorrected: boolean;
}

/**
 * Analyst: live metrics with the viewer's number first, space created with its 90% interval, the evidence behind
 * every claim, and charts on demand, each with a table view (PRD 8.1, 16.4).
 */
export function AnalystPanel({ fs, metric, store, passCorrected }: Props) {
  const { num, pack } = useI18n();
  const [chart, setChart] = useState<ChartId>('control');
  const [heatId, setHeatId] = useState('kes-09');
  const t = fs.t;
  const k9 = fs.pos['kes-09'];
  const items: StatItem[] = byMetric(
    [
      { key: 'run', label: 'Run length', value: num(k9 ? distance(k9, RUN_FROM) : 0, 1), unit: 'm' },
      { key: 'speed', label: 'No. 9 speed', value: num(fs.speedOf('kes-09'), 1), unit: 'km/h', metric: 'sprint' },
      { key: 'disp', label: 'No. 5 displaced', value: num(fs.displacement, 1), unit: 'm' },
      { key: 'gap', label: 'Gap-zone control', value: `${fs.gapPts >= 0 ? '+' : '−'}${num(Math.abs(fs.gapPts))}`, unit: 'pts', metric: 'space' },
      { key: 'pdist', label: 'Pass distance', value: num(passCorrected ? 27.4 : 28, 1), unit: 'm', ready: t >= 4.2, waiting: 'after the pass' },
      { key: 'pdiff', label: 'Pass difficulty', value: num(passCorrected ? 5.9 : 6.1, 1), unit: 'of 10', ready: t >= 4.2, waiting: 'after the pass', metric: 'pass' },
      { key: 'xg', label: 'Shot xG', value: num(0.31, 2), unit: '', ready: t >= 6.4, waiting: 'after the shot' },
      { key: 'line', label: 'Ashmoor line', value: num(fs.depth, 1), unit: 'm from goal' },
    ],
    metric,
  );
  const ready = t >= 6.4;
  const evidence = store
    .forMode('analyst')
    .filter((o) => o.kind === 'caption' && !o.counterfactual_id && !store.retractions.has(o.overlay_id))
    .map((o, i) => ({ id: o.evidence_ids[0] ?? frameRef(0), label: i === 0 ? 'Build-up' : pack.steps[Math.min(4, i - 1)], t: momentT(o), corrected: o.labels.includes('correction') }));

  return (
    <>
      <Card heading="Decoy run · live metrics">
        <div className="grid-2">
          {items.map((m, i) => (
            <Tile key={m.key} label={m.label} order={i} highlight={m.metric === metric}>
              {m.ready === false ? (
                // Not loading: the moment hasn't happened yet. Say what the number is waiting for.
                <div className="tile-value tile-waiting">
                  — <span className="tile-unit">{m.waiting}</span>
                </div>
              ) : (
                <div className="tile-value">
                  {m.value} <span className="tile-unit">{m.unit}</span>
                </div>
              )}
            </Tile>
          ))}
        </div>
      </Card>

      <Card order={2}>
        <h3 className="card-h3" style={{ margin: 0 }}>
          Space created by No. 9
        </h3>
        <p style={{ margin: '2px 0 0', fontSize: 12, color: 'var(--muted)' }}>Tactician · 32 re-runs each way</p>
        {ready ? (
          <>
            <div className="display tabular" style={{ fontSize: 40, margin: '6px 0 8px' }}>
              <CountUp value={41} suffix=" m²" />
            </div>
            <div className="meter" style={{ height: 14, borderRadius: 7, overflow: 'visible' }} aria-hidden="true">
              <div className="meter-fill anim-grow" style={{ insetInlineStart: '55%', width: '25%', background: 'var(--kes)', opacity: 0.5 }} />
              <div className="anim-pop" style={{ position: 'absolute', top: -3, bottom: -3, width: 4, borderRadius: 2, insetInlineStart: '68.3%', background: 'var(--text)', animationDelay: 'var(--dur-slide)' }} />
            </div>
          </>
        ) : (
          <>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, margin: '12px 0 10px', fontSize: 14, color: 'var(--muted)' }}>
              <Spinner color="var(--kes)" />
              Re-running the moment without the run…
            </div>
            <Skeleton height={14} radius={7} />
          </>
        )}
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: 'var(--muted)', marginTop: 4 }}>
          <span>0 m²</span>
          <span>90% interval 33–48 m²</span>
          <span>60 m²</span>
        </div>
        <p className="mono muted" style={{ fontSize: 11, marginTop: 6 }}>
          {CF_ID}
        </p>
      </Card>

      <Card order={3}>
        <h3 className="card-h3">Evidence</h3>
        <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexDirection: 'column', gap: 6 }}>
          {evidence.map((e) => {
            const verified = t >= e.t;
            return (
              <li key={e.id + e.label} style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: 13, minHeight: 26 }}>
                <span className="mono" style={{ fontSize: 12, color: 'var(--muted)', minWidth: 112 }}>
                  {e.id}
                </span>
                <span style={{ flex: 1, minWidth: 0, transition: 'color var(--dur-smooth)', color: verified ? 'var(--text)' : 'var(--muted)' }}>
                  {e.label}
                  {e.corrected ? ' · corrected' : ''}
                </span>
                {verified ? <VerifiedChip /> : <PendingChip />}
              </li>
            );
          })}
        </ul>
      </Card>

      <Card order={4}>
        <div className="stack">
          <Segmented options={CHARTS} value={chart} onChange={setChart} label="Chart" />
          {chart === 'control' && (
            <ChartFrame
              title="Control index"
              name="control-index"
              summary={`Control versus chaos: Kestrel Bay’s index is ${CONTROL_INDEX[63].kes} and Ashmoor’s ${CONTROL_INDEX[63].ash} at 63 minutes. Kestrel have been rising since the 55th minute.`}
              columns={['Minute', 'Kestrel Bay', 'Ashmoor']}
              rows={CONTROL_INDEX.filter((d) => d.minute % 5 === 0).map((d) => [d.minute, d.kes, d.ash])}
            >
              <VegaChart spec={controlIndexSpec(63)} label="Control index for both teams over 63 minutes" />
            </ChartFrame>
          )}
          {chart === 'network' && (
            <ChartFrame title="Kestrel Bay pass network" name="pass-network" summary="Most passes run through No. 6 and No. 8 in midfield; No. 9 is the least-connected player, because his job is to run, not to receive." {...passNetworkTable()}>
              <PassNetwork />
            </ChartFrame>
          )}
          {chart === 'shots' && (
            <ChartFrame title="Shot map" name="shot-map" summary="Kestrel Bay: 5 shots, 0.74 xG, one goal (0.31 xG, 63′). Ashmoor: 3 shots, 0.47 xG, their best chance a 0.34 xG save at 27′." {...shotTable()}>
              <ShotMap />
            </ChartFrame>
          )}
          {chart === 'shape' && (
            <ChartFrame
              title="Shape and pressure"
              name="shape"
              summary={`Ashmoor’s line has dropped from ${SHAPE[0].ashLine} m to ${SHAPE[12].ashLine} m since kick-off, while Kestrel press ${SHAPE[12].kesPress - SHAPE[0].kesPress >= 0 ? 'higher' : 'lower'}.`}
              columns={['Minute', 'Ashmoor line height (m)', 'Ashmoor width (m)', 'Ashmoor compactness (m)', 'Kestrel press height (m)']}
              rows={SHAPE.map((d) => [d.minute, d.ashLine, d.ashWidth, d.ashCompact, d.kesPress])}
            >
              <VegaChart spec={shapeSpec()} label="Line height, width, compactness and press height every five minutes" height={200} />
            </ChartFrame>
          )}
          {chart === 'heat' && (
            <>
              <label className="field-label" htmlFor="heat-player" style={{ marginBottom: 0 }}>
                Player
              </label>
              <select id="heat-player" className="select" value={heatId} onChange={(e) => setHeatId(e.target.value)}>
                {PLAYERS.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.team.toUpperCase()} No. {p.num} · {p.name}
                  </option>
                ))}
              </select>
              <ChartFrame title="Heat map" name={`heat-${heatId}`} summary="Brighter cells are where the player spent more time this match." {...heatTable(heatId)}>
                <HeatMap id={heatId} />
              </ChartFrame>
            </>
          )}
        </div>
      </Card>

      <Card order={5}>
        <ChartFrame
          title="Space Created · this match"
          name="space-created"
          summary={`${leaderName(LEADERS[0].id)} leads with ${LEADERS[0].v} m² (90% interval ${LEADERS[0].lo}–${LEADERS[0].hi}). Defenders earn credit too, for cover and runners passed on.`}
          columns={['Player', 'Space created (m²)', '90% interval low', '90% interval high']}
          rows={LEADERS.map((l) => [leaderName(l.id), l.v, l.lo, l.hi])}
        >
          <Leaderboard rows={LEADERS} max={140} />
        </ChartFrame>
      </Card>
    </>
  );
}
