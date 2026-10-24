import { useEffect, useRef, type MutableRefObject, type ReactNode } from 'react';
import { cx } from '../../lib/cx';
import type { MatchClock } from '../../lib/feed';
import { onFrame } from '../../lib/frame-loop';
import type { Mode } from '../../lib/prefs';
import type { Snapshotter } from '../pitch/snapshot';

/** One clip per family of modes; `npm run clips` renders them from the real renderer into public/clips. */
const CLIP_FOR: Record<Mode, string> = {
  casual: 'showcase-casual',
  learn: 'showcase-casual',
  player: 'showcase-casual',
  audio: 'showcase-casual',
  analyst: 'showcase-analyst',
  broadcaster: 'showcase-broadcaster',
};

/** Fastest speed a video plays at natively; faster replays seek frame by frame instead. */
const MAX_RATE = 4;

/**
 * Tier D (PRD 16.2): a pre-rendered clip of the moment with its graphics burned in, kept in step with the match
 * clock. The caption bar stays live DOM text in the viewer's language. It plays anywhere video plays, which is why
 * it's the last step down; it covers the replay, not a live match.
 */
export function StageVideo({
  clock,
  mode,
  whatIf,
  chips,
  corner,
  scrim,
  dim,
  portrait,
  snapshot,
}: {
  clock: MatchClock;
  mode: Mode;
  whatIf: boolean;
  chips?: ReactNode;
  corner?: ReactNode;
  scrim?: ReactNode;
  dim?: boolean;
  portrait?: boolean;
  /** Filled with this stage's snapshot, while it shows (PRD 16.8). */
  snapshot?: MutableRefObject<Snapshotter | null>;
}) {
  const ref = useRef<HTMLVideoElement>(null);
  const clockRef = useRef(clock);
  clockRef.current = clock;
  const name = CLIP_FOR[mode];

  useEffect(
    () =>
      onFrame(() => {
        const v = ref.current;
        if (!v || v.readyState < 1) return;
        const c = clockRef.current;
        const t = c.now();
        if (c.playing && c.speed <= MAX_RATE) {
          if (v.playbackRate !== c.speed) v.playbackRate = c.speed;
          if (v.paused) void v.play().catch(() => undefined);
          // Correct drift rather than chase every frame: a seek costs more than a quarter-second's slip.
          if (Math.abs(v.currentTime - t) > 0.25) v.currentTime = t;
        } else {
          if (!v.paused) v.pause();
          if (Math.abs(v.currentTime - t) > 1 / 60) v.currentTime = t;
        }
      }),
    [],
  );

  // The snapshot: the clip's current frame, cropped as it shows (object-fit: cover), graphics and all.
  useEffect(() => {
    if (!snapshot) return;
    const shooter: Snapshotter = {
      formats: ['png'],
      take: async (_format, scale) => {
        const v = ref.current;
        if (!v || v.readyState < 2 || !v.videoWidth) throw new Error('The clip hasn’t loaded yet');
        const r = v.getBoundingClientRect();
        const out = document.createElement('canvas');
        out.width = Math.round(r.width * scale);
        out.height = Math.round(r.height * scale);
        const ctx = out.getContext('2d');
        if (!ctx) throw new Error('No canvas for the snapshot');
        const fit = Math.max(out.width / v.videoWidth, out.height / v.videoHeight);
        const w = v.videoWidth * fit;
        const h = v.videoHeight * fit;
        ctx.imageSmoothingQuality = 'high';
        ctx.drawImage(v, (out.width - w) / 2, (out.height - h) / 2, w, h);
        return { width: r.width, height: r.height, canvas: out };
      },
    };
    snapshot.current = shooter;
    return () => {
      if (snapshot.current === shooter) snapshot.current = null;
    };
  }, [snapshot]);

  return (
    <div className={cx('pitch', 'pitch-video', portrait && 'pitch-3d-portrait', dim && 'pitch-dim')} dir="ltr">
      <video
        ref={ref}
        key={name}
        className="pitch-video-el"
        src={`clips/${name}.mp4`}
        poster={`clips/${name}.jpg`}
        muted
        playsInline
        preload="auto"
        aria-label="A recorded clip of the moment from the broadcast camera, with its graphics drawn in. Players can’t be picked out in this view; the caption below says what’s happening."
      />
      {whatIf && <p className="pitch-video-note">The what-if view needs live drawing. This clip shows the real play.</p>}
      {scrim}
      {chips && <div className="pitch-chips">{chips}</div>}
      {corner && <div className="pitch-corner">{corner}</div>}
    </div>
  );
}
