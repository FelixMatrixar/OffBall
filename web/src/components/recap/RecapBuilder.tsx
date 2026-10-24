import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { tokenMs } from '../../lib/motion';
import { CLUBS } from '../../lib/match';
import { usePrefs } from '../../lib/prefs';
import { autoPackage, momentById, publishRecap, useRecapPackage, withdrawRecap, type RecapKind, type RecapMoment, type RecapPackage } from '../../lib/recap';
import { Button, Chip, Segmented, Switch } from '../ui';
import { MomentDiagram } from './MomentDiagram';

const KINDS: readonly { value: RecapKind; label: string }[] = [
  { value: 'halftime', label: 'Halftime' },
  { value: 'fulltime', label: 'Full time' },
];

interface Draft {
  /** Every moment of the period, in the order the recap tells them. */
  order: string[];
  included: string[];
  spoilerSafe: boolean;
}

/** A package as an editable draft: its moments in order, then the period's others, left out. */
function draftOf(pkg: RecapPackage): Draft {
  const rest = autoPackage(pkg.kind).moments.filter((id) => !pkg.moments.includes(id));
  return { order: [...pkg.moments, ...rest], included: [...pkg.moments], spoilerSafe: pkg.spoilerSafe };
}

const time = (iso: string) => new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

/**
 * The producer's recap builder (PRD 15.6): pick the period's moments, put them in order, make it spoiler-safe, and
 * publish. Every open recap on this device updates at once; withdrawing returns viewers to the automatic recap.
 */
export function RecapBuilder() {
  const { reducedMotion } = usePrefs();
  const [kind, setKind] = useState<RecapKind>('halftime');
  const live = useRecapPackage(kind);
  const [draft, setDraft] = useState(() => draftOf(live));
  const [said, setSaid] = useState('');
  // What's published is the starting point, whenever the period changes or a publish arrives from anywhere.
  useEffect(() => setDraft(draftOf(live)), [live]);

  const moments = draft.order.filter((id) => draft.included.includes(id));
  const differs = moments.join() !== live.moments.join() || draft.spoilerSafe !== live.spoilerSafe;
  const status = live.publishedAt ? (differs ? 'Unpublished changes' : `Published at ${time(live.publishedAt)}`) : differs ? 'Draft' : 'Automatic';

  // Reordering slides the rows to their new places (FLIP), and keeps focus on the button that moved them.
  const rows = useRef(new Map<string, HTMLLIElement>());
  const before = useRef(new Map<string, number>());
  const refocus = useRef<{ id: string; dir: 'up' | 'down' } | null>(null);
  useLayoutEffect(() => {
    const was = before.current;
    before.current = new Map();
    if (!reducedMotion)
      for (const [id, el] of rows.current) {
        const top = was.get(id);
        if (top === undefined) continue;
        const dy = top - el.getBoundingClientRect().top;
        if (Math.abs(dy) < 1) continue;
        const ease = getComputedStyle(el).getPropertyValue('--ease-standard').trim() || 'ease-out';
        el.animate([{ transform: `translateY(${dy}px)` }, { transform: 'none' }], { duration: tokenMs('--dur-smooth'), easing: ease });
      }
    const f = refocus.current;
    refocus.current = null;
    if (f) {
      const row = rows.current.get(f.id);
      const want = row?.querySelector<HTMLButtonElement>(`[data-move='${f.dir}']:not(:disabled)`) ?? row?.querySelector<HTMLButtonElement>('[data-move]:not(:disabled)');
      want?.focus();
    }
  }, [draft.order, reducedMotion]);

  const move = (m: RecapMoment, by: -1 | 1) => {
    const i = draft.order.indexOf(m.id);
    const j = i + by;
    if (j < 0 || j >= draft.order.length) return;
    for (const [id, el] of rows.current) before.current.set(id, el.getBoundingClientRect().top);
    refocus.current = { id: m.id, dir: by < 0 ? 'up' : 'down' };
    const order = draft.order.slice();
    [order[i], order[j]] = [order[j], order[i]];
    setDraft({ ...draft, order });
    setSaid(`${m.minute}′ moment moved to ${j + 1} of ${order.length}.`);
  };
  const toggle = (id: string, on: boolean) => setDraft({ ...draft, included: on ? [...draft.included, id] : draft.included.filter((x) => x !== id) });
  const publish = () => {
    publishRecap({ kind, moments, spoilerSafe: draft.spoilerSafe, publishedAt: new Date().toISOString() });
    setSaid(`${kind === 'halftime' ? 'Halftime' : 'Full-time'} recap published with ${moments.length} moments.`);
  };
  const withdraw = () => {
    withdrawRecap(kind);
    setSaid('Recap withdrawn. Viewers see the automatic recap again.');
  };

  return (
    <div className="stack" style={{ gap: 12 }}>
      <div className="cluster" style={{ justifyContent: 'space-between', gap: 10 }}>
        <Segmented options={KINDS} value={kind} onChange={setKind} label="Recap period" />
        <Chip tone={status.startsWith('Published') ? 'space' : status === 'Automatic' ? 'outline' : 'accent'}>{status}</Chip>
      </div>
      <ol className="recap-builder" aria-label={`${kind === 'halftime' ? 'Halftime' : 'Full-time'} moments, in recap order`}>
        {draft.order.map((id, i) => {
          const m = momentById(id);
          if (!m) return null;
          const on = draft.included.includes(id);
          const title = draft.spoilerSafe ? m.safeTitle : m.title;
          return (
            <li
              key={id}
              ref={(el) => {
                if (el) rows.current.set(id, el);
                else rows.current.delete(id);
              }}
              className="tile recap-row"
              data-included={on}
            >
              <MomentDiagram m={m} title={title} className="recap-thumb" decorative />
              <label className="recap-row-main">
                <input type="checkbox" className="check" checked={on} onChange={(e) => toggle(id, e.target.checked)} />
                <span className="stack" style={{ gap: 2, minWidth: 0 }}>
                  <span style={{ fontSize: 14, fontWeight: 600, lineHeight: 1.35 }}>
                    <span className="tabular">{m.minute}′</span> · {title}
                  </span>
                  <span className="muted" style={{ fontSize: 12 }}>
                    {CLUBS[m.team].name} · <span className="tabular">{m.space[0]}</span> m² created
                  </span>
                </span>
              </label>
              <span className="recap-row-move">
                <Button icon className="btn-sm" data-move="up" aria-label={`Move the ${m.minute}′ moment up`} disabled={i === 0} onClick={() => move(m, -1)}>
                  <span aria-hidden="true">↑</span>
                </Button>
                <Button icon className="btn-sm" data-move="down" aria-label={`Move the ${m.minute}′ moment down`} disabled={i === draft.order.length - 1} onClick={() => move(m, 1)}>
                  <span aria-hidden="true">↓</span>
                </Button>
              </span>
            </li>
          );
        })}
      </ol>
      <Switch checked={draft.spoilerSafe} onChange={(spoilerSafe) => setDraft({ ...draft, spoilerSafe })} label="Spoiler-safe: no scores or outcomes" />
      <div className="cluster" style={{ gap: 8 }}>
        <Button variant="primary" className="btn-sm" disabled={moments.length === 0 || (!differs && !!live.publishedAt)} onClick={publish}>
          {live.publishedAt ? 'Publish changes' : 'Publish recap'}
        </Button>
        {live.publishedAt && (
          <Button variant="ghost" className="btn-sm" onClick={withdraw}>
            Withdraw
          </Button>
        )}
        <Button variant="ghost" className="btn-sm" disabled={!differs} onClick={() => setDraft(draftOf(live))}>
          Discard changes
        </Button>
        <a className="btn btn-ghost btn-sm press" href={`#/recap?kind=${kind}`} target="_blank" rel="noreferrer">
          Open the recap
        </a>
      </div>
      <p role="status" className="muted" style={{ fontSize: 12, minHeight: 16, margin: 0 }}>
        {said}
      </p>
    </div>
  );
}
