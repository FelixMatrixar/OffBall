import { CLUBS } from '../../lib/match';
import type { Club } from '../../lib/prefs';
import { LiveBadge } from '../ui';

interface ScoreboardProps {
  score: { kes: number; ash: number };
  clock: string;
  yours?: Club;
  live?: boolean;
  liveLabel?: string;
  compact?: boolean;
}

const yourStyle = (on: boolean) => ({ transition: 'box-shadow var(--dur-smooth)', boxShadow: on ? 'inset 0 -3px 0 var(--space)' : 'none' });

/** The score bug. A changed score pops in; your club gets an underline (PRD 15.9). */
export function Scoreboard({ score, clock, yours = 'none', live = true, liveLabel = 'LIVE', compact = false }: ScoreboardProps) {
  const label = `${CLUBS.kes.name} ${score.kes}, ${CLUBS.ash.name} ${score.ash}, ${clock}${yours !== 'none' ? `, your team is ${CLUBS[yours].name}` : ''}`;
  return (
    <div className="scoreboard" role="group" aria-label={label} dir="ltr" data-compact={compact}>
      <span className="score-kit" style={{ background: 'var(--kes)' }} aria-hidden="true" />
      <span style={yourStyle(yours === 'kes')} aria-hidden="true">
        {CLUBS.kes.short}
      </span>
      <span className="tabular score-digits" aria-hidden="true">
        <span key={`h${score.kes}`} className="anim-pop" style={{ display: 'inline-block' }}>
          {score.kes}
        </span>
        –
        <span key={`a${score.ash}`} className="anim-pop" style={{ display: 'inline-block' }}>
          {score.ash}
        </span>
      </span>
      <span style={yourStyle(yours === 'ash')} aria-hidden="true">
        {CLUBS.ash.short}
      </span>
      <span className="score-kit" style={{ background: 'var(--ash)' }} aria-hidden="true" />
      <span className="tabular score-clock" aria-hidden="true">
        {clock}
      </span>
      {live && (
        <span style={{ fontFamily: 'var(--font-body)' }} aria-hidden="true">
          <LiveBadge label={liveLabel} />
        </span>
      )}
    </div>
  );
}
