import { momentT, type FeedStore, type Overlay } from '../../../lib/feed';
import { Button, Card, CheckIcon, Chip, stagger } from '../../ui';

export type QueueState = 'Queued' | 'Waiting' | 'On air' | 'Held' | 'Skipped' | 'Retracted' | 'Done';

/** Where a broadcaster graphic stands at a moment time. */
export function queueState(o: Overlay, t: number, retracted: boolean): QueueState {
  if (retracted) return 'Retracted';
  if (o.approval === 'held') return 'Held';
  if (o.approval === 'skipped' || o.approval === 'rejected') return 'Skipped';
  if (o.approval === 'pending') return 'Waiting';
  const start = momentT(o);
  const end = start + (o.t_end_ms - o.t_start_ms) / 1000;
  if (t < start) return 'Queued';
  return t < end ? 'On air' : 'Done';
}

/** One row per graphic; the ghost replay's parts travel together under its counterfactual ID. */
export function broadcastQueue(store: FeedStore): Overlay[] {
  const seen = new Set<string>();
  return store.forMode('broadcaster').filter((o) => {
    if (o.kind === 'caption' && !o.counterfactual_id) return false;
    if (o.counterfactual_id) {
      if (seen.has(o.counterfactual_id)) return false;
      seen.add(o.counterfactual_id);
    }
    return true;
  });
}

/** Approve, hold or skip a graphic, including every part of a ghost replay. */
export function decideAll(store: FeedStore, o: Overlay, approval: Overlay['approval']) {
  const parts = o.counterfactual_id ? store.forMode('broadcaster').filter((x) => x.counterfactual_id === o.counterfactual_id) : [o];
  parts.forEach((p) => store.decide(p.overlay_id, approval));
}

export const kindLabel = (o: Overlay) => (o.counterfactual_id ? 'ghost_replay' : o.kind);

/**
 * A graphic's state, styled so the one that matters reads at a glance: on air in the program monitor's red with its
 * live dot, waiting for a decision in the accent, retracted or skipped in danger, and queued or done quiet.
 */
export function QueueChip({ state, approved = false }: { state: QueueState; approved?: boolean }) {
  const tone = state === 'On air' ? 'alert' : state === 'Retracted' || state === 'Skipped' ? 'danger' : state === 'Waiting' || state === 'Held' ? 'accent' : 'muted';
  return (
    <Chip tone={tone}>
      {state === 'On air' && <span className="anim-blink" style={{ width: 7, height: 7, borderRadius: 4, background: 'currentColor' }} />}
      {approved && state !== 'On air' && (
        <span className="anim-pop" style={{ display: 'inline-flex' }}>
          <CheckIcon size={11} />
        </span>
      )}
      {state}
    </Chip>
  );
}

/** Broadcaster mode: the producer's queue, live. Decisions here reach every open view (PRD 10.6). */
export function BroadcasterPanel({ store, t }: { store: FeedStore; t: number }) {
  const queue = broadcastQueue(store);
  return (
    <>
      <Card heading="Graphics queue">
        <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexDirection: 'column', gap: 8 }}>
          {queue.map((o, i) => {
            const state = queueState(o, t, store.retractions.has(o.overlay_id));
            const open = state === 'Waiting' || state === 'Held';
            const live = state === 'On air' || state === 'Queued';
            return (
              <li key={o.overlay_id} className="tile anim-rise" style={{ ...stagger(i), boxShadow: open ? 'inset 0 0 0 1px var(--space)' : 'none' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, alignItems: 'center' }}>
                  <span className="mono" style={{ fontSize: 13 }}>
                    {kindLabel(o)}
                  </span>
                  <QueueChip state={state} />
                </div>
                <div style={{ fontSize: 12, color: 'var(--muted)', marginTop: 4 }}>
                  confidence {o.confidence.toFixed(2)} · {o.approval} · {o.overlay_id}
                </div>
                {open && (
                  <div className="anim-fade cluster" style={{ marginTop: 8, gap: 6 }}>
                    <Button variant="primary" onClick={() => decideAll(store, o, 'approved')}>
                      Approve
                    </Button>
                    {state !== 'Held' && (
                      <Button variant="ghost" onClick={() => decideAll(store, o, 'held')}>
                        Hold
                      </Button>
                    )}
                    <Button variant="ghost" onClick={() => decideAll(store, o, 'skipped')}>
                      Skip
                    </Button>
                  </div>
                )}
                {live && o.approval !== 'pending' && (
                  <div style={{ marginTop: 8 }}>
                    <Button variant="danger" className="btn-sm" onClick={() => store.retract(o.overlay_id, 'producer')}>
                      Retract
                    </Button>
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      </Card>
      <Card order={2}>
        <h3 className="card-h3" style={{ marginBottom: 6 }}>
          Engineer
        </h3>
        <p style={{ marginBottom: 12, fontSize: 13, lineHeight: 1.5, color: 'var(--muted)' }}>Explainer p95 at 1.9 s, inside its 3 s budget. Ingest lag 140 ms. No degrade flags changed.</p>
        <a href="#/producer" style={{ fontWeight: 600, fontSize: 14 }}>
          Open the producer console
        </a>
      </Card>
    </>
  );
}
