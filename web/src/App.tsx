import { useEffect, useState, useSyncExternalStore, type ComponentType } from 'react';
import { Button, ErrorBoundary } from './components/ui';
import { pwaUpdate } from './lib/pwa';
import { usePrefs } from './lib/prefs';
import { BroadcastOutput } from './screens/BroadcastOutput';
import { ClipView } from './screens/ClipView';
import { EvalView } from './screens/EvalView';
import { RecapView } from './screens/RecapView';
import { ComponentGallery } from './screens/ComponentGallery';
import { Home, SCREENS } from './screens/Home';
import { MatchView } from './screens/MatchView';
import { MotionGallery } from './screens/MotionGallery';
import { Onboarding } from './screens/Onboarding';
import { PhoneCompanion } from './screens/PhoneCompanion';
import { ProducerConsole } from './screens/ProducerConsole';
import { SpaceCentre } from './screens/SpaceCentre';
import { StatesGallery } from './screens/StatesGallery';
import { VisualLanguage } from './screens/VisualLanguage';

const ROUTES: Record<string, ComponentType> = {
  match: MatchView,
  phone: PhoneCompanion,
  onboarding: Onboarding,
  'space-centre': SpaceCentre,
  broadcast: BroadcastOutput,
  producer: ProducerConsole,
  components: ComponentGallery,
  'visual-language': VisualLanguage,
  motion: MotionGallery,
  states: StatesGallery,
  recap: RecapView,
  eval: EvalView,
  clip: ClipView,
};

/** Routes that are outputs rather than screens: no screen switcher over them. */
const OUTPUTS = new Set(['clip']);

/** The route is the hash path; anything after "?" is that screen's options. */
const routeFromHash = () => window.location.hash.replace(/^#\/?/, '').split('?')[0];
const queryFromHash = () => new URLSearchParams(window.location.hash.split('?')[1] ?? '');

function useRoute(): string {
  const [route, setRoute] = useState(routeFromHash);
  useEffect(() => {
    const onChange = () => {
      const next = routeFromHash();
      setRoute((prev) => {
        if (prev !== next) window.scrollTo(0, 0);
        return next;
      });
    };
    window.addEventListener('hashchange', onChange);
    return () => window.removeEventListener('hashchange', onChange);
  }, []);
  return route;
}

/** Every screen, one step away, for reviewing the prototype: a footer in the page's flow, never over its content. */
function ScreenSwitcher({ route }: { route: string }) {
  return (
    <nav className="dev-nav" aria-label="Screens">
      <a href="#/" className="btn btn-ghost btn-sm press">
        All screens
      </a>
      <label htmlFor="screen-switch">Go to</label>
      <select id="screen-switch" className="select select-sm" value={route} onChange={(e) => (window.location.hash = `/${e.target.value}`)}>
        {SCREENS.map((s) => (
          <option key={s.route} value={s.route}>
            {s.name}
          </option>
        ))}
      </select>
    </nav>
  );
}

/** A new version has installed: offered, never forced (PRD 15.11: every state says what the viewer can do). */
function UpdatePrompt() {
  const waiting = useSyncExternalStore(pwaUpdate.subscribe, pwaUpdate.get);
  if (!waiting) return null;
  return (
    <div className="update-prompt card anim-rise" role="status">
      <span>A new version of OffBall is ready.</span>
      <Button variant="primary" className="btn-sm" onClick={pwaUpdate.apply}>
        Reload
      </Button>
    </div>
  );
}

export function App() {
  const route = useRoute();
  const { prefs } = usePrefs();
  // First run (PRD 15.8): a first visit to the match goes through the choices, unless it's a deep link for a test or preview.
  const deepLink = ['t', 'state', 'feed', 'pair'].some((k) => queryFromHash().has(k));
  const firstRun = route === 'match' && !prefs.onboarded && !deepLink;
  useEffect(() => {
    if (firstRun) window.location.replace('#/onboarding');
  }, [firstRun]);
  const Screen = firstRun ? Onboarding : (ROUTES[route] ?? Home);
  return (
    <>
      <ErrorBoundary key={route} label="This screen">
        <Screen />
      </ErrorBoundary>
      {ROUTES[route] && !OUTPUTS.has(route) && <ScreenSwitcher route={route} />}
      {!OUTPUTS.has(route) && <UpdatePrompt />}
    </>
  );
}
