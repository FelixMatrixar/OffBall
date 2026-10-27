import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore, type CSSProperties } from 'react';
import { AskPanel } from '../components/ask/AskPanel';
import { CaptionBar, LiveRegion, LoadingPitch, ModeSwitcher, PersonalizeDrawer, Scoreboard, ShortcutsDialog, useAnnouncer } from '../components/match';
import { DENSITY_WEIGHT, FIELD_WEIGHT } from '../components/match/Stage2D';
import { MatchScrubber } from '../components/player/MatchScrubber';
import { MomentList } from '../components/player/MomentList';
import { MomentPanel } from '../components/player/MomentPanel';
import { PlayBoard } from '../components/player/PlayBoard';
import { OUTCOME_LABEL, PlayItOutPanel } from '../components/player/PlayItOutPanel';
import { PlayerPitch, type PitchWord } from '../components/player/PlayerPitch';
import { usePlayItOut } from '../components/player/usePlayItOut';
import { BottomSheet, Button, Chip, Drawer, Logo, MenuButton, Segmented, Spinner } from '../components/ui';
import { canSpeak, speaker, unlockAudio, voiceFor } from '../lib/audio';
import { contrast, parseColor, readToken } from '../lib/color';
import type { ActiveOverlay } from '../lib/feed';
import type { Answer } from '../lib/pundit';
import type { Overlay } from '../lib/feed/types';
import { useScreenClass } from '../lib/hooks';
import { LANGS, fill, isRtl, useDocumentLocale, useI18n } from '../lib/i18n';
import { LEAGUE, checkFixture, displayColour, type FixtureCheck } from '../lib/kits';
import type { Team } from '../lib/match';
import { fetchGraphics, fetchMatches, fetchTimeline, playerHref, type Graphics, type MatchSummary, type Moment, type Timeline, type WhatIf } from '../lib/player/api';
import { SPEEDS, clockOf, matchTime, useMatchClock, type Speed } from '../lib/player/clock';
import { MatchFrames } from '../lib/player/frames';
import { GHOST_AFTER_MS, GHOST_BEFORE_MS } from '../lib/player/whatif';
import { playerWords } from '../lib/player/words';
import { MODE_IDS, usePrefs, type Lang } from '../lib/prefs';

/** A jump to a moment starts this long before it, so the viewer sees the play build. */
const LEAD_IN_MS = 3000;
/** A match counts as whole when it runs past an hour. */
const WHOLE_MS = 60 * 60_000;

type Panel = 'none' | 'personalize' | 'ask' | 'shortcuts';

const isTyping = (el: EventTarget | null) => el instanceof HTMLElement && (el.isContentEditable || ['INPUT', 'SELECT', 'TEXTAREA'].includes(el.tagName));

/** `at=2:1080000` in the address: the second half, 18 minutes in. */
function startFrom(): { period: number; t_ms: number } | null {
  const raw = new URLSearchParams(window.location.hash.split('?')[1] ?? '').get('at') ?? '';
  const [p, t] = raw.split(':').map(Number);
  return raw && Number.isFinite(p) && Number.isFinite(t) ? { period: p, t_ms: t } : null;
}

/** The fixture's colours, checked for colour vision against this theme's pitch (PRD 16.3). */
function fixtureColours(tl: Timeline): FixtureCheck & { onHome: string; onAway: string } {
  const pitch = readToken('--pitch') || readToken('--bg');
  const known = LEAGUE[tl.home.club_id] && LEAGUE[tl.away.club_id];
  const check: FixtureCheck = known
    ? checkFixture(tl.home.club_id, tl.away.club_id, pitch)
    : {
        home: { colour: displayColour(tl.home.kit?.primary ?? readToken('--kes'), pitch), pattern: 'plain' },
        away: { colour: displayColour(tl.away.kit?.primary ?? readToken('--ash'), pitch), pattern: 'hoops', kit: 'primary' },
        decision: 'pattern added',
        minDelta: 0,
        worst: 'typical',
      };
  const bg = readToken('--bg');
  const text = readToken('--text');
  const ink = (c: string) => (contrast(parseColor(c), parseColor(bg)) >= contrast(parseColor(c), parseColor(text)) ? bg : text);
  return { ...check, onHome: ink(check.home.colour), onAway: ink(check.away.colour) };
}

const rgbOf = (c: string) => parseColor(c).map(Math.round).join(' ');

interface WholeMatchProps {
  tl: Timeline;
  graphics: Graphics;
  matches: readonly MatchSummary[];
  start: { period: number; t_ms: number } | null;
}

function WholeMatch({ tl, graphics, matches, start }: WholeMatchProps) {
  const { prefs, update, reducedMotion } = usePrefs();
  const { lang, ui, pack } = useI18n();
  const w = playerWords(lang);
  const screen = useScreenClass();
  const orientation = screen.phonePortrait ? 'v' : 'h';
  const mode = prefs.mode;
  const { msg, announce } = useAnnouncer();
  const [panel, setPanel] = useState<Panel>('none');
  const [sheetOpen, setSheetOpen] = useState(false);

  const mt = useMemo(() => matchTime(tl.periods), [tl]);
  const frames = useMemo(() => new MatchFrames(tl.match_id, Object.fromEntries(tl.periods.map((p) => [p.period, p.duration_ms]))), [tl]);
  useSyncExternalStore(frames.subscribe, frames.getVersion);
  const clock = useMatchClock(
    mt.total,
    start ? mt.toMatch(start) : 0,
    (g) => {
      const p = mt.toPosition(g);
      return frames.has(p.period, p.t_ms);
    },
    (g) => {
      const p = mt.toPosition(g);
      frames.ensure(p.period, p.t_ms);
    },
    // It plays as soon as it opens, as the showcase does; reduced motion waits for the viewer.
    !reducedMotion,
  );
  const pos = mt.toPosition(clock.g);

  const roster = useMemo(() => new Map(tl.players.map((p) => [p.player_id, p])), [tl]);
  const clubOfId = useCallback((id: string) => roster.get(id)?.club_id ?? id.split('-')[0], [roster]);
  const sideOf = useCallback((id: string): Team => (clubOfId(id) === tl.home.club_id ? 'kes' : 'ash'), [clubOfId, tl]);
  const numOf = useCallback((id: string) => roster.get(id)?.number ?? (Number(id.split('-')[1]) || 0), [roster]);
  const label = useCallback(
    (id: string) => {
      const p = roster.get(id);
      return p ? fill(w.player, { n: p.number, name: p.name }) : id;
    },
    [roster, w],
  );
  const clubName = useCallback((id: string) => (clubOfId(id) === tl.home.club_id ? tl.home.name : tl.away.name), [clubOfId, tl]);

  // The fixture's kit colours stand in for the showcase's two clubs, so every graphic takes them (PRD 16.3).
  const colours = useMemo(() => fixtureColours(tl), [tl, prefs.theme]); // eslint-disable-line react-hooks/exhaustive-deps
  const vars = {
    '--kes': colours.home.colour,
    '--ash': colours.away.colour,
    '--kes-rgb': rgbOf(colours.home.colour),
    '--ash-rgb': rgbOf(colours.away.colour),
    '--on-kes': colours.onHome,
    '--on-ash': colours.onAway,
  } as CSSProperties;

  const [overlays, setOverlays] = useState<Overlay[]>(graphics.overlays);
  const [moments, setMoments] = useState<Moment[]>(() =>
    tl.moments.map((m) => {
      const built = graphics.moments[m.candidate_id];
      return built ? { ...m, graphics: built.status, graphics_note: built.note } : m;
    }),
  );
  const [selected, setSelected] = useState<string | null>(null);
  const [whatIf, setWhatIf] = useState<WhatIf | null>(null);
  // Play it out: the viewer takes over the moment on screen, sets it up, and the match engine plays their plan.
  const game = usePlayItOut({ matchId: tl.match_id, clubOf: clubOfId });
  const gameRef = useRef(game);
  gameRef.current = game;

  // An answer from Ask OffBall being shown on the pitch, and whether its play has reached its end.
  const [answer, setAnswer] = useState<Answer | null>(null);
  const answerPaused = useRef<Answer | null>(null);

  // The crew's graphics for this viewer's mode, and what is on now.
  const mine = useMemo(() => overlays.filter((o) => o.mode === mode && !o.counterfactual_id && (o.approval === 'auto' || o.approval === 'approved')), [overlays, mode]);
  const onAir = mine.filter((o) => o.period === pos.period && o.t_start_ms <= pos.t_ms && pos.t_ms < o.t_end_ms);
  const captions: ActiveOverlay[] = onAir.filter((o) => o.kind === 'caption').map((overlay) => ({ overlay }));
  const current = captions[0];
  const stat = onAir.find((o) => o.kind === 'stat_card');
  const ringWords: PitchWord[] = [];
  const words: PitchWord[] = [
    ...onAir
      .filter((o) => o.kind === 'gap_ring' && o.anchors.centre_xy && (o.text[lang] ?? o.text.en))
      .map((o) => {
        const [x, y] = o.anchors.centre_xy!;
        const ry = Number((o.data as { ry_m?: number } | null)?.ry_m ?? 6);
        return { id: o.overlay_id, text: o.text[lang] ?? o.text.en ?? '', at: [x, Math.min(67, y + ry + 1.5)] as [number, number], tone: 'space' as const };
      })
      // Two rings saying the same thing in the same place (two moments' graphics overlapping) read as one.
      .filter((wd) => {
        const twin = ringWords.some((o) => o.text === wd.text && Math.hypot(o.at![0] - wd.at[0], o.at![1] - wd.at[1]) < 8);
        if (!twin) ringWords.push(wd);
        return !twin;
      }),
    ...onAir.filter((o) => o.kind === 'player_tag' && o.anchors.player_id).map((o) => ({ id: o.overlay_id, text: o.text[lang] ?? o.text.en ?? '', player_id: o.anchors.player_id! })),
  ];

  const live = useMemo(() => {
    let found: Moment | null = null;
    for (const m of moments) if (m.period === pos.period && m.t_start_ms <= pos.t_ms && pos.t_ms <= m.t_end_ms + 1500) found = m;
    return found;
  }, [moments, pos.period, pos.t_ms]);
  const chosen = moments.find((m) => m.candidate_id === selected) ?? null;
  const highlight = clock.playing ? (live?.candidate_id ?? selected) : (selected ?? live?.candidate_id ?? null);

  const gOf = useCallback((m: Moment) => mt.toMatch({ period: m.period, t_ms: m.t_start_ms }), [mt]);
  const jump = useCallback(
    (m: Moment, play = true) => {
      clock.seek(Math.max(0, gOf(m) - LEAD_IN_MS), play);
      window.history.replaceState(null, '', playerHref('match', { m: tl.match_id, at: `${m.period}:${Math.max(0, m.t_start_ms - LEAD_IN_MS)}` }));
    },
    [clock, gOf, tl.match_id],
  );
  const pick = useCallback(
    (m: Moment) => {
      if (m.candidate_id !== selected) setWhatIf(null);
      setSelected(m.candidate_id);
      jump(m);
      if (screen.phonePortrait) setSheetOpen(true);
      announce(`${w.types[m.type] ?? m.type}, ${clockOf({ period: m.period, t_ms: m.t_start_ms })}`);
    },
    [jump, selected, screen.phonePortrait, announce, w],
  );
  const step = useCallback(
    (dir: 1 | -1) => {
      const g = clock.now();
      const next = dir > 0 ? moments.find((m) => gOf(m) - LEAD_IN_MS > g + 500) : [...moments].reverse().find((m) => gOf(m) - LEAD_IN_MS < g - 1500);
      if (next) pick(next);
    },
    [clock, moments, gOf, pick],
  );

  // Ask OffBall's answer, played on the pitch: from just before the play, at normal speed, with its players ringed.
  const showAnswer = useCallback(
    (a: Answer) => {
      if (!a.show) return;
      setPanel('none');
      setAnswer(a);
      answerPaused.current = null;
      if (a.show.moment_id && moments.some((m) => m.candidate_id === a.show!.moment_id)) {
        if (a.show.moment_id !== selected) setWhatIf(null);
        setSelected(a.show.moment_id);
      }
      clock.setSpeed(1);
      clock.seek(Math.max(0, mt.toMatch({ period: a.show.period, t_ms: a.show.from_ms }) - 1000), true);
      announce(a.claims.map((c) => c.text).join(' '));
    },
    [clock, moments, mt, selected, announce],
  );
  const answerFrom = answer?.show ? mt.toMatch({ period: answer.show.period, t_ms: answer.show.from_ms }) : 0;
  const answerTo = answer?.show ? mt.toMatch({ period: answer.show.period, t_ms: answer.show.to_ms }) : 0;
  // The answer holds the pitch and the caption from just before its play until a while after it.
  const answering = !!answer?.show && clock.g >= answerFrom - 4000 && clock.g <= answerTo + 8000;
  // At the end of its play the clock pauses once, so the viewer can take the answer in.
  useEffect(() => {
    if (!answer?.show || answerPaused.current === answer || !clock.playing) return;
    if (clock.g >= answerTo && clock.g < answerTo + 2000) {
      answerPaused.current = answer;
      clock.pause();
    }
  }, [answer, answerTo, clock]);

  // Voice: the caption spoken in the viewer's language, never over itself and never far behind (PRD 10.5).
  const voiceWanted = mode === 'audio' || prefs.voice;
  const voice = voiceFor(lang);
  const answerLang: Lang = lang === 'es' || lang === 'fr' ? lang : 'en';
  const answerText = answering && answer ? answer.claims.map((c) => c.text).join(' ') : '';
  const captionText = answerText || (current ? (current.overlay.text[lang] ?? current.overlay.text.en ?? '') : '');
  useEffect(() => {
    if (!voiceWanted || !clock.playing || !current) return;
    speaker.say({ id: `${current.overlay.overlay_id}:${lang}`, text: captionText, lang, t: clock.now() / 1000 }, () => clock.now() / 1000, mode === 'audio' ? 1.05 : 1);
  }, [current?.overlay.overlay_id, voiceWanted, clock.playing, lang, mode, captionText]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!voiceWanted || !clock.playing) speaker.cancel();
  }, [voiceWanted, clock.playing]);
  useEffect(() => () => speaker.cancel(), []);
  useEffect(() => {
    if (captionText) announce(captionText);
  }, [captionText, announce]);

  // Keyboard shortcuts (PRD 15.4), as on the showcase where they mean the same.
  const clockRef = useRef(clock);
  clockRef.current = clock;
  const stepRef = useRef(step);
  stepRef.current = step;
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      unlockAudio();
      if (e.defaultPrevented || e.altKey || e.ctrlKey || e.metaKey || isTyping(e.target) || document.getElementById('root')?.inert) return;
      const c = clockRef.current;
      const k = e.key;
      // The board has its own controls; Escape leaves it.
      if (gameRef.current.active) {
        if (k === 'Escape') gameRef.current.exit();
        return;
      }
      const i = SPEEDS.indexOf(c.speed);
      const act: Record<string, () => void> = {
        ' ': c.toggle,
        k: c.toggle,
        j: () => stepRef.current(-1),
        l: () => stepRef.current(1),
        ArrowLeft: () => c.seek(c.now() - 10_000),
        ArrowRight: () => c.seek(c.now() + 10_000),
        '[': () => c.setSpeed(SPEEDS[Math.max(0, i - 1)]),
        ']': () => c.setSpeed(SPEEDS[Math.min(SPEEDS.length - 1, i + 1)]),
        Home: () => c.seek(0),
        End: () => c.seek(mt.total),
        a: () => setPanel('ask'),
        p: () => setPanel('personalize'),
        '?': () => setPanel('shortcuts'),
      };
      const fn = act[k] ?? act[k.toLowerCase()];
      const inControl = (e.target as HTMLElement | null)?.closest?.('[role="slider"], [role="radiogroup"]');
      if (fn && !(inControl && k.startsWith('Arrow')) && (k !== ' ' || !(e.target instanceof HTMLButtonElement))) {
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
    return () => window.removeEventListener('keydown', onKey);
  }, [mt.total, update]);

  const score = { kes: 0, ash: 0 };
  for (const goal of tl.goals) if (mt.toMatch(goal) <= clock.g) score[goal.club_id === tl.home.club_id ? 'kes' : 'ash']++;
  const failed = frames.error(pos.period, pos.t_ms);
  const strength = Math.min(1, FIELD_WEIGHT[mode] * DENSITY_WEIGHT[prefs.density]);
  const levels = mode === 'analyst' || prefs.density === 'rich' ? [0.25, 0.5, 0.75] : [0.5];
  const clockText = clockOf(pos);
  const captionMoment = current ? moments.find((m) => m.candidate_id === current.overlay.detected_moment_id) : null;
  const evidence = current?.overlay.evidence_ids ?? [];
  const meta = answering && answer
    ? `Ask OffBall · “${answer.question}” · ${answer.state === 'ok' ? 'fact-checked' : 'partly fact-checked'}`
    : current
    ? mode === 'analyst'
      ? `${w.types[captionMoment?.type ?? ''] ?? ''} · Evidence: ${evidence.join(' · ')}`
      : `${w.types[captionMoment?.type ?? ''] ?? ''} · ${fill(ui.aiCaption, { n: Math.max(1, evidence.length + 1) })}`
    : live
      ? `${w.types[live.type] ?? live.type} · ${w.graphics[live.graphics]}`
      : `${w.half[pos.period] ?? ''} · ${tl.home.name} v ${tl.away.name}`;
  const voiceLabel = !voiceWanted ? ui.voiceOff : !canSpeak() || !voice ? `No device voice for ${LANGS.find((l) => l.code === lang)?.en ?? lang}` : `${ui.voiceOn} · ${voice.name.split(' - ')[0]}`;
  const showingWhatIf = !!whatIf && whatIf.period === pos.period && pos.t_ms >= whatIf.t_start_ms - GHOST_BEFORE_MS && pos.t_ms <= whatIf.t_measure_ms + GHOST_AFTER_MS;
  const whole = matches.filter((m) => m.tracking && m.duration_ms >= WHOLE_MS);
  const modeLabel = pack.modes[mode].label;

  const chips = (
    <>
      {answering && answer && (
        <span className="map-chip map-chip-space anim-pop">
          Ask OffBall: {answer.question}
          <button type="button" className="chip-x press" aria-label="Back to Ask OffBall" title="Back to Ask OffBall" onClick={() => setPanel('ask')}>
            ↩
          </button>
          <button type="button" className="chip-x press" aria-label="Stop showing the answer" title="Stop showing the answer" onClick={() => setAnswer(null)}>
            ×
          </button>
        </span>
      )}
      <span className="map-chip">
        <span className="anim-blink" style={{ width: 6, height: 6, borderRadius: 3, background: 'var(--space)' }} />
        {w.half[pos.period]} · {clockText}
      </span>
      <span key={String(showingWhatIf)} className="map-chip anim-pop">
        {showingWhatIf ? `${w.whatIf}: ${chosen ? label(chosen.creator_id) : ''} ${whatIf ? w.alternative[whatIf.option_id] : ''}` : 'Field: live space control'}
      </span>
      {stat && <span className="map-chip map-chip-space anim-pop">{stat.text[lang] ?? stat.text.en}</span>}
    </>
  );
  const scrim = failed ? (
    <div className="pitch-scrim anim-fade">
      <span className="map-chip" style={{ fontSize: 14, padding: '10px 16px', borderRadius: 999 }}>
        {w.framesFailed}
      </span>
      <Button variant="secondary" className="btn-sm" onClick={() => frames.retry(pos.period, pos.t_ms)}>
        {w.retry}
      </Button>
    </div>
  ) : clock.waiting ? (
    <div className="pitch-scrim anim-fade">
      <span className="map-chip" style={{ fontSize: 14, padding: '10px 16px', borderRadius: 999 }}>
        <Spinner />
        {w.buffering}
      </span>
    </div>
  ) : null;

  const sidePanel = game.active ? (
    <div className="stack" style={{ gap: 14 }}>
      <PlayItOutPanel game={game} home={tl.home} away={tl.away} label={label} onExit={game.exit} />
    </div>
  ) : (
    <div className="stack" style={{ gap: 14 }} dir={isRtl(lang) ? 'rtl' : 'ltr'}>
      {chosen ? (
        <MomentPanel
          key={chosen.candidate_id}
          matchId={tl.match_id}
          moment={chosen}
          alternatives={tl.alternatives}
          label={label}
          clubOf={clubName}
          w={w}
          lang={lang}
          mode={mode}
          shown={whatIf && whatIf.candidate_id === chosen.candidate_id ? whatIf : null}
          onJump={() => jump(chosen)}
          onExplained={(status, added, note) => {
            setOverlays((all) => [...all.filter((o) => o.detected_moment_id !== chosen.candidate_id), ...added]);
            setMoments((all) => all.map((m) => (m.candidate_id === chosen.candidate_id ? { ...m, graphics: status, graphics_note: note } : m)));
          }}
          onShow={setWhatIf}
        />
      ) : (
        <p className="card muted" style={{ margin: 0, lineHeight: 1.5 }}>
          {w.pick}
        </p>
      )}
      <MomentList moments={moments} home={tl.home} away={tl.away} current={highlight} label={(id) => `${clubName(id)} · ${label(id)}`} w={w} onPick={pick} />
    </div>
  );
  const playHere = () => {
    clock.pause();
    setAnswer(null);
    game.start(pos.period, Math.round(pos.t_ms));
    if (screen.phonePortrait) setSheetOpen(true);
  };
  const shownRun = game.result && game.playback ? game.result.out.runs[game.run] : null;
  const gameText = game.active
    ? game.result && shownRun && (game.decided || !game.playback)
      ? `${OUTCOME_LABEL[shownRun.outcome]} Run ${game.run + 1} of ${game.result.out.summary.runs}: ${game.result.out.summary.shots} ${game.result.out.summary.shots === 1 ? 'shot' : 'shots'} and ${game.result.out.summary.goals} ${game.result.out.summary.goals === 1 ? 'goal' : 'goals'} in all.`
      : game.coach.plan
        ? `${game.coach.plan.headline}. ${game.coach.plan.explanation}`
        : 'Set the scene: drag players, tap one of yours and give him an order, or ask the Coach for a plan. Then play it out.'
    : '';
  const panelTitle = game.active ? 'Play it out' : chosen ? (w.types[chosen.type] ?? chosen.type) : fill(w.moments, { n: moments.length });
  const screenKind = screen.phonePortrait ? 'portrait' : screen.phoneLandscape ? 'landscape' : screen.tablet ? 'tablet' : 'desktop';
  const clubs = { kes: { name: tl.home.name, short: tl.home.short }, ash: { name: tl.away.name, short: tl.away.short } };

  return (
    <div className={`screen match whole-match ${screen.phonePortrait ? 'has-sheet' : ''}`} data-screen={screenKind} style={vars}>
      <div className="container">
        <h1 className="sr-only">
          {tl.home.name} v {tl.away.name}: match view
        </h1>
        <header className="match-header anim-rise">
          <Logo size={screen.phonePortrait ? 22 : 28} />
          <Scoreboard score={score} clock={clockText} yours={prefs.club} liveLabel="REPLAY" compact={screen.phonePortrait} clubs={clubs} />
          <div className="match-header-tools">
            <label htmlFor="mv-match" className="sr-only">
              Match
            </label>
            <select id="mv-match" className="select match-select" value={tl.match_id} onChange={(e) => window.location.assign(playerHref('match', { m: e.target.value }))} aria-label="Match">
              {whole.map((m) => (
                <option key={m.match_id} value={m.match_id}>
                  {m.home} v {m.away}
                  {m.round !== null ? ` · ${fill(w.round, { n: m.round })}` : ''}
                </option>
              ))}
            </select>
            <label htmlFor="mv-lang" className="sr-only">
              {ui.language}
            </label>
            <select id="mv-lang" className="select wide-only" style={{ width: 'auto' }} value={prefs.lang} onChange={(e) => update({ lang: e.target.value as Lang })} aria-label={ui.language}>
              {LANGS.map((l) => (
                <option key={l.code} value={l.code} lang={l.code}>
                  {l.native}
                </option>
              ))}
            </select>
            <Button onClick={() => setPanel('ask')}>{ui.ask}</Button>
            <MenuButton label={ui.more} items={[{ key: 'keys', label: `${ui.shortcuts} (?)`, onSelect: () => setPanel('shortcuts') }]} />
            <Button icon aria-label={ui.personalize} onClick={() => setPanel('personalize')}>
              <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true">
                <path d="M3 5 H15 M3 9 H15 M3 13 H15" style={{ fill: 'none', stroke: 'currentColor', strokeWidth: 1.6, strokeLinecap: 'round' }} />
                <circle cx="6" cy="5" r="2" style={{ fill: 'var(--surface)', stroke: 'currentColor', strokeWidth: 1.6 }} />
                <circle cx="12" cy="9" r="2" style={{ fill: 'var(--surface)', stroke: 'currentColor', strokeWidth: 1.6 }} />
                <circle cx="8" cy="13" r="2" style={{ fill: 'var(--surface)', stroke: 'currentColor', strokeWidth: 1.6 }} />
              </svg>
            </Button>
          </div>
        </header>

        <nav className="match-modes anim-rise" aria-label={ui.viewingMode}>
          <ModeSwitcher value={mode} onChange={(m) => update({ mode: m })} />
        </nav>

        <main className="match-main">
          <section aria-label="Match" className="match-stage">
            <div className="pitch-card anim-rise">
              {game.active ? (
                game.board ? (
                  <PlayBoard
                    positions={game.positions}
                    ballOwner={game.ballOwner}
                    orders={game.orders}
                    sideOf={sideOf}
                    numOf={numOf}
                    commandable={game.commandable}
                    selected={game.selected}
                    goalX={game.goalX}
                    offsideX={game.offsideX}
                    playback={game.playback}
                    editable={!game.running}
                    patterns={{ kes: colours.home.pattern, ash: colours.away.pattern }}
                    reduced={reducedMotion}
                    label={`Play it out board from ${clockOf({ period: game.board.period, t_ms: game.board.t_ms })}. ${gameText}`}
                    banner={
                      shownRun && game.decided ? (
                        <div className="goal-banner board-banner anim-pop" data-outcome={shownRun.outcome} aria-hidden="true">
                          {OUTCOME_LABEL[shownRun.outcome]}
                        </div>
                      ) : null
                    }
                    chips={
                      <span className="map-chip map-chip-space">
                        🎮 Play it out · {game.side === 'attack' ? 'you attack' : 'you defend'}
                      </span>
                    }
                    onMove={game.move}
                    onTap={game.tap}
                  />
                ) : (
                  <LoadingPitch stage={1} orientation="h" checks={ui.loading} />
                )
              ) : (
              <PlayerPitch
                frames={frames}
                now={clock.now}
                toPosition={mt.toPosition}
                sideOf={sideOf}
                numOf={numOf}
                overlays={mine}
                whatIf={whatIf}
                patterns={{ kes: colours.home.pattern, ash: colours.away.pattern }}
                orientation={orientation}
                fieldStrength={strength}
                levels={levels}
                reduced={reducedMotion}
                words={words}
                focus={answering && answer?.show ? answer.show.player_ids : undefined}
                label={`2D pitch, ${tl.home.name} ${score.kes}, ${tl.away.name} ${score.ash}, ${clockText}. ${captionText}`}
                chips={chips}
                scrim={scrim}
                dim={!!scrim}
              />
              )}
            </div>

            <CaptionBar captions={game.active ? [] : captions} override={game.active ? { text: gameText, lang: 'en' } : answerText ? { text: answerText, lang: answerLang } : undefined} meta={game.active ? 'Play it out · your plan, played by the match engine 8 times' : meta} size={mode === 'audio' ? prefs.capSize + 2 : prefs.capSize} voice={{ on: voiceWanted, speaking: clock.playing, label: voiceLabel }} />

            {!game.active && (
            <div className="card stack player-transport" style={{ padding: '12px 16px', gap: 12 }}>
              <div className="cluster" style={{ gap: 8 }}>
                <Button variant="ghost" icon aria-label={w.prevMoment} title={`${w.prevMoment} (J)`} onClick={() => step(-1)}>
                  ⏮
                </Button>
                <Button variant="ghost" icon aria-label={w.back10} title={w.back10} onClick={() => clock.seek(clock.now() - 10_000)}>
                  −10
                </Button>
                <Button variant="primary" icon round aria-label={clock.playing ? ui.pause : ui.play} onClick={clock.toggle}>
                  {clock.playing ? '❚❚' : '▶'}
                </Button>
                <Button variant="ghost" icon aria-label={w.fwd10} title={w.fwd10} onClick={() => clock.seek(clock.now() + 10_000)}>
                  +10
                </Button>
                <Button variant="ghost" icon aria-label={w.nextMoment} title={`${w.nextMoment} (L)`} onClick={() => step(1)}>
                  ⏭
                </Button>
                <span className="mono player-clock">{clockText}</span>
                <Button variant="secondary" className="btn-sm play-it-out" onClick={playHere} title="Take over this moment: move players, give orders, and let the match engine play it out">
                  🎮 Play it out
                </Button>
                <span className="spacer" />
                <Segmented options={SPEEDS.map((s) => ({ value: String(s), label: `${s}×` }))} value={String(clock.speed)} onChange={(s) => clock.setSpeed(Number(s) as Speed)} label={w.speed} minWidth={52} />
              </div>
              <MatchScrubber
                periods={tl.periods}
                total={mt.total}
                g={clock.g}
                toMatch={mt.toMatch}
                toPosition={mt.toPosition}
                moments={moments}
                goals={tl.goals}
                selected={highlight}
                label={w.scrubber}
                halfLabels={w.half}
                onSeek={(g) => clock.seek(g)}
                onMoment={pick}
              />
              <p className="muted" style={{ margin: 0, fontSize: 12 }}>
                {w.keys}
              </p>
            </div>
            )}
            <p className="muted" style={{ fontSize: 12 }}>
              {ui.synthetic}
            </p>
          </section>

          {screen.phonePortrait ? (
            <BottomSheet title={panelTitle} open={sheetOpen} onToggle={setSheetOpen}>
              {sidePanel}
            </BottomSheet>
          ) : (
            <aside aria-label={`${modeLabel} panel`} className="match-panel">
              {sidePanel}
            </aside>
          )}
        </main>
      </div>

      <PersonalizeDrawer open={panel === 'personalize'} onClose={() => setPanel('none')} />
      <Drawer open={panel === 'ask'} onClose={() => setPanel('none')} title={ui.ask}>
        <AskPanel t={0} at={{ matchId: tl.match_id, period: pos.period, t_ms: Math.round(pos.t_ms), momentId: selected ?? live?.candidate_id ?? null }} onShow={showAnswer} />
      </Drawer>
      <ShortcutsDialog open={panel === 'shortcuts'} onClose={() => setPanel('none')} />
      <LiveRegion msg={msg} />
    </div>
  );
}

type Load = { state: 'loading'; stage: number } | { state: 'error' } | { state: 'ok'; tl: Timeline; graphics: Graphics; matches: MatchSummary[] };

/**
 * The match view for a whole match from the OffBall API (PRD 10.1, 15.2): all 90 minutes to play and scrub, every
 * moment the models found with the crew's graphics, and what-ifs replayed in the match engine, in the showcase's look.
 */
export function WholeMatchView({ matchId }: { matchId: string }) {
  const { prefs } = usePrefs();
  const { ui } = useI18n();
  useDocumentLocale(prefs.lang);
  const w = playerWords(prefs.lang);
  const screen = useScreenClass();
  const [load, setLoad] = useState<Load>({ state: 'loading', stage: 0 });
  const [attempt, setAttempt] = useState(0);
  const [start] = useState(startFrom);

  useEffect(() => {
    const ctl = new AbortController();
    setLoad({ state: 'loading', stage: 0 });
    const matches = fetchMatches(ctl.signal).then((m) => (setLoad((l) => (l.state === 'loading' ? { ...l, stage: Math.max(l.stage, 1) } : l)), m));
    const tl = fetchTimeline(matchId, ctl.signal).then((t) => (setLoad((l) => (l.state === 'loading' ? { ...l, stage: Math.max(l.stage, 2) } : l)), t));
    const graphics = fetchGraphics(matchId, ctl.signal).catch((): Graphics => ({ overlays: [], moments: {} }));
    Promise.all([tl, graphics, matches.catch((): MatchSummary[] => [])])
      .then(([t, g, m]) => setLoad({ state: 'ok', tl: t, graphics: g, matches: m }))
      .catch(() => !ctl.signal.aborted && setLoad({ state: 'error' }));
    return () => ctl.abort();
  }, [matchId, attempt]);

  if (load.state === 'ok') return <WholeMatch key={load.tl.match_id} tl={load.tl} graphics={load.graphics} matches={load.matches} start={start} />;
  return (
    <div className="screen match" data-screen={screen.phonePortrait ? 'portrait' : 'desktop'}>
      <div className="container stack" style={{ gap: 14 }}>
        <header className="match-header">
          <Logo size={screen.phonePortrait ? 22 : 28} />
        </header>
        {load.state === 'loading' ? (
          <>
            <LoadingPitch stage={load.stage} orientation={screen.phonePortrait ? 'v' : 'h'} checks={ui.loading} />
            <p className="muted" role="status" style={{ fontSize: 14 }}>
              {w.finding}
            </p>
          </>
        ) : (
          <div className="card cluster" role="alert">
            <Chip tone="danger">{w.matchFailed}</Chip>
            <Button variant="secondary" className="btn-sm" onClick={() => setAttempt((n) => n + 1)}>
              {w.retry}
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}
