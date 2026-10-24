import { useState, type CSSProperties } from 'react';
import { Stage2D } from '../components/match';
import { Button, CaptionReveal, CheckIcon, Chip, LinkButton, Logo, Stepper, Switch } from '../components/ui';
import { MODE_GLYPHS } from '../lib/content';
import { getStore, useMatchClock } from '../lib/feed';
import { LANGS, PACKS, useDocumentLocale, useI18n } from '../lib/i18n';
import { CLUBS, player, type Team } from '../lib/match';
import { MODE_IDS, usePrefs, type Club } from '../lib/prefs';

const STEPS = ['Watch', 'Club', 'Language', 'Ready'] as const;

const CLUB_CHOICES: readonly { id: Club; name: string; color: string }[] = [
  { id: 'kes', name: CLUBS.kes.name, color: 'var(--kes)' },
  { id: 'ash', name: CLUBS.ash.name, color: 'var(--ash)' },
  { id: 'none', name: 'No favourite', color: 'var(--muted)' },
];

/** Players with a Player focus story, per club. */
const ROSTER: Record<Team, readonly string[]> = { kes: ['kes-09', 'kes-10', 'kes-07'], ash: ['ash-05', 'ash-10'] };

const Tick = () => (
  <span className="anim-pop" style={{ width: 22, height: 22, borderRadius: 11, background: 'var(--space)', color: 'var(--on-space)', display: 'inline-flex', alignItems: 'center', justifyContent: 'center', flex: 'none' }}>
    <CheckIcon size={12} />
  </span>
);

/**
 * The live preview: the real renderer replaying the moment once with the viewer's choices, so they see how the
 * captions will read before they commit (PRD 15.8). Remounted on every change, so it replays.
 */
function Preview() {
  const { prefs } = usePrefs();
  const i18n = useI18n();
  const store = getStore();
  const clock = useMatchClock(store, false, { loop: false });
  const mode = prefs.mode;
  const caption = store.active(clock.t_ms, { mode, whatIf: false, fav: prefs.fav }).find((a) => a.overlay.kind === 'caption');
  const text = mode === 'broadcaster' ? 'overlay.upsert · run_arrow · m07-o0041 · auto' : (caption?.overlay.text[prefs.lang] ?? caption?.overlay.text.en ?? '').replace('{count}', '1');
  return (
    <>
      <Stage2D store={store} time={clock} mode={mode} density={prefs.density} theme={prefs.theme} fav={prefs.fav} i18n={i18n} orientation="h" variant="real" ghosts={false} onFollow={() => {}} />
      <div style={{ background: 'var(--bg)', border: '1px solid var(--line)', borderRadius: 12, padding: '12px 14px', minHeight: 76 }} aria-live="polite">
        <CaptionReveal text={text} lang={prefs.lang} style={mode === 'broadcaster' ? { fontFamily: 'var(--font-mono)', fontSize: 15, lineHeight: 1.45 } : { fontSize: 17, lineHeight: 1.45, fontWeight: 500 }} />
      </div>
      <Button variant="ghost" className="btn-sm" onClick={() => clock.scrub(0)} style={{ alignSelf: 'flex-start' }}>
        {clock.playing ? 'Playing' : 'Replay the preview'}
      </Button>
    </>
  );
}

/** First run: three quick choices and a summary, each skippable, with a live preview (PRD 15.8). */
export function Onboarding() {
  const { prefs, update, reset } = usePrefs();
  const { pack, ui } = useI18n();
  useDocumentLocale(prefs.lang);
  const [step, setStep] = useState(0);
  const [dir, setDir] = useState<'fwd' | 'back'>('fwd');
  const go = (n: number) => {
    setDir(n > step ? 'fwd' : 'back');
    setStep(n);
  };
  const slide = dir === 'back' ? 'anim-slide-back' : 'anim-slide-fwd';
  const langInfo = LANGS.find((l) => l.code === prefs.lang)!;
  const modeLabel = pack.modes[prefs.mode].label;
  const favPlayer = player(prefs.fav);
  const delayed = (i: number, extra?: CSSProperties): CSSProperties => ({ animationDelay: `calc(var(--stagger) * ${i})`, ...extra });
  const finish = () => update({ onboarded: true });
  const skip = () => {
    reset();
    window.location.hash = '/match';
  };
  const framing = prefs.club === 'kes' ? ui.attacking : prefs.club === 'ash' ? ui.defending : '';

  return (
    <div className="screen" style={{ padding: '28px 24px 96px' }}>
      <div className="container" style={{ maxWidth: 1180 }}>
        <header className="cluster anim-rise" style={{ justifyContent: 'space-between', marginBottom: 28, gap: 16 }}>
          <Logo />
          <Stepper steps={STEPS} current={step === 0 ? -1 : step === 4 ? 4 : step - 1} />
        </header>

        <div className="row row-stretch" style={{ gap: 28 }}>
          <section className="grow stack-lg" style={{ flexBasis: 560 }} aria-label="Setup">
            {step === 0 && (
              <div key="welcome" className={slide}>
                <p className="card-label" style={{ color: 'var(--space-ink)', marginBottom: 10 }}>
                  WELCOME
                </p>
                <h1 className="display" style={{ fontSize: 'clamp(40px, 8vw, 64px)', lineHeight: 0.95, marginBottom: 14 }}>
                  See the play behind the play.
                </h1>
                <p style={{ fontSize: 18, lineHeight: 1.55, color: 'var(--muted)', maxWidth: 560, marginBottom: 24 }}>
                  Most goals are made off the ball. OffBall shows you the runs that open space, why they matter, and what would have happened without them. Three quick choices and you’re watching.
                </p>
                <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexDirection: 'column', gap: 10 }}>
                  {[
                    ['var(--space)', 'No account. Your choices stay on this device.'],
                    ['var(--kes)', 'Every claim is fact-checked against match data.'],
                    ['var(--ash)', 'All matches are synthetic: fictional clubs and players.'],
                  ].map(([color, text], i) => (
                    <li key={text} className="anim-rise" style={{ display: 'flex', gap: 12, alignItems: 'center', fontSize: 15, ...delayed(i + 3) }}>
                      <span style={{ width: 10, height: 10, borderRadius: 5, background: color }} />
                      {text}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {step === 1 && (
              <div key="mode" className={slide}>
                <h1 className="display" style={{ fontSize: 44, marginBottom: 6 }}>
                  How do you like to watch?
                </h1>
                <p className="muted" style={{ fontSize: 15, marginBottom: 18 }}>
                  You can switch any time during a match.
                </p>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))', gap: 12 }}>
                  {MODE_IDS.map((m, i) => {
                    const on = prefs.mode === m;
                    return (
                      <button key={m} type="button" aria-pressed={on} onClick={() => update({ mode: m })} className="choice press anim-rise" style={delayed(i, { minHeight: 150 })}>
                        <span style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', width: '100%' }}>
                          <span
                            className="display"
                            aria-hidden="true"
                            style={{ width: 40, height: 40, borderRadius: 12, display: 'inline-flex', alignItems: 'center', justifyContent: 'center', fontSize: 22, transition: 'background-color var(--dur-base), color var(--dur-base), transform var(--dur-smooth) var(--ease-pop)', background: on ? 'var(--space)' : 'var(--surface-2)', color: on ? 'var(--on-space)' : 'var(--text)', transform: on ? 'rotate(-6deg) scale(1.06)' : 'none' }}
                          >
                            {MODE_GLYPHS[m]}
                          </span>
                          {on && <Tick />}
                        </span>
                        <span style={{ fontSize: 17, fontWeight: 700, marginTop: 10 }}>{pack.modes[m].label}</span>
                        <span style={{ fontSize: 13, lineHeight: 1.45, color: 'var(--muted)' }}>{pack.modes[m].desc}</span>
                      </button>
                    );
                  })}
                </div>
              </div>
            )}

            {step === 2 && (
              <div key="club" className={slide}>
                <h1 className="display" style={{ fontSize: 44, marginBottom: 6 }}>
                  Pick your club and player
                </h1>
                <p className="muted" style={{ fontSize: 15, marginBottom: 18 }}>
                  We’ll use your club’s colours and frame moments from your side.
                </p>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: 12, marginBottom: 22 }}>
                  {CLUB_CHOICES.map((c, i) => {
                    const on = prefs.club === c.id;
                    return (
                      <button
                        key={c.id}
                        type="button"
                        aria-pressed={on}
                        onClick={() => update({ club: c.id, ...(c.id !== 'none' ? { fav: ROSTER[c.id][0] } : {}) })}
                        className="choice press anim-rise"
                        style={delayed(i, { flexDirection: 'row', alignItems: 'center', gap: 14, minHeight: 72 })}
                      >
                        <span style={{ width: 34, height: 40, flex: 'none', borderRadius: '6px 6px 17px 17px', background: c.color, transition: 'transform var(--dur-smooth) var(--ease-pop)', transform: on ? 'scale(1.1)' : 'none' }} />
                        <span style={{ fontSize: 16, fontWeight: 700 }}>{c.name}</span>
                        {on && (
                          <span style={{ marginInlineStart: 'auto' }}>
                            <Tick />
                          </span>
                        )}
                      </button>
                    );
                  })}
                </div>
                {prefs.club !== 'none' && (
                  <div key={prefs.club} className="anim-fade">
                    <h2 className="field-label">Favourite player</h2>
                    <div className="cluster" style={{ gap: 8 }}>
                      {ROSTER[prefs.club].map((id, i) => {
                        const p = player(id);
                        const on = prefs.fav === id;
                        return (
                          <button
                            key={id}
                            type="button"
                            aria-pressed={on}
                            onClick={() => update({ fav: id })}
                            className="press anim-rise"
                            style={{ display: 'inline-flex', alignItems: 'center', gap: 8, minHeight: 44, padding: '0 14px 0 8px', borderRadius: 999, border: 0, fontWeight: 600, fontSize: 14, background: on ? 'var(--surface-2)' : 'transparent', boxShadow: `inset 0 0 0 ${on ? '2px var(--space)' : '1px var(--line)'}`, ...delayed(i) }}
                          >
                            <span style={{ width: 26, height: 26, borderRadius: 13, display: 'inline-flex', alignItems: 'center', justifyContent: 'center', fontSize: 12, fontWeight: 700, background: `var(--${p.team})`, color: `var(--on-${p.team})` }}>{p.num}</span>
                            {p.name}
                          </button>
                        );
                      })}
                    </div>
                  </div>
                )}
              </div>
            )}

            {step === 3 && (
              <div key="lang" className={slide}>
                <h1 className="display" style={{ fontSize: 44, marginBottom: 6 }}>
                  Language and voice
                </h1>
                <p className="muted" style={{ fontSize: 15, marginBottom: 18 }}>
                  Captions and commentary in your language. English is always one tap away.
                </p>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))', gap: 8, marginBottom: 20 }}>
                  {LANGS.map((l, i) => {
                    const on = prefs.lang === l.code;
                    return (
                      <button key={l.code} type="button" lang={l.code} aria-pressed={on} onClick={() => update({ lang: l.code })} className="choice press anim-rise" style={{ minHeight: 56, padding: '6px 12px', borderRadius: 12, fontWeight: 600, fontSize: 15, ...delayed(i / 2) }}>
                        {l.native}
                        <span style={{ fontSize: 11, fontWeight: 400, color: 'var(--muted)' }} lang="en">
                          {l.en}
                          {!PACKS[l.code].reviewed && l.code !== 'en' ? ' · draft' : ''}
                        </span>
                      </button>
                    );
                  })}
                </div>
                <div style={{ maxWidth: 420 }}>
                  <Switch block checked={prefs.voice} onChange={(voice) => update({ voice })} label="Voice commentary" hint="Spoken lines with your device’s voice, paced so they never overlap" />
                </div>
              </div>
            )}

            {step === 4 && (
              <div key="done" className={slide} style={{ position: 'relative' }}>
                <p className="card-label" style={{ color: 'var(--space-ink)', marginBottom: 10 }}>
                  ALL SET
                </p>
                <h1 className="display" style={{ fontSize: 'clamp(36px, 7vw, 56px)', lineHeight: 1, marginBottom: 14 }}>
                  Kestrel Bay v Ashmoor is live.
                </h1>
                <p className="muted" style={{ fontSize: 16, marginBottom: 18 }}>
                  Here’s how you’ll watch it:
                </p>
                <div className="cluster" style={{ gap: 8 }}>
                  {[`${modeLabel}`, prefs.club === 'none' ? 'No favourite club' : `${CLUBS[prefs.club].name} · No. ${favPlayer.num} ${favPlayer.name}`, langInfo.native, prefs.voice ? 'Voice on' : 'Voice off'].map((text, i) => (
                    <Chip key={text} tone={i === 0 ? 'space' : 'outline'} size="lg" className="anim-pop" style={{ ...delayed(i * 2 + 2), fontSize: 14 }}>
                      {text}
                    </Chip>
                  ))}
                </div>
              </div>
            )}

            <div className="cluster" style={{ marginTop: 'auto', paddingTop: 8, gap: 12 }}>
              {step > 0 && step < 4 && (
                <Button variant="ghost" size="lg" onClick={() => go(step - 1)}>
                  Back
                </Button>
              )}
              {step < 4 ? (
                <Button variant="primary" size="lg" onClick={() => go(step + 1)}>
                  {step === 0 ? 'Get started' : step === 3 ? 'Finish' : 'Continue'}
                  <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true" style={{ transform: 'scaleX(var(--flip, 1))' }}>
                    <path d="M3 8 H13 M9 4 L13 8 L9 12" style={{ fill: 'none', stroke: 'currentColor', strokeWidth: 2, strokeLinecap: 'round', strokeLinejoin: 'round' }} />
                  </svg>
                </Button>
              ) : (
                <LinkButton href="#/match" variant="primary" size="lg" className="anim-pop" onClick={finish}>
                  Watch the match
                  <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
                    <path d="M4 2 L14 8 L4 14 Z" style={{ fill: 'currentColor' }} />
                  </svg>
                </LinkButton>
              )}
              {step < 4 && (
                <button type="button" className="btn btn-ghost spacer press" style={{ fontSize: 14 }} onClick={skip}>
                  Skip, use defaults
                </button>
              )}
            </div>
          </section>

          <aside aria-label="Live preview" className="side card anim-rise" style={{ flexBasis: 380, display: 'flex', flexDirection: 'column', gap: 12, padding: 16, borderRadius: 18 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span className="card-label">LIVE PREVIEW</span>
              <Chip key={`${prefs.mode}-${prefs.lang}`} tone="space" className="anim-pop">
                {modeLabel}
                {prefs.lang !== 'en' ? ` · ${langInfo.en}` : ''}
              </Chip>
            </div>
            <Preview key={`${prefs.mode}-${prefs.lang}-${prefs.club}-${prefs.fav}`} />
            <p className="muted" style={{ fontSize: 12 }}>
              {framing ? `${framing} · ` : ''}
              {!PACKS[prefs.lang].reviewed && prefs.lang !== 'en' ? ui.draft : `This is how captions will read in ${modeLabel} mode.`}
            </p>
          </aside>
        </div>
      </div>
    </div>
  );
}
