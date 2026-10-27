import { useCallback, useEffect, useMemo, useState, useSyncExternalStore, type CSSProperties } from 'react';
import { MatchScrubber } from '../components/player/MatchScrubber';
import { MomentList } from '../components/player/MomentList';
import { MomentPanel } from '../components/player/MomentPanel';
import { PlayerPitch, type PlayerTag } from '../components/player/PlayerPitch';
import { ModeSwitcher } from '../components/match/ModeSwitcher';
import { DENSITY_WEIGHT, FIELD_WEIGHT } from '../components/match/Stage2D';
import { Button, CaptionReveal, Chip, Logo, Segmented, Spinner } from '../components/ui';
import { apiBase } from '../lib/api';
import { contrast, parseColor, readToken } from '../lib/color';
import type { Overlay } from '../lib/feed/types';
import { useHashQuery } from '../lib/hooks';
import { fill, isRtl, useI18n } from '../lib/i18n';
import { LEAGUE, checkFixture, displayColour, type FixtureCheck } from '../lib/kits';
import type { Team } from '../lib/match';
import { fetchGraphics, fetchTimeline, playerHref, type Graphics, type Moment, type Timeline, type WhatIf } from '../lib/player/api';
import { SPEEDS, clockOf, matchTime, useMatchClock, type Speed } from '../lib/player/clock';
import { MatchFrames } from '../lib/player/frames';
import { GHOST_AFTER_MS, GHOST_BEFORE_MS } from '../lib/player/whatif';
import { playerWords } from '../lib/player/words';
import { usePrefs } from '../lib/prefs';

/** A jump to a moment starts this long before it, so the viewer sees the play build. */
const LEAD_IN_MS = 3000;

type Load = { state: 'loading' } | { state: 'error' } | { state: 'ok'; tl: Timeline; graphics: Graphics };

/** `t=2:1080000` in the address: the second half, 18 minutes in. */
const startFrom = (raw: string | null) => {
  const [p, t] = (raw ?? '').split(':').map(Number);
  return Number.isFinite(p) && Number.isFinite(t) ? { period: p, t_ms: t } : null;
};

/** The fixture's colours, checked for colour vision against this theme's pitch (PRD 16.3). */
function fixtureColours(tl: Timeline, theme: string): FixtureCheck & { onHome: string; onAway: string } {
  void theme;
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

function Player({ tl, graphics, start }: { tl: Timeline; graphics: Graphics; start: { period: number; t_ms: number } | null }) {
  const { prefs, update } = usePrefs();
  const { lang } = useI18n();
  const w = playerWords(lang);
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
  );
  const pos = mt.toPosition(clock.g);

  const roster = useMemo(() => new Map(tl.players.map((p) => [p.player_id, p])), [tl]);
  const clubOfId = useCallback((id: string) => roster.get(id)?.club_id ?? id.split('-')[0], [roster]);
  const sideOf = useCallback((id: string): Team => (clubOfId(id) === tl.home.club_id ? 'kes' : 'ash'), [clubOfId, tl]);
  const numOf = useCallback((id: string) => roster.get(id)?.number ?? (Number(id.split('-')[1]) || 0), [roster]);
  const label = useCallback((id: string) => {
    const p = roster.get(id);
    return p ? fill(w.player, { n: p.number, name: p.name }) : id;
  }, [roster, w]);
  const clubName = useCallback((id: string) => (clubOfId(id) === tl.home.club_id ? tl.home.name : tl.away.name), [clubOfId, tl]);

  const colours = useMemo(() => fixtureColours(tl, prefs.theme), [tl, prefs.theme]);
  const vars = {
    '--kes': colours.home.colour,
    '--ash': colours.away.colour,
    '--kes-rgb': rgbOf(colours.home.colour),
    '--ash-rgb': rgbOf(colours.away.colour),
    '--on-kes': colours.onHome,
    '--on-ash': colours.onAway,
  } as CSSProperties;

  const [overlays, setOverlays] = useState<Overlay[]>(graphics.overlays);
  const [moments, setMoments] = useState<Moment[]>(() => tl.moments.map((m) => ({ ...m, ...(graphics.moments[m.candidate_id] ? { graphics: graphics.moments[m.candidate_id].status, graphics_note: graphics.moments[m.candidate_id].note } : {}) })));
  const [selected, setSelected] = useState<string | null>(null);
  const [whatIf, setWhatIf] = useState<WhatIf | null>(null);
  const mine = useMemo(() => overlays.filter((o) => o.mode === prefs.mode && !o.counterfactual_id), [overlays, prefs.mode]);
  const onAir = mine.filter((o) => o.period === pos.period && o.t_start_ms <= pos.t_ms && pos.t_ms < o.t_end_ms);
  const caption = onAir.find((o) => o.kind === 'caption');
  const rings = onAir.filter((o) => o.kind === 'gap_ring' && o.anchors.centre_xy && (o.text[lang] ?? o.text.en));
  const stat = onAir.find((o) => o.kind === 'stat_card');
  const tags: PlayerTag[] = onAir.filter((o) => o.kind === 'player_tag' && o.anchors.player_id).map((o) => ({ id: o.overlay_id, player_id: o.anchors.player_id!, text: o.text[lang] ?? o.text.en ?? '' }));

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
      window.history.replaceState(null, '', playerHref('play', { m: tl.match_id, t: `${m.period}:${Math.max(0, m.t_start_ms - LEAD_IN_MS)}` }));
    },
    [clock, gOf, tl.match_id],
  );
  const pick = useCallback(
    (m: Moment) => {
      if (m.candidate_id !== selected) setWhatIf(null);
      setSelected(m.candidate_id);
      jump(m);
    },
    [jump, selected],
  );
  const step = useCallback(
    (dir: 1 | -1) => {
      const g = clock.now();
      const next = dir > 0 ? moments.find((m) => gOf(m) - LEAD_IN_MS > g + 500) : [...moments].reverse().find((m) => gOf(m) - LEAD_IN_MS < g - 1500);
      if (next) pick(next);
    },
    [clock, moments, gOf, pick],
  );

  // Keyboard: space plays or pauses, arrows move 10 s, J and L step through the moments.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null;
      if (el && (el.closest('input, select, textarea, [role="slider"], [role="radiogroup"]') || e.metaKey || e.ctrlKey || e.altKey)) return;
      if (e.key === ' ' && !el?.closest('button, a')) clock.toggle();
      else if (e.key === 'ArrowLeft') clock.seek(clock.now() - 10_000);
      else if (e.key === 'ArrowRight') clock.seek(clock.now() + 10_000);
      else if (e.key === 'j' || e.key === 'J') step(-1);
      else if (e.key === 'l' || e.key === 'L') step(1);
      else return;
      e.preventDefault();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [clock, step]);

  const score = { home: 0, away: 0 };
  for (const goal of tl.goals) if (mt.toMatch(goal) <= clock.g) score[goal.club_id === tl.home.club_id ? 'home' : 'away']++;
  const failed = frames.error(pos.period, pos.t_ms);
  const strength = Math.min(1, FIELD_WEIGHT[prefs.mode] * DENSITY_WEIGHT[prefs.density]);
  const captionText = caption ? (caption.text[lang] ?? caption.text.en ?? '') : '';
  const captionLang = caption && caption.text[lang] ? lang : 'en';
  const captionMoment = caption ? moments.find((m) => m.candidate_id === caption.detected_moment_id) : null;

  return (
    <div className="screen player-screen" style={vars} lang={lang}>
      <div className="container stack" style={{ gap: 14 }}>
        <header className="cluster player-head anim-rise">
          <Logo href={playerHref('matches')} />
          <a href={playerHref('matches')} className="btn btn-ghost btn-sm press">
            {w.back}
          </a>
          <h1 className="display player-score" aria-label={fill(w.score, { home: tl.home.name, hs: score.home, away: tl.away.name, as: score.away })}>
            <span className="player-club" data-team="kes">
              {tl.home.name}
            </span>
            <span className="tabular">
              {score.home}–{score.away}
            </span>
            <span className="player-club" data-team="ash">
              {tl.away.name}
            </span>
          </h1>
          <span className="mono player-clock" aria-live="off">
            {clockOf(pos)}
          </span>
          <Chip tone="muted">{w.half[pos.period] ?? pos.period}</Chip>
          {clock.waiting && !failed && (
            <span className="cluster muted" role="status" style={{ gap: 6, fontSize: 13 }}>
              <Spinner /> {w.buffering}
            </span>
          )}
        </header>
        <ModeSwitcher value={prefs.mode} onChange={(mode) => update({ mode })} />

        <div className="row row-stretch" style={{ gap: 18 }}>
          <main className="grow stack" style={{ gap: 12 }}>
            <PlayerPitch
              frames={frames}
              now={clock.now}
              toPosition={mt.toPosition}
              sideOf={sideOf}
              numOf={numOf}
              overlays={mine}
              whatIf={whatIf}
              patterns={{ kes: colours.home.pattern, ash: colours.away.pattern }}
              fieldStrength={strength}
              reduced={prefs.reducedMotion}
              tags={tags}
              label={`${tl.home.name} ${score.home}, ${tl.away.name} ${score.away}, ${clockOf(pos)}. ${captionText}`}
              chips={
                <>
                  {rings.map((o) => (
                    <Chip key={o.overlay_id} tone="space">
                      {o.text[lang] ?? o.text.en}
                    </Chip>
                  ))}
                  {stat && (
                    <Chip tone="solid">
                      {stat.text[lang] ?? stat.text.en}
                    </Chip>
                  )}
                  {whatIf && whatIf.period === pos.period && pos.t_ms >= whatIf.t_start_ms - GHOST_BEFORE_MS && pos.t_ms <= whatIf.t_measure_ms + GHOST_AFTER_MS && <Chip tone="accent">{w.whatIf}</Chip>}
                </>
              }
              scrim={
                failed ? (
                  <div className="pitch-scrim">
                    <p>{w.framesFailed}</p>
                    <Button variant="secondary" className="btn-sm" onClick={() => frames.retry(pos.period, pos.t_ms)}>
                      {w.retry}
                    </Button>
                  </div>
                ) : undefined
              }
            />
            <div className="card caption-bar player-caption">
              <div className="caption-bar-main">
                {captionText ? <CaptionReveal key={caption!.overlay_id} text={captionText} lang={captionLang} style={{ fontSize: prefs.capSize, lineHeight: 1.4, fontWeight: 500 }} /> : <p style={{ fontSize: prefs.capSize }}>&nbsp;</p>}
                <p className="caption-meta">
                  {captionMoment ? `${w.types[captionMoment.type] ?? captionMoment.type} · ${w.aiGenerated}` : live ? `${w.types[live.type] ?? live.type} · ${w.graphics[live.graphics]}` : ' '}
                </p>
              </div>
            </div>
            <div className="card stack player-transport" style={{ gap: 12 }}>
              <div className="cluster" style={{ gap: 8 }}>
                <Button variant="ghost" icon aria-label={w.prevMoment} title={w.prevMoment} onClick={() => step(-1)}>
                  ⏮
                </Button>
                <Button variant="ghost" icon aria-label={w.back10} title={w.back10} onClick={() => clock.seek(clock.now() - 10_000)}>
                  −10
                </Button>
                <Button variant="primary" icon round aria-label={clock.playing ? w.pause : w.play} onClick={clock.toggle}>
                  {clock.playing ? '❚❚' : '▶'}
                </Button>
                <Button variant="ghost" icon aria-label={w.fwd10} title={w.fwd10} onClick={() => clock.seek(clock.now() + 10_000)}>
                  +10
                </Button>
                <Button variant="ghost" icon aria-label={w.nextMoment} title={w.nextMoment} onClick={() => step(1)}>
                  ⏭
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
          </main>
          <aside className="side stack player-side" style={{ gap: 14 }} dir={isRtl(lang) ? 'rtl' : 'ltr'}>
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
                mode={prefs.mode}
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
          </aside>
        </div>
      </div>
    </div>
  );
}

/**
 * A whole match from the OffBall API (PRD 10.1, 15.2): all 90 minutes to play and scrub, every moment the models
 * found with the crew's graphics, and what-ifs replayed in the match engine.
 */
export function MatchPlayer() {
  const { lang } = useI18n();
  const w = playerWords(lang);
  const id = useHashQuery('m');
  const t = useHashQuery('t');
  const [load, setLoad] = useState<Load>({ state: 'loading' });
  const [attempt, setAttempt] = useState(0);
  const backend = !!apiBase();
  const [start] = useState(() => startFrom(t));

  useEffect(() => {
    if (!id || !backend) return;
    const ctl = new AbortController();
    setLoad({ state: 'loading' });
    Promise.all([fetchTimeline(id, ctl.signal), fetchGraphics(id, ctl.signal).catch((): Graphics => ({ overlays: [], moments: {} }))])
      .then(([tl, graphics]) => setLoad({ state: 'ok', tl, graphics }))
      .catch(() => !ctl.signal.aborted && setLoad({ state: 'error' }));
    return () => ctl.abort();
  }, [id, backend, attempt]);

  if (!id) {
    window.location.replace(playerHref('matches'));
    return null;
  }
  if (load.state === 'ok') return <Player key={load.tl.match_id} tl={load.tl} graphics={load.graphics} start={start} />;
  return (
    <div className="screen" lang={lang}>
      <div className="container stack-lg">
        <header className="cluster">
          <Logo href={playerHref('matches')} />
          <a href={playerHref('matches')} className="btn btn-ghost btn-sm press">
            {w.back}
          </a>
        </header>
        {!backend && <p className="card">{w.noBackend}</p>}
        {backend && load.state === 'loading' && (
          <p className="card cluster muted" role="status" style={{ gap: 10 }}>
            <Spinner /> {w.finding}
          </p>
        )}
        {load.state === 'error' && (
          <div className="card cluster" role="alert">
            <span>{w.matchFailed}</span>
            <Button variant="secondary" className="btn-sm" onClick={() => setAttempt((n) => n + 1)}>
              {w.retry}
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}

