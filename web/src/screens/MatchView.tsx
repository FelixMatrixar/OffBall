import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { AskPanel } from '../components/ask/AskPanel';
import { ChartFrame, MomentumRibbon } from '../components/charts';
import {
  AnalystPanel,
  AudioPanel,
  BroadcasterPanel,
  CaptionBar,
  CasualPanel,
  DecisionPanel,
  LearnPanel,
  LiveRegion,
  LoadingPitch,
  METRIC_LABEL,
  ModeSwitcher,
  PairDialog,
  PersonalizeDrawer,
  PlayerPanel,
  ReplayBar,
  Scoreboard,
  ShortcutsDialog,
  Stage2D,
  Stage3D,
  StageVideo,
  useAnnouncer,
  useDecisions,
  type StatItem,
} from '../components/match';
import { apiBase } from '../lib/api';
import { RERUNS, counterfactualId } from '../lib/decisions';
import { GROUP_LABEL, STEP_DOWN_AT, groupsIn, learnedDensity, type HiddenByMode, type OverlayGroup } from '../lib/density';
import { composeSnapshot, type SnapshotFormat, type Snapshotter } from '../components/pitch/snapshot';
import { BottomSheet, Button, Chip, Drawer, ErrorBoundary, Logo, MenuButton, Segmented, Skeleton, Spinner, Switch, ToastStack, stagger, type ToastItem } from '../components/ui';
import { canSpeak, cue, speaker, unlockAudio, useVoices, voiceFor } from '../lib/audio';
import { focusStats } from '../lib/content';
import { download } from '../lib/export';
import { SPEEDS, frameState, momentT, ms, sourceFromLocation, useFeedSource, useFeedStore, useMatchClock, type SourceSpec } from '../lib/feed';
import { CONCEPT_AT_STEP, useGlossary } from '../lib/glossary';
import { useHashQuery, useOnline, useScreenClass } from '../lib/hooks';
import { LANGS, PACKS, fill, useDocumentLocale, useI18n } from '../lib/i18n';
import { CLUBS, GAP_CENTRE, T_END, clockLabel, player, stepAt } from '../lib/match';
import { useHostCode, usePairHost } from '../lib/pairing';
import { MODE_IDS, usePrefs, type Lang, type Mode, type View } from '../lib/prefs';
import { MOMENTUM } from '../lib/stats';
import { AVAILABLE_TIERS, TIERS, useTiers, type Tier } from '../lib/tiers';
import { VIEW_OPTIONS } from '../components/match/PersonalizeDrawer';
import { WholeMatchView } from './WholeMatchView';

type Panel = 'none' | 'personalize' | 'ask' | 'pair' | 'shortcuts' | 'panel';

const capitalise = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

const isTyping = (el: EventTarget | null) => el instanceof HTMLElement && (el.isContentEditable || ['INPUT', 'SELECT', 'TEXTAREA'].includes(el.tagName));

/** The caption bar and the side panel hold their shape while the match loads, so nothing jumps when it arrives. */
function CaptionSkeleton() {
  return (
    <div className="card caption-bar" aria-hidden="true">
      <div className="caption-bar-main stack" style={{ gap: 10 }}>
        <Skeleton width="72%" height={20} />
        <Skeleton width="38%" height={11} />
      </div>
    </div>
  );
}

function PanelSkeleton() {
  return (
    <div className="card panel-skeleton" aria-hidden="true">
      <Skeleton width="62%" height={22} />
      <Skeleton width="44%" height={12} style={{ marginTop: 8 }} />
      {[78, 64, 52, 70, 34].map((w, i) => (
        <div key={i} className="panel-skeleton-row anim-rise" style={stagger(i + 1)}>
          <Skeleton width={28} height={28} radius={14} />
          <Skeleton width={`${w}%`} height={14} />
        </div>
      ))}
    </div>
  );
}

/** The match the view opens on: Kestrel Bay against Ashmoor, the fixture of the showcase moment. */
export const DEFAULT_MATCH = 'm07';

/**
 * The match view. With an OffBall API it plays whole matches (`?m=`, Kestrel Bay against Ashmoor by default); without
 * one, or with a feed or a moment time in the address, it plays the showcase moment from its own replay.
 */
export function MatchView() {
  const m = useHashQuery('m');
  const query = new URLSearchParams(window.location.hash.split('?')[1] ?? '');
  const showcase = ['feed', 't', 'state', 'showcase'].some((k) => query.has(k));
  return apiBase() && !showcase ? <WholeMatchView matchId={m ?? DEFAULT_MATCH} /> : <ShowcaseMatchView />;
}

/** The showcase moment: Kestrel Bay's 63rd-minute decoy-run goal against Ashmoor, with every scripted feature. */
function ShowcaseMatchView() {
  const { prefs, update, reducedMotion } = usePrefs();
  const i18n = useI18n();
  const { lang, ui, pack, num } = i18n;
  useDocumentLocale(prefs.lang);
  const screen = useScreenClass();
  const online = useOnline();
  const preview = useHashQuery('state');
  const [whatIf, setWhatIf] = useState(false);
  const [simStall, setSimStall] = useState(false);
  const [simSlow, setSimSlow] = useState(false);
  const [panel, setPanel] = useState<Panel>('none');
  const [sheetOpen, setSheetOpen] = useState(false);
  const [panelCollapsed, setPanelCollapsed] = useState(false);
  const [explaining, setExplaining] = useState(false);
  const [narration, setNarration] = useState(true);
  const [loadStage, setLoadStage] = useState(preview === 'loading' ? 0 : 3);

  const spec = useMemo<SourceSpec>(() => (simStall ? { kind: 'live-sim', stall: { at: 2, for: 4 } } : sourceFromLocation()), [simStall]);
  const source = useFeedSource(spec);
  const store = useFeedStore();
  const clock = useMatchClock(store, !!source?.live);
  const t = clock.t;
  const step = stepAt(t);
  const t_ms = ms(t);
  // 3D starts when a 3D view is picked; if it can't start here, the 2D view stays for the session (PRD VIS-4).
  const [threeD, setThreeD] = useState<{ failed: boolean; got: Tier | null }>({ failed: false, got: null });
  const view = prefs.view;
  // The recorded clip (tier D) covers the replay only, never a live match.
  const live = !!source?.live;
  const available = AVAILABLE_TIERS.filter((tier) => !(threeD.failed && (tier === 'A' || tier === 'B')) && !(live && tier === 'D'));
  const tiers = useTiers({ view, choice: prefs.tier, slow: simSlow, available });
  const showVideo = tiers.tier === 'D' && !live;
  const show3D = !showVideo && view !== '2d' && (tiers.tier === 'A' || tiers.tier === 'B');
  const shownTier: Tier = showVideo ? 'D' : show3D ? (threeD.got ?? tiers.tier) : 'C';
  const { msg, announce } = useAnnouncer();
  // Re-renders once the device's voices load, so the voice label and speech pick them up.
  useVoices();
  const orientation = screen.phonePortrait ? 'v' : 'h';
  const mode = prefs.mode;
  const fav = prefs.fav;
  // Change one decision (PRD 10.10, 15.12): it takes the side panel's place, and its scenario is what the pitch shows.
  const decide = useDecisions(clock, mode, announce);
  const decisionScenario = decide.open ? decide.scenario : null;
  const decisionResult = decisionScenario?.phase === 'result';
  const decisionSplit = decisionResult && decide.split && !screen.phonePortrait;
  const openDecisions = () => {
    setWhatIf(false);
    setPanelCollapsed(false);
    decide.start();
    if (screen.phonePortrait) setSheetOpen(true);
    else if (screen.phoneLandscape) setPanel('panel');
    // Opened from the replay bar, below the pitch: bring the pitch and the panel, side by side, into view.
    else stageBox.current?.scrollIntoView({ block: 'start', behavior: reducedMotion ? 'auto' : 'smooth' });
  };
  const toggleWhatIf = (on: boolean) => {
    setWhatIf(on);
    if (on) decide.close();
  };
  const split = (whatIf && prefs.cfView === 'split') || decisionSplit;
  const prefsRef = useRef(prefs);
  prefsRef.current = prefs;

  // Adaptive density (PRD 8.2): the groups of pitch graphics the viewer hides, for each mode. With Adapt on they're
  // remembered on this device, and hiding two steps that mode's density down; with it off they last until the page closes.
  const [sessionHidden, setSessionHidden] = useState<HiddenByMode>({});
  const [densityNote, setDensityNote] = useState<ToastItem | null>(null);
  const modeGroups = useMemo(() => groupsIn(store.forMode(mode).filter((o) => !o.counterfactual_id).map((o) => o.kind)), [store, store.version, mode]);
  const hiddenNow = ((prefs.adapt ? prefs.hidden : sessionHidden)[mode] ?? []).filter((g) => modeGroups.includes(g));
  const density = learnedDensity(prefs.density, hiddenNow, prefs.adapt);
  const fewer = density !== prefs.density;
  const setHiddenFor = useCallback(
    (m: Mode, next: readonly OverlayGroup[]) => {
      const merge = (all: HiddenByMode): HiddenByMode => {
        const out = { ...all, [m]: next };
        if (!next.length) delete out[m];
        return out;
      };
      if (prefsRef.current.adapt) update({ hidden: merge(prefsRef.current.hidden) });
      else setSessionHidden(merge);
    },
    [update],
  );
  const toggleGroup = (g: OverlayGroup) => {
    const before = hiddenNow;
    const hiding = !before.includes(g);
    const next = hiding ? [...before, g] : before.filter((x) => x !== g);
    setHiddenFor(mode, next);
    const name = PACKS.en.modes[mode].label;
    const steps = prefs.adapt && hiding && next.length === STEP_DOWN_AT && learnedDensity(prefs.density, next, true) !== prefs.density;
    const text = hiding ? `${GROUP_LABEL[g]} hidden in ${name}.${steps ? ` ${name} now shows fewer overlays.` : ''}` : `${GROUP_LABEL[g]} back in ${name}.`;
    const undo = () => {
      setHiddenFor(mode, before);
      setDensityNote(null);
    };
    setDensityNote({ id: `density-${Date.now()}`, text, tone: 'info', action: { label: 'Undo', onClick: undo } });
    announce(text);
  };
  const showEverything = () => {
    const before = hiddenNow;
    setHiddenFor(mode, []);
    const text = `Everything back in ${PACKS.en.modes[mode].label}.`;
    setDensityNote({ id: `density-${Date.now()}`, text, tone: 'info', action: { label: 'Undo', onClick: () => (setHiddenFor(mode, before), setDensityNote(null)) } });
    announce(text);
  };
  // The note holds long enough to reach Undo, then goes.
  useEffect(() => {
    if (!densityNote) return;
    const id = window.setTimeout(() => setDensityNote(null), 6000);
    return () => window.clearTimeout(id);
  }, [densityNote]);
  // Each stage on show fills one of these with its snapshot (PRD 16.8); the side-by-side view fills both.
  const snapMain = useRef<Snapshotter | null>(null);
  const snapCf = useRef<Snapshotter | null>(null);
  const stageBox = useRef<HTMLElement>(null);
  const [snapping, setSnapping] = useState(false);

  // The loading sequence: three checks tick off as the feed, the space model and the agents come up (PRD 15.11).
  useEffect(() => {
    if (preview === 'loading') return;
    if (loadStage >= 3) return;
    const id = window.setTimeout(() => setLoadStage((s) => s + 1), 350);
    return () => window.clearTimeout(id);
  }, [loadStage, preview]);
  useEffect(() => {
    if (preview === 'loading') setLoadStage(0);
  }, [preview]);

  // A loop counter for the glossary: the moment restarted when time jumps back.
  const prevT = useRef(t);
  const [loop, setLoop] = useState(0);
  useEffect(() => {
    if (t < prevT.current - 0.5) setLoop((l) => l + 1);
    prevT.current = t;
  }, [t]);
  const glossary = useGlossary(step, loop, mode === 'learn');

  // Captions for this viewer, from the feed.
  const active = store.active(t_ms, { mode, whatIf, fav });
  const captions = active.filter((a) => a.overlay.kind === 'caption');
  const current = captions.find((c) => !c.retraction) ?? captions[0];
  const captionText = current ? (current.overlay.text[lang] ?? current.overlay.text.en ?? '') : '';
  const learnText = mode === 'learn' && !whatIf ? fill(captionText, { count: glossary.seen.decoy }) : null;
  const feedLine = useMemo(() => {
    const lines = store.log.filter((l) => l.t_ms <= t_ms);
    return lines[lines.length - 1]?.text ?? 'match.status · in_play';
  }, [store.log, store.version, t_ms]);
  // A changed decision's verdict replaces the caption while its world plays (PRD 15.12).
  const verdict = decisionResult ? decide.verdict : null;
  // Each override says which language it's in: Analyst's verdict is English, the others are in the caption's language.
  const captionLang: Lang = current?.overlay.text[lang] ? lang : 'en';
  const override = verdict
    ? { text: verdict, lang: mode === 'analyst' || mode === 'broadcaster' ? ('en' as Lang) : lang }
    : mode === 'broadcaster' && !whatIf
      ? { text: feedLine, mono: true }
      : learnText
        ? { text: learnText, lang: captionLang }
        : undefined;
  const shownText = override?.text ?? captionText;

  // Voice: the caption spoken in the viewer's language, never over itself and never more than 4 s behind (PRD 10.5).
  const voiceWanted = mode === 'audio' ? narration : prefs.voice;
  const voice = voiceFor(lang);
  const tRef = useRef(t);
  tRef.current = t;
  useEffect(() => {
    if (!voiceWanted || !clock.playing || !current || mode === 'broadcaster') return;
    speaker.say({ id: `${current.overlay.overlay_id}:${lang}`, text: shownText, lang, t: momentT(current.overlay) }, () => tRef.current, mode === 'audio' ? 1.05 : 1);
  }, [current?.overlay.overlay_id, voiceWanted, clock.playing, lang, mode, shownText, current]);
  useEffect(() => {
    if (!voiceWanted || !clock.playing) speaker.cancel();
  }, [voiceWanted, clock.playing]);
  useEffect(() => () => speaker.cancel(), []);

  // Stereo cues where space is opening: the audio-described mode's cue, or sonification in any mode (PRD 10.5, 16.6).
  const cued = useRef(new Set<string>());
  const ring = active.find((a) => a.overlay.kind === 'gap_ring' && !a.overlay.counterfactual_id);
  useEffect(() => {
    if (!ring || !clock.playing) return;
    const key = `${loop}:${ring.overlay.overlay_id}`;
    if (cued.current.has(key)) return;
    const pan = ring.overlay.speech?.[lang]?.pan ?? (prefs.sonify ? ((ring.overlay.anchors.centre_xy?.[0] ?? 52.5) - 52.5) / 52.5 : null);
    if (pan === null || pan === undefined) return;
    cued.current.add(key);
    cue(pan);
  }, [ring, loop, lang, prefs.sonify, clock.playing]);

  // Announcements, rate-limited (PRD 15.4).
  useEffect(() => {
    if (shownText && mode !== 'broadcaster') announce(shownText);
  }, [shownText, mode, announce]);
  useEffect(() => {
    if (clock.stalled) announce(ui.stall);
  }, [clock.stalled, announce, ui.stall]);
  useEffect(() => {
    if (tiers.notice) announce(tiers.notice.text);
  }, [tiers.notice, announce]);

  // Pairing: the code stays live while the match view is open (PRD 15.5).
  const host = useHostCode();
  const guests = usePairHost(host.code, host.expiresAt, { t, playing: clock.playing, mode, lang: prefs.lang, fav });

  const follow = useCallback(
    (id: string) => {
      update({ fav: id, mode: 'player' });
      announce(`Following ${player(id).name}`);
    },
    [update, announce],
  );

  // A snapshot of what the pitch shows now: one picture, or both sides of the what-if, with the export label and a line
  // saying when and what. About 1920 pixels across for PNG; SVG where the view is drawn in 2D.
  const snapshot = async (format: SnapshotFormat) => {
    const main = snapMain.current;
    if (!main || snapping) return;
    setSnapping(true);
    try {
      const kind = main.formats.includes(format) ? format : 'png';
      const width = stageBox.current?.getBoundingClientRect().width ?? 960;
      const scale = Math.min(4, Math.max(2, 1920 / width));
      const second = split ? snapCf.current : null;
      const parts = second
        ? [
            { shot: await main.take(kind, scale), title: ui.real },
            { shot: await second.take(kind, scale), title: decisionScenario ? decisionScenario.world : ui.without },
          ]
        : [{ shot: await main.take(kind, scale) }];
      const shown = store.scoreAt(ms(clockRef.current.now()));
      const clockText = clockLabel(clockRef.current.now());
      const world = decisionResult && decisionScenario && !split ? ` · ${decisionScenario.world}` : whatIf && !split ? ' · without No. 9’s run' : '';
      const caption = `${clockText} · ${pack.modes[mode].label} · ${CLUBS.kes.name} ${shown.kes}–${shown.ash} ${CLUBS.ash.name}${world}`;
      const blob = await composeSnapshot(parts, kind, scale, caption);
      download(blob, `offball-snapshot-${clockText.replace(/[^0-9]+/g, '-')}.${kind}`);
      announce(`Snapshot saved as ${kind.toUpperCase()}.`);
    } catch (err) {
      announce(`The snapshot couldn’t be made: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setSnapping(false);
    }
  };
  const snapshotRef = useRef(snapshot);
  snapshotRef.current = snapshot;
  // The shortcuts read these through refs, so the key handler doesn't re-attach on every render.
  const decideRef = useRef(decide);
  decideRef.current = decide;
  const decideOpenRef = useRef(decide.open);
  decideOpenRef.current = decide.open;
  const openDecisionsRef = useRef(openDecisions);
  openDecisionsRef.current = openDecisions;
  const toggleWhatIfRef = useRef(toggleWhatIf);
  toggleWhatIfRef.current = toggleWhatIf;
  const whatIfRef = useRef(whatIf);
  whatIfRef.current = whatIf;

  // Keyboard shortcuts (PRD 15.4). Ignored while typing, inside a dialog, or when a control already used the key.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      unlockAudio();
      if (e.defaultPrevented || e.altKey || e.ctrlKey || e.metaKey || isTyping(e.target) || document.getElementById('root')?.inert) return;
      const k = e.key;
      const speedIndex = SPEEDS.indexOf(clock.speed);
      const act: Record<string, () => void> = {
        ' ': clock.toggle,
        k: clock.toggle,
        ',': () => clock.step(-1),
        '.': () => clock.step(1),
        j: () => clock.jump(-1),
        l: () => clock.jump(1),
        '[': () => clock.setSpeed(SPEEDS[Math.max(0, speedIndex - 1)]),
        ']': () => clock.setSpeed(SPEEDS[Math.min(SPEEDS.length - 1, speedIndex + 1)]),
        Home: () => clock.scrub(0),
        End: () => clock.scrub(T_END),
        w: () => toggleWhatIfRef.current(!whatIfRef.current),
        d: () => (decideOpenRef.current ? decideRef.current.close() : openDecisionsRef.current()),
        Escape: () => decideOpenRef.current && decideRef.current.close(),
        v: () => {
          const i = VIEW_OPTIONS.findIndex((o) => o.value === prefsRef.current.view);
          update({ view: VIEW_OPTIONS[(i + 1) % VIEW_OPTIONS.length].value });
        },
        a: () => setPanel('ask'),
        p: () => setPanel('personalize'),
        s: () => void snapshotRef.current('png'),
        '?': () => setPanel('shortcuts'),
      };
      const fn = act[k] ?? act[k.toLowerCase()];
      // Escape only closes the decision panel; anything else that uses it (dialogs, the sheet) handles it first.
      if (k === 'Escape' && !decideOpenRef.current) return;
      if (fn && (k !== ' ' || !(e.target instanceof HTMLButtonElement))) {
        e.preventDefault();
        fn();
        return;
      }
      const n = Number(k);
      if (n >= 1 && n <= 6) {
        e.preventDefault();
        update({ mode: MODE_IDS[n - 1] });
      }
    };
    window.addEventListener('keydown', onKey);
    const unlock = () => unlockAudio();
    window.addEventListener('pointerdown', unlock, { once: true });
    return () => {
      window.removeEventListener('keydown', onKey);
      window.removeEventListener('pointerdown', unlock);
    };
  }, [clock, update]);

  const fail3D = useCallback(
    (reason: string) => {
      console.warn(`3D view unavailable: ${reason}`);
      setThreeD({ failed: true, got: null });
      announce('The 3D view isn’t available on this device, so the 2D view is showing.');
    },
    [announce],
  );
  const got3D = useCallback((tier: Tier) => setThreeD((s) => (s.got === tier ? s : { ...s, got: tier })), []);

  // Stable handlers, so the memoised panel below doesn't re-render for them.
  const clockRef = useRef(clock);
  clockRef.current = clock;
  const explain = useCallback(() => {
    clockRef.current.pause();
    setExplaining(true);
  }, []);
  const openPersonalize = useCallback(() => setPanel('personalize'), []);

  const passCorrected = useMemo(() => [...store.overlays.values()].some((o) => o.labels.includes('correction')), [store, store.version]);

  const yours = prefs.club === 'kes' ? `${ui.attacking} · ` : prefs.club === 'ash' ? `${ui.defending} · ` : '';
  const draft = !pack.reviewed && lang !== 'en' ? ` · ${ui.draft}` : '';
  const evidence = current?.overlay.evidence_ids ?? [];
  const meta =
    verdict && decide.option && decide.point
      ? `${fill(pack.decide.meta, { n: RERUNS, clock: clockLabel(decide.point.t) })} · ${counterfactualId(decide.option.id)}`
      : mode === 'broadcaster'
      ? `Overlay feed · partner protocol 2.0 · ${source?.label ?? ''}`
      : mode === 'analyst'
        ? `${yours}Evidence: ${evidence.join(' · ')}${draft}`
        : `${yours}${fill(ui.aiCaption, { n: Math.max(1, evidence.length + 1) })}${draft}`;
  const voiceLabel = !voiceWanted ? ui.voiceOff : !canSpeak() || !voice ? `No device voice for ${LANGS.find((l) => l.code === lang)?.en ?? lang}` : `${ui.voiceOn} · ${voice.name.split(' - ')[0]}`;

  const toasts: ToastItem[] = [];
  if (tiers.notice) toasts.push({ id: `tier-${tiers.notice.id}`, text: tiers.notice.text, tone: 'info' });
  if (threeD.failed && view !== '2d') toasts.push({ id: '3d-unavailable', text: 'The 3D view isn’t available on this device, so the 2D view is showing.', tone: 'info' });
  if (clock.recovered) toasts.push({ id: 'sync', text: clock.missed > 0 ? fill(ui.syncedMissed, { n: clock.missed }) : ui.synced, tone: 'success' });
  if (densityNote) toasts.push(densityNote);

  // The view: 2D tactical, or one of the 3D cameras (PRD 15.1).
  const viewPicker = (
    <label className="pitch-view">
      <span className="sr-only">Pitch view</span>
      <select className="select select-sm" value={view} onChange={(e) => update({ view: e.target.value as View })}>
        {VIEW_OPTIONS.map((o) => (
          <option key={o.value} value={o.value} disabled={o.value !== '2d' && threeD.failed}>
            {o.label}
            {o.value !== '2d' && threeD.failed ? ' (not available here)' : ''}
          </option>
        ))}
      </select>
    </label>
  );
  const chips = (
    <>
      {viewPicker}
      <span className="map-chip">
        <span className="anim-blink" style={{ width: 6, height: 6, borderRadius: 3, background: 'var(--space)' }} />
        Tier {shownTier} · {TIERS[shownTier].name} · <span className="fps-value">{tiers.fps} fps</span>
      </span>
      <span key={`${whatIf}:${decisionResult ? decisionScenario?.id : ''}`} className="map-chip anim-pop">
        {decisionResult && decisionScenario ? fill(pack.decide.field, { world: decisionScenario.world }) : whatIf ? 'Field: without No. 9’s run' : 'Field: live space control'}
      </span>
      {decide.open && decide.phase === 'pick' && <span className="map-chip map-chip-space anim-pop">{pack.decide.pickChip}</span>}
      {/* What the viewer can hide, in the real world only: a what-if or a changed decision shows everything. */}
      {!whatIf && !decide.open && !showVideo && (
        <MenuButton
          label="Overlays"
          className="overlays-menu"
          buttonClassName="map-chip map-chip-btn press"
          align="start"
          icon={
            <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true">
              <path d="M7 1.5 L12.5 4.5 L7 7.5 L1.5 4.5 Z M1.5 7 L7 10 L12.5 7 M1.5 9.5 L7 12.5 L12.5 9.5" style={{ fill: 'none', stroke: 'currentColor', strokeWidth: 1.3, strokeLinejoin: 'round' }} />
            </svg>
          }
          extra={hiddenNow.length > 0 && <span className="map-chip-count">{hiddenNow.length} hidden</span>}
          note={
            <>
              {prefs.adapt ? 'Hide what you don’t need. OffBall remembers it for this mode, on this device.' : 'Hidden until you leave this page. Turn on “Adapt to what I hide or show” in Personalize to keep it.'}
              {fewer && <span className="menu-note-strong"> {PACKS.en.modes[mode].label} shows fewer overlays while two are hidden.</span>}
            </>
          }
          items={[
            ...modeGroups.map((g) => ({ key: g, label: GROUP_LABEL[g], checked: !hiddenNow.includes(g), onSelect: () => toggleGroup(g) })),
            ...(hiddenNow.length ? [{ key: 'all', label: 'Show everything', divided: true, onSelect: showEverything }] : []),
          ]}
        />
      )}
    </>
  );
  const scrim = clock.stalled ? (
    <div className="pitch-scrim anim-fade">
      <span className="map-chip" style={{ fontSize: 14, padding: '10px 16px', borderRadius: 999 }}>
        <Spinner />
        {ui.stall}
      </span>
    </div>
  ) : null;
  const explainCard =
    explaining && mode === 'learn' ? (
      <div className="explain">
        <div className="card explain-card anim-rise" role="dialog" aria-label={ui.pauseExplain}>
          <p className="card-label" style={{ marginBottom: 6 }}>
            {pack.glossary[CONCEPT_AT_STEP[step] ?? 'decoy'].term}
          </p>
          <p style={{ fontSize: 16, lineHeight: 1.5, marginBottom: 12 }}>{pack.glossary[CONCEPT_AT_STEP[step] ?? 'decoy'].def}</p>
          <p className="muted" style={{ fontSize: 14, lineHeight: 1.5, marginBottom: 12 }}>
            {shownText}
          </p>
          <Button
            variant="primary"
            onClick={() => {
              setExplaining(false);
              clock.play();
            }}
          >
            {ui.play}
          </Button>
        </div>
      </div>
    ) : null;

  // While picking whose decision to change, a click or Enter on a player picks them instead of following them.
  const picking = decide.open && decide.phase === 'pick';
  const stageProps = { store, time: clock, mode, density, hide: hiddenNow, theme: prefs.theme, fav, i18n, onFollow: picking ? decide.pick : follow, pickable: decide.pickable, onPlayerClick: picking ? decide.pick : undefined } as const;
  const pitch = (variant: 'real' | 'cf', ghosts: boolean, extra: { chips?: ReactNode; corner?: ReactNode } = {}) => {
    const snap = split && variant === 'cf' ? snapCf : snapMain;
    // The changed decision: its preview on the real pitch while choosing, its world on the other side once it's back.
    const scenario = decisionScenario && (decisionResult ? variant === 'cf' : variant === 'real') ? decisionScenario : null;
    return showVideo ? (
      <StageVideo {...extra} clock={clock} mode={mode} whatIf={whatIf} scrim={scrim} dim={clock.stalled} portrait={screen.phonePortrait} snapshot={snap} />
    ) : show3D ? (
      <Stage3D {...stageProps} {...extra} view={view as Exclude<View, '2d'>} tier={tiers.tier as 'A' | 'B'} variant={variant} ghosts={ghosts} onFail={fail3D} onTier={got3D} scrim={scrim} dim={clock.stalled} portrait={screen.phonePortrait} snapshot={snap} compare={split} scenario={scenario} />
    ) : (
      <Stage2D {...stageProps} {...extra} orientation={orientation} variant={variant} ghosts={ghosts} scrim={scrim} dim={clock.stalled} snapshot={snap} compare={split} scenario={scenario} />
    );
  };
  const otherWorld = whatIf || decisionResult;
  const stage =
    loadStage < 3 ? (
      <LoadingPitch stage={loadStage} orientation={orientation} checks={ui.loading} />
    ) : split && !showVideo ? (
      <div className="split-wrap">
        {viewPicker}
        <div className="split">
          {(['real', 'cf'] as const).map((variant) => (
            <div key={variant} className="pitch-card">
              <p className="split-label">{variant === 'real' ? ui.real : decisionResult && decisionScenario ? capitalise(decisionScenario.world) : ui.without}</p>
              {pitch(variant, false)}
            </div>
          ))}
        </div>
      </div>
    ) : (
      <div className="pitch-card anim-rise">
        {pitch(otherWorld ? 'cf' : 'real', otherWorld, { chips, corner: <ToastStack toasts={toasts} /> })}
        {explainCard}
      </div>
    );

  // The side panel's numbers update four times a second: digits changing faster can't be read, and the pitch keeps
  // the full frame rate (PRD 16.7). Its step follows the exact clock, so a beat never shows early or late.
  const panelT = Math.floor(t * 4) / 4;
  const voiceName = canSpeak() ? (voice?.name ?? null) : null;
  const panelContent = useMemo(() => {
    const pfs = frameState(store, panelT);
    const pStep = step;
    const space = focusStats(fav).space;
    // The number the viewer cares about (PRD 8.2), for Casual's tile.
    const mine: StatItem =
      prefs.metric === 'pass'
        ? { key: 'pass', label: METRIC_LABEL.pass, value: num(passCorrected ? 5.9 : 6.1, 1), unit: 'of 10', ready: panelT >= 4.2 }
        : prefs.metric === 'sprint'
          ? { key: 'sprint', label: `${METRIC_LABEL.sprint} · No. ${player(fav).num}`, value: num(pfs.speedOf(fav), 1), unit: 'km/h' }
          : { key: 'space', label: `${METRIC_LABEL.space} · No. ${player(fav).num}`, value: String(space[panelT >= space[2] && space[2] > 0 ? 1 : 0]), unit: 'm²' };
    // The followed player's speed through the move, every quarter second, for the sparkline.
    const speeds: number[] = [];
    if (mode === 'player') for (let tt = 0; tt <= panelT + 0.001; tt += 0.25) speeds.push(frameState(store, tt, { fields: false }).speedOf(fav));
    // The audio-described transcript: every spoken line of the moment, in the viewer's language.
    const audioLines = store
      .forMode('audio')
      .filter((o) => o.kind === 'caption' && !o.counterfactual_id && !store.retractions.has(o.overlay_id))
      .map((o) => ({ t: momentT(o), text: o.text[lang] ?? o.text.en ?? '' }));
    const pan = ((pStep >= 3 ? GAP_CENTRE[0] : (pfs.pos['kes-09']?.[0] ?? 52.5)) - 52.5) / 52.5;
    return (
      <ErrorBoundary label="The side panel">
        <div key={mode} className="stack">
          {mode === 'casual' && <CasualPanel step={pStep} mine={mine} />}
          {mode === 'learn' && <LearnPanel step={pStep} seen={glossary.seen} fresh={glossary.fresh} onExplain={explain} />}
          {mode === 'analyst' && <AnalystPanel fs={pfs} metric={prefs.metric} store={store} passCorrected={passCorrected} />}
          {mode === 'player' && <PlayerPanel fav={fav} fs={pfs} speeds={speeds} metric={prefs.metric} onChange={openPersonalize} />}
          {mode === 'audio' && <AudioPanel lines={audioLines} t={panelT} playing={clock.playing} pan={pan} narration={narration} onNarration={setNarration} voiceName={voiceName} onTestCue={() => (unlockAudio(), cue(pan))} />}
          {mode === 'broadcaster' && <BroadcasterPanel store={store} t={panelT} />}
        </div>
      </ErrorBoundary>
    );
  }, [store, store.version, panelT, step, mode, fav, prefs.metric, passCorrected, lang, num, glossary.seen, glossary.fresh, explain, openPersonalize, clock.playing, narration, voiceName]);

  // Static chart: built once per language.
  const momentumCard = useMemo(
    () => (
      <div className="card" style={{ padding: '12px 16px' }}>
        <ChartFrame
          title="Momentum · space value per minute"
          name="momentum"
          summary={`Kestrel Bay above the line, Ashmoor below. Kestrel have had the better of it since the 55th minute; big chances at 12′, 27′ (Ashmoor), 41′ and 63′.`}
          columns={['Minute', 'Space value (positive is Kestrel Bay)']}
          rows={MOMENTUM.filter((d) => d.minute % 5 === 0 || d.minute === 63).map((d) => [d.minute, d.value])}
        >
          <MomentumRibbon minute={63} label="Momentum ribbon: space value per minute, Kestrel Bay above the line and Ashmoor below." />
        </ChartFrame>
      </div>
    ),
    [],
  );

  // The caption only re-renders when its lines, corrections or status change.
  const captionKey = captions.map((c) => `${c.overlay.overlay_id}:${c.overlay.rev}:${c.retraction ? 1 : 0}`).join('|');
  const captionBar = useMemo(
    () => <CaptionBar className={screen.phoneLandscape ? 'caption-overlay' : undefined} captions={captions} override={override} meta={meta} size={mode === 'audio' ? prefs.capSize + 2 : prefs.capSize} voice={{ on: voiceWanted, speaking: clock.playing, label: voiceLabel }} />,
    // Keyed on the caption's content, not the arrays rebuilt every frame.
    [captionKey, override?.text, override?.mono, override?.lang, meta, mode, prefs.capSize, voiceWanted, clock.playing, voiceLabel, screen.phoneLandscape],
  );

  const screenKind = screen.phonePortrait ? 'portrait' : screen.phoneLandscape ? 'landscape' : screen.tablet ? 'tablet' : 'desktop';
  const modeLabel = pack.modes[mode].label;
  // Change one decision takes the side panel's place while it's open (PRD 15.12).
  const panelTitle = decide.open ? pack.decide.title : modeLabel;
  const sidePanel = loadStage < 3 ? (
    <PanelSkeleton />
  ) : decide.open ? (
    <ErrorBoundary label="Change one decision">
      <DecisionPanel d={decide} mode={mode} canSplit={!screen.phonePortrait && !showVideo} titled={!screen.phonePortrait && !screen.phoneLandscape} />
    </ErrorBoundary>
  ) : (
    panelContent
  );

  // The header changes once a second at most (the clock), or when a setting changes.
  const score = store.scoreAt(t_ms);
  const clockText = clockLabel(t);
  const isLive = !!source?.live;
  const header = useMemo(
    () => (
      <header className="match-header anim-rise">
        <Logo size={screen.phonePortrait ? 22 : 28} />
        <Scoreboard score={score} clock={clockText} yours={prefs.club} liveLabel={isLive ? 'LIVE' : 'REPLAY'} compact={screen.phonePortrait} />
        <div className="match-header-tools">
          <label htmlFor="mv-lang" className="sr-only">
            {ui.language}
          </label>
          <select id="mv-lang" className="select" style={{ width: 'auto' }} value={prefs.lang} onChange={(e) => update({ lang: e.target.value as Lang })} aria-label={ui.language}>
            {LANGS.map((l) => (
              <option key={l.code} value={l.code} lang={l.code}>
                {l.native}
              </option>
            ))}
          </select>
          {prefs.lang !== 'en' && (
            <Button variant="ghost" className="btn-sm wide-only" onClick={() => update({ lang: 'en' })} lang="en">
              English
            </Button>
          )}
          <Switch checked={whatIf} onChange={(on) => toggleWhatIfRef.current(on)} label={ui.whatIf} />
          {whatIf && !screen.phonePortrait && (
            <Segmented
              options={[
                { value: 'overlay', label: 'Overlay' },
                { value: 'split', label: 'Side by side' },
              ]}
              value={prefs.cfView}
              onChange={(cfView) => update({ cfView })}
              label="What-if view"
            />
          )}
          <Button onClick={() => setPanel('ask')}>{ui.ask}</Button>
          {/* What isn't used every minute waits one click away, on every screen size (PRD 15.1). */}
          <MenuButton
            label={ui.more}
            items={[
              { key: 'pair', label: ui.pair, onSelect: () => setPanel('pair') },
              { key: 'keys', label: `${ui.shortcuts} (?)`, onSelect: () => setPanel('shortcuts') },
              // On a phone the one-tap way back to English waits here, so the header keeps to three rows.
              ...(screen.phonePortrait && prefs.lang !== 'en' ? [{ key: 'en', label: <span lang="en">English</span>, onSelect: () => update({ lang: 'en' }) }] : []),
            ]}
          />
          <Button icon aria-label={ui.personalize} onClick={openPersonalize}>
            <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true">
              <path d="M3 5 H15 M3 9 H15 M3 13 H15" style={{ fill: 'none', stroke: 'currentColor', strokeWidth: 1.6, strokeLinecap: 'round' }} />
              <circle cx="6" cy="5" r="2" style={{ fill: 'var(--surface)', stroke: 'currentColor', strokeWidth: 1.6 }} />
              <circle cx="12" cy="9" r="2" style={{ fill: 'var(--surface)', stroke: 'currentColor', strokeWidth: 1.6 }} />
              <circle cx="8" cy="13" r="2" style={{ fill: 'var(--surface)', stroke: 'currentColor', strokeWidth: 1.6 }} />
            </svg>
          </Button>
        </div>
      </header>
    ),
    // The score object is rebuilt every frame; its two numbers are what matter. The what-if switch's handler reads
    // through a ref, so a new one each render doesn't rebuild the header.
    [score.kes, score.ash, clockText, isLive, prefs.club, prefs.lang, prefs.cfView, screen.phonePortrait, whatIf, ui, update, openPersonalize],
  );

  return (
    <div className={`screen match ${screen.phonePortrait ? 'has-sheet' : ''}`} data-screen={screenKind}>
      <div className="container">
        <h1 className="sr-only">
          {CLUBS.kes.name} v {CLUBS.ash.name}: match view
        </h1>
        {header}

        {(!online || preview === 'offline') && (
          <div className="card cluster" role="status" style={{ marginBottom: 12, gap: 10, padding: '10px 14px', borderColor: 'var(--ash)' }}>
            <Chip tone="danger">Offline</Chip>
            <span style={{ fontSize: 14 }}>{ui.offline}</span>
          </div>
        )}

        <nav className="match-modes anim-rise" aria-label={ui.viewingMode}>
          <ModeSwitcher value={mode} onChange={(m) => update({ mode: m })} />
        </nav>

        {screen.phoneLandscape && (
          <div className="landscape-tools">
            <Button variant="solid" onClick={clock.toggle}>
              {clock.playing ? ui.pause : ui.play}
            </Button>
            <Button onClick={() => setPanel('panel')}>{modeLabel}</Button>
            <Button icon aria-label={ui.personalize} onClick={() => setPanel('personalize')}>
              ☰
            </Button>
          </div>
        )}

        <main className="match-main">
          <section ref={stageBox} aria-label="Match" className="match-stage">
            <ErrorBoundary label="The pitch">{stage}</ErrorBoundary>

            {loadStage < 3 ? <CaptionSkeleton /> : captionBar}

            <div className="card" style={{ padding: '12px 16px' }}>
              <ReplayBar
                clock={clock}
                tools={
                  <span className="snapshot-tools">
                    <Button className="btn-sm" onClick={() => void snapshot('png')} disabled={snapping || loadStage < 3} aria-label="Snapshot: save the pitch as a PNG image" title="Save the pitch as a PNG image (S)">
                      <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
                        <path d="M2 5 H4.5 L6 3 H10 L11.5 5 H14 V13 H2 Z" style={{ fill: 'none', stroke: 'currentColor', strokeWidth: 1.5, strokeLinejoin: 'round' }} />
                        <circle cx="8" cy="8.8" r="2.4" style={{ fill: 'none', stroke: 'currentColor', strokeWidth: 1.5 }} />
                      </svg>
                      Snapshot
                    </Button>
                    {!showVideo && !show3D && (
                      <Button variant="ghost" className="btn-sm" onClick={() => void snapshot('svg')} disabled={snapping || loadStage < 3} aria-label="SVG: save the pitch with its shapes and words as vectors" title="Save the pitch as SVG, with shapes and words as vectors">
                        SVG
                      </Button>
                    )}
                    <Button className={decide.open ? 'btn-sm decide-on' : 'btn-sm'} aria-expanded={decide.open} onClick={() => (decide.open ? decide.close() : openDecisions())} disabled={loadStage < 3} title="Change one player’s decision and re-run the moment (D)">
                      <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
                        <path d="M3 14 V9 C3 6.5 5 5 8 5 H12 M10 2.5 L12.5 5 L10 7.5 M3 9 C3 11 5 12.5 8 12.5 H9.5" style={{ fill: 'none', stroke: 'currentColor', strokeWidth: 1.5, strokeLinecap: 'round', strokeLinejoin: 'round', strokeDasharray: 'none' }} />
                      </svg>
                      {decide.open ? pack.decide.close : pack.decide.open}
                    </Button>
                  </span>
                }
              />
            </div>

            {momentumCard}

            {/* Tools for demonstrating the system states (PRD 15.11), tucked away from viewers. */}
            <details className="demo-tools" open={simStall || simSlow || undefined}>
              <summary className="demo-tools-summary">Demo controls</summary>
              <div className="cluster" style={{ fontSize: 13, marginTop: 10 }}>
                <span className="muted">Simulate:</span>
                <Switch checked={simStall} onChange={setSimStall} label="Feed stall" />
                <Switch checked={simSlow} onChange={setSimSlow} label="Slow device" />
                <span className="muted" style={{ fontSize: 12 }}>
                  {source?.label} · {tiers.p95} ms p95
                </span>
              </div>
            </details>
            <p className="muted" style={{ fontSize: 12 }}>
              {ui.synthetic}
            </p>
          </section>

          {screen.phonePortrait ? (
            <BottomSheet title={panelTitle} open={sheetOpen} onToggle={setSheetOpen}>
              {sidePanel}
            </BottomSheet>
          ) : screen.phoneLandscape ? null : (
            <aside aria-label={`${panelTitle} panel`} className="match-panel" data-collapsed={screen.tablet && panelCollapsed}>
              <Button className="panel-toggle" variant="ghost" aria-expanded={!panelCollapsed} onClick={() => setPanelCollapsed((c) => !c)}>
                {panelCollapsed ? `Show ${panelTitle} panel` : `Hide ${panelTitle} panel`}
              </Button>
              {sidePanel}
            </aside>
          )}
        </main>
      </div>

      <PersonalizeDrawer open={panel === 'personalize'} onClose={() => setPanel('none')} />
      <Drawer open={panel === 'ask'} onClose={() => setPanel('none')} title={ui.ask}>
        <AskPanel t={t} />
      </Drawer>
      <Drawer open={panel === 'panel'} onClose={() => setPanel('none')} title={panelTitle}>
        {sidePanel}
      </Drawer>
      <PairDialog open={panel === 'pair'} onClose={() => setPanel('none')} code={host.code} expiresAt={host.expiresAt} guests={guests} onRenew={host.renew} />
      <ShortcutsDialog open={panel === 'shortcuts'} onClose={() => setPanel('none')} />
      <LiveRegion msg={msg} />
    </div>
  );
}
