import { useState } from 'react';
import { focusStats } from '../../../lib/content';
import type { FrameState } from '../../../lib/feed';
import { useI18n } from '../../../lib/i18n';
import { CLUBS, player } from '../../../lib/match';
import type { Metric } from '../../../lib/prefs';
import { useServed } from '../../../lib/served';
import { distanceSeries } from '../../../lib/stats';
import { ChartFrame, HeatMap, RunMap, Sparkline, heatTable, runTable } from '../../charts';
import { Button, Card, Segmented, Tile } from '../../ui';
import { byMetric, type StatItem } from './shared';

const ROLE: Record<string, string> = { GK: 'Goalkeeper', RB: 'Right-back', LB: 'Left-back', CB: 'Centre-back', DM: 'Holding midfielder', CM: 'Midfielder', AM: 'Attacking midfielder', RM: 'Right midfielder', LM: 'Left midfielder', RW: 'Right winger', LW: 'Left winger', ST: 'Striker' };

/**
 * Player focus: the favourite's running tally of off-ball work (runs, defenders dragged, space created, sprints,
 * distance) with season context, physical sparklines and a run map (PRD 8.1, 16.4).
 */
export function PlayerPanel({ fav, fs, speeds, metric, onChange }: { fav: string; fs: FrameState; speeds: readonly number[]; metric: Metric; onChange: () => void }) {
  const { num } = useI18n();
  const [view, setView] = useState<'runs' | 'heat'>('runs');
  useServed();
  const p = player(fav);
  const s = focusStats(fav);
  const t = fs.t;
  const pick = ([before, after, at]: [number, number, number]) => (at > 0 && t >= at ? after : before);
  const speed = fs.speedOf(fav);
  const tallies: StatItem[] = byMetric(
    [
      { key: 'runs', label: 'Off-ball runs', value: String(pick(s.runs)) },
      { key: 'dragged', label: 'Defenders dragged', value: String(pick(s.dragged)) },
      { key: 'space', label: p.team === 'ash' && p.role === 'CB' ? 'Space protected' : 'Space created', value: String(pick(s.space)), unit: 'm²', metric: 'space' },
      { key: 'sprints', label: 'Sprints', value: String(pick(s.sprints)) },
      { key: 'distance', label: 'Distance', value: num(s.distanceKm + t * 0.002, 2), unit: 'km' },
      { key: 'top', label: 'Top speed', value: num(Math.max(s.topSpeed, speed), 1), unit: 'km/h', metric: 'sprint' },
    ],
    metric,
  );
  const dist = distanceSeries(fav);
  return (
    <>
      <Card>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 14 }}>
          <span
            className="display"
            aria-hidden="true"
            style={{ width: 48, height: 48, borderRadius: 24, background: `var(--${p.team})`, color: `var(--on-${p.team})`, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 26 }}
          >
            {p.num}
          </span>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div className="display" style={{ fontSize: 26 }}>
              {p.name}
            </div>
            <div style={{ fontSize: 13, color: 'var(--muted)' }}>
              {ROLE[p.role]} · {CLUBS[p.team].name} · following
            </div>
          </div>
          <Button variant="ghost" className="btn-sm" onClick={onChange}>
            Change
          </Button>
        </div>
        <div className="grid-2">
          {tallies.map((ty, i) => (
            <Tile key={ty.key} label={ty.label} order={i} highlight={ty.metric === metric}>
              <div className="tile-value" style={{ fontSize: 26 }}>
                {ty.value} {ty.unit && <span className="tile-unit">{ty.unit}</span>}
              </div>
            </Tile>
          ))}
        </div>
        <p style={{ marginTop: 12, fontSize: 13, color: 'var(--muted)', lineHeight: 1.5 }}>{s.season}</p>
      </Card>
      <Card order={2}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 8 }}>
          <h3 className="card-h3" style={{ margin: 0 }}>
            Speed, this move
          </h3>
          <span className="display tabular" style={{ fontSize: 26 }}>
            {num(speed, 1)} km/h
          </span>
        </div>
        <Sparkline values={speeds} max={36} span={37} threshold={25.2} thresholdLabel="sprint 25.2" label={`No. ${p.num}’s speed over this move, now ${num(speed, 1)} km/h.`} />
        <h3 className="card-h3" style={{ margin: '14px 0 6px' }}>
          Distance per 5 minutes
        </h3>
        <Sparkline values={dist.map((d) => d.metres)} max={900} span={dist.length} label={`Distance per five minutes, between ${Math.min(...dist.map((d) => d.metres))} and ${Math.max(...dist.map((d) => d.metres))} metres.`} color="var(--space)" live={false} />
      </Card>
      <Card order={3}>
        <div className="stack">
          <Segmented
            options={[
              { value: 'runs', label: 'Run map' },
              { value: 'heat', label: 'Heat map' },
            ]}
            value={view}
            onChange={setView}
            label="Player chart"
          />
          {view === 'runs' ? (
            <ChartFrame title={`No. ${p.num}’s runs by type`} name={`runs-${fav}`} summary={s.runsByType.map((r) => `${r.type}: ${r.n}`).join('; ') || 'No off-ball runs recorded.'} {...runTable(fav)}>
              <RunMap id={fav} />
            </ChartFrame>
          ) : (
            <ChartFrame title={`No. ${p.num}’s heat map`} name={`heat-${fav}`} summary="Brighter cells are where he spent more time this match." {...heatTable(fav)}>
              <HeatMap id={fav} />
            </ChartFrame>
          )}
        </div>
      </Card>
    </>
  );
}
