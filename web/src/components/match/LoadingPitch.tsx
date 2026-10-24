import { PitchMarkings, VIEWBOX, type Orientation } from '../pitch';
import { CheckIcon, Spinner } from '../ui';
import { cx } from '../../lib/cx';

/** The three loading checks: ticked, in progress, still to come. */
export function LoadChecks({ checks, stage, className }: { checks: readonly string[]; stage: number; className?: string }) {
  return (
    // The status wraps the list, so the list keeps its own role for screen readers.
    <div className={cx('load-checks', className)} role="status">
      <ul className="load-checks-list">
        {checks.map((c, i) => {
          const state = i < stage ? 'done' : i === stage ? 'now' : 'next';
          return (
            <li key={i} className="load-check" data-state={state}>
              <span className="load-check-icon" aria-hidden="true">
                {state === 'done' ? <CheckIcon draw size={12} /> : state === 'now' ? <Spinner /> : null}
              </span>
              {c}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

/**
 * The loading state (PRD 15.11): the pitch's chalk lines draw themselves in under a slow shimmer, while three checks
 * tick off in order on a card over the centre circle.
 */
export function LoadingPitch({ stage, orientation, checks }: { stage: number; orientation: Orientation; checks: readonly [string, string, string] }) {
  return (
    <div className="pitch-card" aria-busy="true">
      <div className={cx('pitch', 'pitch-loading', orientation === 'v' && 'pitch-v')} dir="ltr">
        <svg viewBox={VIEWBOX[orientation]} className="pitch-layer" aria-hidden="true">
          <PitchMarkings orientation={orientation} drawIn />
        </svg>
        <span className="pitch-sweep" aria-hidden="true" />
      </div>
      <LoadChecks checks={checks} stage={stage} className="load-checks-over anim-pop" />
    </div>
  );
}
