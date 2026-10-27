import { useEffect, useMemo, useRef, useState } from 'react';
import { fill } from '../../lib/i18n';
import type { ClubInfo, Moment } from '../../lib/player/api';
import { clockOf } from '../../lib/player/clock';
import type { PlayerWords } from '../../lib/player/words';
import { Chip, Segmented } from '../ui';

type ClubFilter = 'both' | 'home' | 'away';

interface MomentListProps {
  moments: readonly Moment[];
  home: ClubInfo;
  away: ClubInfo;
  /** The moment on screen now, or the one chosen. */
  current: string | null;
  label: (id: string) => string;
  w: PlayerWords;
  onPick: (m: Moment) => void;
}

/**
 * Every moment the models found, in match order, filterable by club, type, whether the crew explained it and
 * whether it led to a goal or shot. Picking one jumps there (PRD 15.2).
 */
export function MomentList({ moments, home, away, current, label, w, onPick }: MomentListProps) {
  const [club, setClub] = useState<ClubFilter>('both');
  const [type, setType] = useState('');
  const [built, setBuilt] = useState(false);
  const [chances, setChances] = useState(false);
  const listRef = useRef<HTMLOListElement>(null);
  const types = useMemo(() => [...new Set(moments.map((m) => m.type))].sort((a, b) => (w.types[a] ?? a).localeCompare(w.types[b] ?? b)), [moments, w]);
  const shown = moments.filter(
    (m) =>
      (club === 'both' || m.club_id === (club === 'home' ? home.club_id : away.club_id)) &&
      (!type || m.type === type) &&
      (!built || m.graphics === 'published' || m.graphics === 'corrected') &&
      (!chances || m.outcome !== 'none'),
  );

  // Keep the moment on screen in view, without moving the page.
  useEffect(() => {
    const list = listRef.current;
    const el = current ? list?.querySelector<HTMLElement>(`[data-id="${CSS.escape(current)}"]`) : null;
    if (!list || !el) return;
    const top = el.offsetTop - list.offsetTop;
    if (top < list.scrollTop || top + el.offsetHeight > list.scrollTop + list.clientHeight) list.scrollTo({ top: top - list.clientHeight / 3, behavior: 'smooth' });
  }, [current]);

  return (
    <section className="card moment-list" aria-label={fill(w.moments, { n: moments.length })}>
      <div className="stack" style={{ gap: 10 }}>
        <h2 className="card-h3">{fill(w.moments, { n: shown.length })}</h2>
        <Segmented
          options={[
            { value: 'both', label: w.allClubs },
            { value: 'home', label: home.short },
            { value: 'away', label: away.short },
          ]}
          value={club}
          onChange={setClub}
          label={w.allClubs}
          minWidth={64}
        />
        <div className="cluster" style={{ gap: 8 }}>
          <select className="select select-sm" value={type} onChange={(e) => setType(e.target.value)} aria-label={w.allTypes}>
            <option value="">{w.allTypes}</option>
            {types.map((t) => (
              <option key={t} value={t}>
                {w.types[t] ?? t}
              </option>
            ))}
          </select>
          <button type="button" className={`chip chip-lg press ${built ? 'chip-space' : 'chip-outline'}`} aria-pressed={built} onClick={() => setBuilt(!built)}>
            {w.withGraphics}
          </button>
          <button type="button" className={`chip chip-lg press ${chances ? 'chip-space' : 'chip-outline'}`} aria-pressed={chances} onClick={() => setChances(!chances)}>
            {w.chances}
          </button>
        </div>
      </div>
      <ol ref={listRef} className="moment-items">
        {shown.map((m) => {
          const on = m.candidate_id === current;
          const explained = m.graphics === 'published' || m.graphics === 'corrected';
          return (
            <li key={m.candidate_id} data-id={m.candidate_id}>
              <button type="button" className="moment-item press" aria-current={on ? 'true' : undefined} onClick={() => onPick(m)}>
                <span className="mono moment-clock">{clockOf({ period: m.period, t_ms: m.t_start_ms })}</span>
                <span className="moment-main">
                  <span className="moment-type">
                    {w.types[m.type] ?? m.type}
                    {m.outcome !== 'none' && (
                      <Chip tone={m.outcome === 'goal' ? 'space' : 'accent'} className="moment-outcome">
                        {m.outcome === 'goal' ? w.goal : w.shot}
                      </Chip>
                    )}
                  </span>
                  <span className="moment-who muted">{label(m.creator_id)}</span>
                </span>
                <span className={`moment-dot${explained ? ' moment-dot-on' : ''}`} title={w.graphics[m.graphics]} aria-label={w.graphics[m.graphics]} />
              </button>
            </li>
          );
        })}
        {!shown.length && <li className="muted moment-empty">{w.none}</li>}
      </ol>
    </section>
  );
}
