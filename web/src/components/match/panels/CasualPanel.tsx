import { useI18n } from '../../../lib/i18n';
import { Card, Tile, stagger } from '../../ui';
import type { StatItem } from './shared';

/** Casual: the goal's steps lighting up as they happen, plus the one number the viewer asked for. */
export function CasualPanel({ step, mine }: { step: number; mine: StatItem }) {
  const { pack, ui } = useI18n();
  return (
    <>
      <Card heading={ui.howGoal}>
        <p style={{ margin: '-6px 0 14px', color: 'var(--muted)', fontSize: 14 }}>{ui.howGoalHint}</p>
        <ol style={{ listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexDirection: 'column', gap: 8 }}>
          {pack.steps.map((text, i) => {
            const n = i + 1;
            const state = step === n ? 'current' : step > n ? 'done' : 'todo';
            return (
              <li key={n} className="step-item anim-rise" data-state={state} style={stagger(i)} aria-current={state === 'current' ? 'step' : undefined}>
                <span key={state === 'current' ? `now-${step}` : 'still'} className={state === 'current' ? 'step-badge anim-beat-once' : 'step-badge'}>
                  {n}
                </span>
                <span>{text}</span>
              </li>
            );
          })}
        </ol>
      </Card>
      <Card order={2}>
        <Tile label={`Your number · ${mine.label}`} highlight>
          <div className="tile-value">
            {mine.ready === false ? '—' : mine.value} <span className="tile-unit">{mine.unit}</span>
          </div>
        </Tile>
      </Card>
    </>
  );
}
