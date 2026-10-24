import { Button, Logo, Segmented, Switch } from '../components/ui';
import { THEMES, usePrefs, type Theme } from '../lib/prefs';

export const SCREENS = [
  { route: 'match', name: 'Match view', desc: 'The match from the overlay feed, in 2D or from four 3D cameras: six modes, the control field with contours, “what if” overlaid or side by side, captions in ten languages with voice, replay controls, snapshots and keyboard shortcuts.' },
  { route: 'phone', name: 'Second screen', desc: 'The phone companion: pairs with a code or QR, follows the main screen’s clock, your player, and Ask OffBall by text or voice.' },
  { route: 'onboarding', name: 'First run', desc: 'Three quick choices and a summary, with a live preview drawn by the real renderer.' },
  { route: 'space-centre', name: 'Space Centre', desc: 'A ten-match whip-around that jumps to the biggest off-ball moment, with colour-checked kits.' },
  { route: 'broadcast', name: 'Broadcast output', desc: '1080p graphics on a broadcast camera view, with EBU R 95 safe areas and a key output.' },
  { route: 'recap', name: 'Recap', desc: 'Halftime and full-time recaps of the top space moments, the Space Created leaderboard, a shareable player card and the vertical clip, spoiler-safe on request.' },
  { route: 'producer', name: 'Producer console', desc: 'Approve, hold, skip or retract graphics that reach every view; trace any graphic; simulate a feed correction; build and publish recaps.' },
  { route: 'eval', name: 'Evaluation', desc: 'How we know it’s right: the synthetic data against real football, the models against what happened, the agents against OffBall-Bench, and frame times measured on your device.' },
  { route: 'components', name: 'Components', desc: 'Every component, live and interactive, with the file it lives in.' },
  { route: 'visual-language', name: 'Visual language', desc: 'Colour tokens for every theme, colour-vision and kit checks, field ramps, type and the overlay grammar.' },
  { route: 'motion', name: 'Motion', desc: 'Principles, duration and easing tokens, and a demo of every micro-interaction.' },
  { route: 'states', name: 'System states', desc: 'Loading, stalls, corrections, unverified answers, offline and more.' },
] as const;

const THEME_LABEL: Record<Theme, string> = { dark: 'Dark', light: 'Light', contrast: 'High contrast' };

export function Home() {
  const { prefs, update } = usePrefs();
  return (
    <div className="screen">
      <div className="container stack-lg">
        <header className="cluster anim-rise" style={{ justifyContent: 'space-between' }}>
          <Logo />
          <div className="cluster">
            <Segmented options={THEMES.map((t) => ({ value: t, label: THEME_LABEL[t] }))} value={prefs.theme} onChange={(theme) => update({ theme })} label="Theme" />
            <Switch checked={prefs.reducedMotion} onChange={(reducedMotion) => update({ reducedMotion })} label="Reduced motion" />
          </div>
        </header>
        <div className="anim-rise">
          <h1 className="display" style={{ fontSize: 'clamp(44px, 8vw, 64px)', lineHeight: 0.95 }}>
            OffBall UI
          </h1>
          <p className="muted" style={{ fontSize: 18, marginTop: 12, maxWidth: 760, lineHeight: 1.5 }}>
            Design tokens, components and screens for making space visible. Every screen reads the same contract feed for the same synthetic showcase match: Kestrel Bay’s 63rd-minute decoy-run goal against Ashmoor.
          </p>
          <div className="cluster" style={{ marginTop: 14 }}>
            <Button variant="ghost" className="btn-sm" onClick={() => update({ onboarded: false })} disabled={!prefs.onboarded}>
              {prefs.onboarded ? 'Show the first run again' : 'First run will show on the match view'}
            </Button>
          </div>
        </div>
        <nav aria-label="Screens" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: 14 }}>
          {SCREENS.map((s, i) => (
            <a key={s.route} href={`#/${s.route}`} className="screen-card anim-rise" style={{ animationDelay: `calc(var(--stagger) * ${i + 2})` }}>
              <span className="display" style={{ fontSize: 26 }}>
                {s.name}
              </span>
              <span className="muted" style={{ fontSize: 14, lineHeight: 1.5 }}>
                {s.desc}
              </span>
            </a>
          ))}
        </nav>
      </div>
    </div>
  );
}
