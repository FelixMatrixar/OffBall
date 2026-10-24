import { useEffect, useMemo, useRef, useState } from 'react';
import { Stage2D } from '../components/match/Stage2D';
import { Stage3D } from '../components/match/Stage3D';
import { T_LOOP, ms, useFeedSource, useFeedStore, type TimeSource } from '../lib/feed';
import { useDocumentLocale, useI18n } from '../lib/i18n';
import { usePrefs, type View } from '../lib/prefs';

/** The hook `scripts/render-clips.mjs` drives: move to a moment time, then resolve once that frame is drawn. */
interface ClipControl {
  seek: (t: number) => Promise<void>;
  /** True once the stage has drawn its first frame. */
  ready: () => boolean;
  duration: number;
}

declare global {
  interface Window {
    __offballClip?: ClipControl;
  }
}

const nextFrame = () => new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));

/**
 * The stage on its own, for the pre-rendered clips of tier D and the vertical share clip (PRD 16.2, 16.8). Nothing
 * moves by itself: the renderer steps a timeline, and the scene, the camera and even the labels' CSS entrances all
 * follow it, so every captured frame is exact however long it takes to capture. Options: view (2d or a 3D camera),
 * w and h in pixels, and captions=1 to burn the caption in for sharing.
 */
export function ClipView() {
  const { prefs } = usePrefs();
  const i18n = useI18n();
  useDocumentLocale(prefs.lang);
  const query = useMemo(() => new URLSearchParams(window.location.hash.split('?')[1] ?? ''), []);
  const view = (query.get('view') ?? 'broadcast') as View;
  const width = Number(query.get('w') ?? 1280);
  const height = Number(query.get('h') ?? 720);
  const captions = query.get('captions') === '1';
  const portrait = height > width;
  const spec = useMemo(() => ({ kind: 'replay' as const }), []);
  useFeedSource(spec);
  const store = useFeedStore();
  const [t, setT] = useState(Number(query.get('t') ?? 0));
  const tRef = useRef(t);
  const time = useMemo<TimeSource>(() => ({ t, now: () => tRef.current, wall: () => tRef.current * 1000 }), [t]);

  useEffect(() => {
    // Each CSS animation is pinned to the clip time it started at, then seeked rather than left to run.
    const started = new WeakMap<Animation, number>();
    const pin = (clipMs: number) => {
      for (const a of document.getAnimations()) {
        if (!started.has(a)) started.set(a, clipMs);
        a.pause();
        a.currentTime = clipMs - started.get(a)!;
      }
    };
    window.__offballClip = {
      duration: T_LOOP,
      // The 2D stage is complete once it has drawn; the 3D one once its materials have compiled.
      ready: () => !!document.querySelector('.clip .pitch-stage[data-ready="true"], .clip .pitch:not(.pitch-3d) .pitch-stage[data-resting]'),
      seek: async (v: number) => {
        tRef.current = v;
        setT(v);
        // React commits the new labels, the frame loop draws and places them, then the animations are pinned.
        await nextFrame();
        await nextFrame();
        pin(v * 1000);
        await nextFrame();
      },
    };
    return () => {
      delete window.__offballClip;
    };
  }, []);

  const mode = prefs.mode;
  const caption = store.active(ms(t), { mode, whatIf: false, fav: prefs.fav }).find((a) => a.overlay.kind === 'caption');
  const captionText = caption ? (caption.overlay.text[prefs.lang] ?? caption.overlay.text.en ?? '').replace('{count}', '1') : '';
  const stageProps = { store, time, mode, density: prefs.density, theme: prefs.theme, fav: prefs.fav, i18n, onFollow: () => {} } as const;

  return (
    <div className={portrait ? 'clip clip-portrait' : 'clip'} style={{ width, height }}>
      <h1 className="sr-only">OffBall clip</h1>
      {view === '2d' ? (
        <Stage2D {...stageProps} orientation={portrait ? 'v' : 'h'} variant="real" ghosts={false} />
      ) : (
        <Stage3D {...stageProps} view={view} tier="B" variant="real" ghosts={false} portrait={portrait} onFail={(reason) => console.error(`Clip: the 3D view failed: ${reason}`)} />
      )}
      {captions && (
        <p className="clip-caption" lang={prefs.lang}>
          {captionText}
        </p>
      )}
      <p className="clip-label">OffBall · synthetic match · AI-generated graphics</p>
    </div>
  );
}
