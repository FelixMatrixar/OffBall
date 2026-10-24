import type { ReactNode } from 'react';
import { LoadChecks } from '../components/match';
import { PitchMarkings, VIEWBOX } from '../components/pitch';
import { Chip, Logo, PulseDot, Spinner, ToastStack } from '../components/ui';
import { useCycle } from '../lib/hooks';
import { usePrefs } from '../lib/prefs';

function State({ title, note, children, delay }: { title: string; note: string; children: ReactNode; delay: number }) {
  return (
    <article className="card anim-rise" style={{ padding: 14, display: 'flex', flexDirection: 'column', gap: 10, animationDelay: `${delay}ms` }}>
      <div style={{ height: 160, borderRadius: 10, background: 'var(--edge)', padding: 12, position: 'relative', overflow: 'hidden', display: 'flex', flexDirection: 'column', justifyContent: 'center', gap: 8 }}>{children}</div>
      <h2 className="card-h3" style={{ margin: 0 }}>
        {title}
      </h2>
      <p className="muted" style={{ fontSize: 12, lineHeight: 1.5 }}>
        {note}
      </p>
    </article>
  );
}

/** What viewers see when things are loading, slow, wrong or out of scope (PRD 15.11). */
export function StatesGallery() {
  const cycle = useCycle(3600);
  const { reducedMotion } = usePrefs();
  // With reduced motion each demo rests on the frame that tells its story, rather than looping through empty ones.
  const stage = reducedMotion ? 2 : cycle % 3;
  const bubble = { alignSelf: 'flex-end', background: 'var(--surface-2)', borderRadius: '12px 12px 4px 12px', padding: '6px 10px', fontSize: 12 } as const;

  return (
    <div className="screen">
      <div className="container stack-lg">
        <header className="anim-rise">
          <Logo />
          <h1 className="display" style={{ fontSize: 56, lineHeight: 1, marginTop: 16 }}>
            System states
          </h1>
          <p className="muted" style={{ fontSize: 17, marginTop: 10, maxWidth: 900 }}>
            Every state says what is happening, what OffBall is doing about it, and what the viewer can do.
          </p>
        </header>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))', gap: 18 }}>
          <State title="Loading a match" note="The pitch's chalk draws itself in while three checks tick off in order. First frame in 2 s or less on broadband." delay={0}>
            <div key={reducedMotion ? 'rest' : Math.floor(cycle / 3)} style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
              <svg viewBox={VIEWBOX.h} aria-hidden="true" className="pitch-loading" style={{ width: 128, flex: 'none', filter: 'saturate(0.4) brightness(0.8)' }}>
                <PitchMarkings drawIn />
              </svg>
              <LoadChecks checks={['Feed connected', 'Space model ready', 'Agents joining']} stage={stage} className="load-checks-small" />
            </div>
          </State>

          <State title="Feed stall" note="After 2 s without data the picture freezes and dims. Late graphics are dropped, never shown out of sync." delay={60}>
            <div style={{ position: 'absolute', inset: 0, background: 'var(--pitch)', filter: 'saturate(0.4) brightness(0.7)' }} />
            <span className="map-chip" style={{ position: 'relative', alignSelf: 'center', borderRadius: 999, padding: '8px 12px' }}>
              <Spinner />
              Feed interrupted · holding the last frame
            </span>
          </State>

          <State title="Back in sync" note="A short, polite toast when the feed recovers, saying whether anything was missed." delay={120}>
            <div style={{ display: 'flex', justifyContent: 'center' }}>
              <ToastStack toasts={stage === 0 ? [] : [{ id: reducedMotion ? 'synced' : String(cycle), text: 'Back in sync. Nothing was missed.', tone: 'success' }]} />
            </div>
          </State>

          <State title="Quality step-down" note="Frame time over budget for 2 s steps down a tier. The viewer is told once, and can lock a tier." delay={180}>
            <div style={{ position: 'relative', display: 'flex', flexDirection: 'column', gap: 4 }}>
              <span
                aria-hidden="true"
                style={{ position: 'absolute', left: -6, top: -2, width: 120, height: 30, borderRadius: 8, boxShadow: 'inset 0 0 0 2px var(--space)', transition: 'transform var(--dur-smooth) var(--ease-standard)', transform: `translateY(${stage === 1 ? 34 : 0}px)` }}
              />
              {['A · WebGPU', 'B · WebGL2', 'C · Canvas', 'D · Video'].map((tier) => (
                <span key={tier} style={{ height: 30, display: 'flex', alignItems: 'center', fontSize: 12, fontWeight: 600 }}>
                  {tier}
                </span>
              ))}
            </div>
          </State>

          <State title="Video fallback" note="On devices that can’t draw live, clips play with overlays burned in and a live caption track." delay={240}>
            <div style={{ position: 'absolute', inset: 0, background: 'var(--pitch)' }} />
            <span className="map-chip" style={{ position: 'absolute', left: 10, top: 10, fontSize: 11 }}>
              Tier D · pre-rendered clip
            </span>
            <div style={{ position: 'absolute', left: 10, right: 10, bottom: 30, fontSize: 12, background: 'var(--chip-bg)', padding: '6px 8px', borderRadius: 6 }}>Watch No. 9. This run isn’t to get the ball.</div>
            <div className="meter" style={{ position: 'absolute', left: 10, right: 10, bottom: 14, height: 4 }}>
              <span key={cycle} className="meter-fill" style={{ width: '100%', background: 'var(--space)', animation: 'ob-grow 3.6s var(--ease-linear)' /* tokens-ok: the demo's cycle length */ }} />
            </div>
          </State>

          <State title="Correction" note="The old claim is struck through and replaced within 5 s, with a Correction tag that stays for 3 s." delay={300}>
            {stage > 0 && (
              <Chip tone="alert" className="anim-pop" style={{ position: 'absolute', right: 12, top: 12 }}>
                Correction
              </Chip>
            )}
            <div key={reducedMotion ? 'rest' : Math.floor(cycle / 3)} style={{ display: 'flex', flexDirection: 'column', gap: 6, fontSize: 14 }}>
              <span className={stage > 0 ? 'strike muted' : undefined} style={{ alignSelf: 'flex-start' }}>Goal for No. 7 at 41′.</span>
              {stage === 2 && <span className="anim-rise">Goal for No. 11 at 41′, after the feed’s correction.</span>}
            </div>
          </State>

          <State title="Couldn’t verify" note="The Pundit answers what it can prove and says plainly what it couldn’t check. Nothing unverified is presented as fact." delay={360}>
            <span style={{ fontSize: 12, lineHeight: 1.5 }}>No. 9 has made 7 off-ball runs today, the most in this match.</span>
            <span className="muted" style={{ fontSize: 12, lineHeight: 1.5, borderLeft: '2px dashed var(--muted)', paddingLeft: 8 }}>
              I couldn’t verify whether that’s a season record, so I’ve left it out.
            </span>
            <Chip tone="muted" style={{ alignSelf: 'flex-start' }}>
              1 claim unverified
            </Chip>
          </State>

          <State title="Out of scope" note="Declines briefly without lecturing, and offers the nearest useful thing it can do." delay={420}>
            <span style={bubble}>What are the odds Kestrel win?</span>
            <span style={{ fontSize: 12, lineHeight: 1.5 }}>OffBall doesn’t do odds or betting. I can show you who’s controlling space right now, if that helps.</span>
            <Chip tone="accent" style={{ alignSelf: 'flex-start' }}>
              Show space control
            </Chip>
          </State>

          <State title="Empty Ask OffBall" note="Never a blank box: three questions drawn from what just happened in the match." delay={480}>
            <span className="display" style={{ fontSize: 20, textAlign: 'center' }}>
              Ask about this match
            </span>
            {['Why did No. 5 follow?', 'Who made the most space?'].map((q, i) => (
              <Chip key={q} tone="outline" className="anim-pop" style={{ alignSelf: 'center', animationDelay: `${i * 120}ms` }}>
                {q}
              </Chip>
            ))}
          </State>

          <State title="Offline" note="The app keeps a short replay buffer, so losing the network never means a blank screen." delay={540}>
            <span className="cluster" style={{ gap: 8, fontSize: 13, fontWeight: 600 }}>
              <PulseDot color="var(--ash)" />
              You’re offline
            </span>
            <span className="muted" style={{ fontSize: 12, lineHeight: 1.5 }}>
              The last 10 minutes are saved on this device. Live moments will catch up when you reconnect.
            </span>
            <Chip tone="space" style={{ alignSelf: 'flex-start' }}>
              Watch the saved replay
            </Chip>
          </State>

          <State title="Live-run limit" note="When live runs hit the fair-use limit, viewers get a place in line and an instant alternative, never an error." delay={600}>
            <span style={{ fontSize: 13, fontWeight: 600 }}>Live runs are busy right now</span>
            <span className="muted" style={{ fontSize: 12, lineHeight: 1.5 }}>
              You’re 2nd in line, about 4 minutes. The showcase replay is ready now.
            </span>
            <div className="meter" style={{ height: 6 }}>
              <span key={cycle} className="meter-fill anim-grow" style={{ width: '70%', background: 'var(--kes)' }} />
            </div>
          </State>

          <State title="Reduced motion" note="Follows the system setting or the switch in Personalize. Every state above has a fade-only version." delay={660}>
            <svg viewBox="0 0 120 90" aria-hidden="true" style={{ width: 120, height: 90, alignSelf: 'center' }}>
              <ellipse key={cycle} className="anim-fade" cx={60} cy={45} rx={34} ry={28} style={{ fill: 'var(--space-fill)', stroke: 'var(--space)', strokeWidth: 3 }} />
            </svg>
          </State>
        </div>
      </div>
    </div>
  );
}
