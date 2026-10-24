import { useEffect, useState, type CSSProperties, type ReactNode } from 'react';
import { AgentTrace } from '../components/charts';
import { Ball, GapRing, GoalBurst, PlayerDot, RunArrow } from '../components/pitch';
import { CaptionReveal, CountUp, Logo, PulseDot, Segmented, Skeleton, Stepper, Switch, ToastStack, VerifiedChip, LiveBadge } from '../components/ui';
import { useCycle } from '../lib/hooks';

const DURATIONS = [
  { token: 'press', ms: 80, use: 'Button press, scaling to 96%' },
  { token: 'quick', ms: 150, use: 'Hover, colour changes and exits' },
  { token: 'base', ms: 220, use: 'Switches, chips and small entrances' },
  { token: 'smooth', ms: 340, use: 'Mode pill, panels, drawers and toasts' },
  { token: 'draw', ms: 600, use: 'Rings and arrows drawing on the pitch' },
  { token: 'hero', ms: 900, use: 'Goal burst and count-ups, once per event' },
];

const EASINGS = [
  { token: 'standard', curve: [0.2, 0, 0, 1], use: 'Anything entering or moving into place' },
  { token: 'exit', curve: [0.3, 0, 1, 1], use: 'Anything leaving' },
  { token: 'pop', curve: [0.34, 1.56, 0.64, 1], use: 'Chips, checks, switches and tags: a small overshoot' },
] as const;

const curvePath = ([x1, y1, x2, y2]: readonly number[]) => `M0 100 C${x1 * 100} ${100 - y1 * 100} ${x2 * 100} ${100 - y2 * 100} 100 0`;

/** Moves a dot across and back with the given easing token, so the curve can be felt. */
function EasingDemo({ token }: { token: string }) {
  const tick = useCycle(1600);
  const at = tick % 2 === 1;
  return (
    <div style={{ position: 'relative', height: 16, borderRadius: 8, background: 'var(--surface-2)', width: 230 }} dir="ltr">
      <span
        style={{
          position: 'absolute',
          top: 2,
          left: 2,
          width: 12,
          height: 12,
          borderRadius: 6,
          background: 'var(--space)',
          transform: `translateX(${at ? 212 : 0}px)`,
          transition: `transform var(--dur-hero) var(--ease-${token})`,
        }}
      />
    </div>
  );
}

const PRINCIPLES = [
  ['Explain, don’t decorate', 'Every animation answers “what changed?” or “why?”.'],
  ['Faster than the play', 'Interface motion finishes within 340 ms, so it never lags the match. Only drawing on the pitch takes longer.'],
  ['One thing at a time', 'On the pitch, one overlay enters at a time and everything else holds still, so the eye knows where to go.'],
  ['Reduced motion is a mode', 'It is designed, not switched off: fades instead of movement, steady dots instead of pulses.'],
] as const;

function Demo({ title, spec, children }: { title: string; spec: string; children: ReactNode }) {
  return (
    <div className="card" style={{ padding: 14 }}>
      <div style={{ height: 120, display: 'flex', alignItems: 'center', justifyContent: 'center', overflow: 'hidden', borderRadius: 10 }}>{children}</div>
      <div style={{ fontWeight: 700, fontSize: 14, marginTop: 8 }}>{title}</div>
      <div className="muted" style={{ fontSize: 12, lineHeight: 1.45 }}>
        {spec}
      </div>
    </div>
  );
}

const MiniPitch = ({ children }: { children: ReactNode }) => (
  <svg viewBox="600 100 500 360" aria-hidden="true" style={{ width: '100%', height: '100%', display: 'block', background: 'var(--pitch)' }}>
    {children}
  </svg>
);

/** The motion system with a live, looping demo of each micro-interaction (PRD 16.10). */
const DEMO_MODES = ['Casual', 'Analyst', 'Audio'] as const;
type DemoMode = (typeof DEMO_MODES)[number];

export function MotionGallery() {
  const cycle = useCycle(3200);
  const [mode, setMode] = useState<DemoMode>('Casual');
  const [on, setOn] = useState(false);
  const step = cycle % 5;
  const loading = cycle % 2 === 0;

  // The demos advance on their own; viewers can still click them in between.
  useEffect(() => {
    setMode(DEMO_MODES[cycle % DEMO_MODES.length]);
    setOn(cycle % 2 === 1);
  }, [cycle]);

  return (
    <div className="screen">
      <div className="container stack-lg">
        <header className="anim-rise">
          <Logo />
          <h1 className="display" style={{ fontSize: 56, lineHeight: 1, marginTop: 16 }}>
            Motion and micro-interactions
          </h1>
          <p className="muted" style={{ fontSize: 17, marginTop: 10, maxWidth: 900 }}>
            Motion shows cause and change. If removing it loses no meaning, remove it. The demos here loop so you can feel each timing; in the product, only live indicators loop.
          </p>
        </header>

        <section aria-label="Principles" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(240px, 1fr))', gap: 14 }}>
          {PRINCIPLES.map(([title, text], i) => (
            <div key={title} className="card anim-rise" style={{ padding: 16, animationDelay: `calc(var(--stagger) * ${i})` }}>
              <h2 className="display" style={{ fontSize: 22, marginBottom: 6 }}>
                {title}
              </h2>
              <p className="muted" style={{ fontSize: 14, lineHeight: 1.5 }}>
                {text}
              </p>
            </div>
          ))}
        </section>

        <div className="row row-stretch" style={{ gap: 20 }}>
          <section className="card grow" style={{ flexBasis: 520 }}>
            <h2 className="card-title">Duration tokens</h2>
            <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexDirection: 'column', gap: 12 }}>
              {DURATIONS.map((d) => (
                <li key={d.token} style={{ display: 'grid', gridTemplateColumns: '90px 70px minmax(0, 1fr)', alignItems: 'center', gap: 12 }}>
                  <span className="mono" style={{ fontSize: 13 }}>
                    {d.token}
                  </span>
                  <span className="mono muted" style={{ fontSize: 13 }}>
                    {d.ms} ms
                  </span>
                  <span className="meter">
                    <span key={cycle} className="meter-fill" style={{ width: `${(d.ms / 900) * 100}%`, background: 'var(--space)', animation: `ob-grow ${d.ms}ms var(--ease-standard) backwards` }} />
                  </span>
                  <span className="muted" style={{ gridColumn: '1 / -1', fontSize: 12, marginTop: -6 }}>
                    {d.use}
                  </span>
                </li>
              ))}
            </ul>
          </section>

          <section className="card grow" style={{ flexBasis: 520 }}>
            <h2 className="card-title">Easing tokens</h2>
            <div className="stack" style={{ gap: 16 }}>
              {EASINGS.map((e) => (
                <div key={e.token} style={{ display: 'grid', gridTemplateColumns: '96px minmax(0, 1fr)', gap: 16, alignItems: 'center' }}>
                  <svg viewBox="-6 -64 112 176" aria-hidden="true" style={{ width: 96, height: 'auto' }}>
                    <rect x={0} y={0} width={100} height={100} style={{ fill: 'none', stroke: 'var(--line)' }} />
                    <path d={curvePath(e.curve)} style={{ fill: 'none', stroke: 'var(--space)', strokeWidth: 3, strokeLinecap: 'round' }} />
                  </svg>
                  <div>
                    <div className="mono" style={{ fontSize: 13 }}>
                      {e.token} · <span className="muted">cubic-bezier({e.curve.join(', ')})</span>
                    </div>
                    <div className="muted" style={{ fontSize: 12, margin: '4px 0 10px' }}>
                      {e.use}
                    </div>
                    <EasingDemo token={e.token} />
                  </div>
                </div>
              ))}
            </div>
          </section>
        </div>

        <section>
          <h2 className="card-title">Micro-interaction catalogue</h2>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))', gap: 14 }}>
            <Demo title="Mode switch" spec="The pill slides under the chosen mode in 340 ms; panel cards rise in behind it.">
              <Segmented options={DEMO_MODES.map((m) => ({ value: m, label: m }))} value={mode} onChange={setMode} label="Demo mode" />
            </Demo>
            <Demo title="Caption reveal" spec="Each word rises 8 px and unblurs. 35 ms stagger, capped at 700 ms.">
              <CaptionReveal key={cycle} text="Watch No. 9. This run pulls a defender away." style={{ fontSize: 16, fontWeight: 500, padding: '0 6px' }} />
            </Demo>
            <Demo title="Gap ring" spec="The stroke draws in 600 ms, then pulses once. Lime only ever means space.">
              <MiniPitch>
                <GapRing key={cycle} at={[88.5, 40]} />
              </MiniPitch>
            </Demo>
            <Demo title="Run arrow" spec="Draws about 0.8 s ahead of the runner, so you see where the run is going.">
              <MiniPitch>
                <RunArrow key={cycle} from={[84, 34]} runner={[87.5, 43.5]} ahead={[91, 53]} />
              </MiniPitch>
            </Demo>
            <Demo title="Player hover" spec="The dot grows to 132% in 150 ms and the name appears. Players never move on hover. Hover or tab to it.">
              <svg viewBox="600 100 500 360" role="group" aria-label="Player hover demo" style={{ width: '100%', height: '100%', display: 'block', background: 'var(--pitch)' }}>
                <PlayerDot at={[85, 30]} team="kes" num={9} label="Kestrel Bay No. 9, J. Velmar" hint="No. 9 Velmar · 27.3 km/h" tabIndex={0} />
              </svg>
            </Demo>
            <Demo title="Spotlight jump" spec="Space Centre: the new match slides in over 500 ms with a soft lime sweep; a bar counts down to the next jump.">
              <div key={cycle} className="anim-slide-fwd" style={{ position: 'relative', overflow: 'hidden', width: '86%', borderRadius: 10, background: 'var(--surface-2)', padding: '14px 16px' }}>
                <div className="display" style={{ fontSize: 20 }}>
                  Brackenford 2–1 Saltmere
                </div>
                <div className="muted" style={{ fontSize: 12 }}>
                  Overlap · 33 m²
                </div>
                <div className="meter" style={{ height: 4, marginTop: 10 }} aria-hidden="true">
                  <span className="meter-fill" style={{ width: '100%', background: 'var(--space)', animation: 'ob-grow 3.2s var(--ease-linear) both' /* tokens-ok: the demo's cycle length */ }} />
                </div>
                <span className="sweep" aria-hidden="true" style={{ position: 'absolute', inset: 0, width: '40%', background: 'linear-gradient(90deg, transparent, rgb(var(--space-rgb) / 0.12), transparent)', pointerEvents: 'none' }} />
              </div>
            </Demo>
            <Demo title="Verified chip" spec="Pops with a slight overshoot, then the check draws in 450 ms.">
              <span key={cycle}>
                <VerifiedChip />
              </span>
            </Demo>
            <Demo title="Count-up" spec="New numbers roll up from zero over 900 ms. Numbers already on screen update in place.">
              <span className="display" style={{ fontSize: 44 }}>
                <CountUp key={cycle} value={41} suffix=" m²" />
              </span>
            </Demo>
            <Demo title="Goal burst" spec="Fourteen particles from the ball, 900 ms, once per goal. The only celebration. With reduced motion, one ring fades in instead.">
              <MiniPitch>
                <GoalBurst key={cycle} at={[95, 40]} />
                <Ball at={[95, 40]} />
              </MiniPitch>
            </Demo>
            <Demo title="Switch" spec="The knob slides with a small overshoot (260 ms); the track colour fades (220 ms).">
              <Switch checked={on} onChange={setOn} label="What if no run?" />
            </Demo>
            <Demo title="Toast" spec="Rises with an overshoot in 340 ms, holds 3.5 s, fades in 150 ms. Announced politely.">
              <ToastStack toasts={loading ? [] : [{ id: String(cycle), text: 'Switched to Tier B to hold 60 fps', tone: 'info' }]} />
            </Demo>
            <Demo title="Skeleton to content" spec="A shimmer holds the space while the Tactician re-runs the moment; content rises in when ready.">
              {loading ? (
                <div style={{ width: '80%', display: 'flex', flexDirection: 'column', gap: 8 }}>
                  <Skeleton width="70%" height={12} />
                  <Skeleton width="45%" height={26} />
                </div>
              ) : (
                <div key={cycle} className="anim-rise" style={{ width: '80%' }}>
                  <div className="muted" style={{ fontSize: 12 }}>
                    Space created by No. 9
                  </div>
                  <div className="display" style={{ fontSize: 30 }}>
                    41 m²
                  </div>
                </div>
              )}
            </Demo>
            <Demo title="Live indicators" spec="The only loops: live, listening, paired and on-air. 1.4–1.6 s, low contrast.">
              <span className="cluster" style={{ gap: 24 }}>
                <PulseDot size={14} />
                <LiveBadge />
              </span>
            </Demo>
            <Demo title="Stepper" spec="The line fills in 500 ms and the next step grows to 115% with an overshoot.">
              <div style={{ transform: 'scale(0.8)' }}>
                <Stepper steps={['Watch', 'Club', 'Language', 'Ready']} current={step % 4} />
              </div>
            </Demo>
            <Demo title="Agent trace" spec="Bars grow in the order the agents ran, at true proportions. A rejection shakes once.">
              <div style={{ width: '100%', transform: 'scale(0.82)', transformOrigin: 'center' }}>
                <AgentTrace
                  key={cycle}
                  rows={[
                    { agent: 'Scout', start: 0, end: 0.3 },
                    { agent: 'Explainer', start: 0.3, end: 1.2 },
                    { agent: 'Fact-checker', start: 1.2, end: 1.6, kind: 'rejected' },
                  ]}
                  budget={2}
                  compact
                />
              </div>
            </Demo>
            <Demo title="Reduced motion" spec="The same chip with reduced motion: a short fade, no scale, no drawing.">
              <span key={cycle} className="chip chip-space chip-lg anim-fade">
                Verified
              </span>
            </Demo>
          </div>
        </section>

        <section className="card">
          <h2 className="card-title">Rules</h2>
          <ul style={{ margin: 0, paddingLeft: 18, display: 'flex', flexDirection: 'column', gap: 6, fontSize: 15, lineHeight: 1.5 } as CSSProperties}>
            <li>Only live indicators loop. Nothing else repeats.</li>
            <li>Movement on the pitch follows the match clock; interface motion never delays it.</li>
            <li>Numbers already on screen update in place; only new numbers count up.</li>
            <li>On the pitch, nothing bounces except a gap ring’s single pulse.</li>
            <li>Animations change only transform and opacity, so they stay inside the frame budget.</li>
            <li>With reduced motion, changes are instant or fade; player and ball movement stays, because it is the match itself.</li>
          </ul>
        </section>
      </div>
    </div>
  );
}
