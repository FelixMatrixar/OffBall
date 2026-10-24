import { useState } from 'react';
import { PitchMarkings, VIEWBOX } from '../components/pitch';
import { Button, CaptionReveal, Chip, LiveBadge, Logo, PulseDot } from '../components/ui';
import { readToken } from '../lib/color';
import { MATCHDAY, type MatchdayGame } from '../lib/content';
import { useNow } from '../lib/hooks';
import { LEAGUE, checkFixture, type FixtureCheck } from '../lib/kits';

const TOP = 5;

/** Deterministic pseudo-random positions so each spotlight scene stays stable. */
const rnd = (i: number, k: number) => {
  const v = Math.sin(i * 12.9898 + k * 78.233) * 43758.5453;
  return v - Math.floor(v);
};

const name = (id: string) => LEAGUE[id]?.name ?? id;

function Spotlight({ game, index, clock, kits }: { game: MatchdayGame; index: number; clock: string; kits: FixtureCheck }) {
  const dots = Array.from({ length: 16 }, (_, i) => {
    const home = i < 8;
    return { x: home ? 380 + rnd(index, i) * 520 : 520 + rnd(index + 3, i) * 500, y: 60 + rnd(index + 7, i) * 560, home };
  });
  return (
    <div className="anim-slide-fwd" style={{ position: 'relative', display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div className="cluster" style={{ gap: 12 }}>
        <span className="card-label" style={{ color: 'var(--space-ink)' }}>
          BIGGEST MOMENT NOW
        </span>
        <span className="display" style={{ fontSize: 26 }}>
          {name(game.home)} <span className="tabular">{game.hs}–{game.as}</span> {name(game.away)}
        </span>
        <span className="mono muted" style={{ fontSize: 13 }}>
          {clock}
        </span>
        <Chip tone="accent" size="lg" className="spacer">
          {game.type}
        </Chip>
      </div>
      <svg viewBox={VIEWBOX.h} role="img" aria-label={`${name(game.home)} against ${name(game.away)}: ${game.text}`} style={{ width: '100%', height: 'auto', display: 'block', borderRadius: 12, direction: 'ltr' }}>
        <PitchMarkings />
        <ellipse className="ring-draw" pathLength={100} cx={game.gap[0]} cy={game.gap[1]} rx={62} ry={62} style={{ fill: 'var(--space-fill)', stroke: 'var(--space)', strokeWidth: 5, animationDelay: 'var(--dur-base), var(--dur-hero)' }} />
        <line className="line-draw" pathLength={100} x1={game.arrow[0]} y1={game.arrow[1]} x2={game.arrow[2]} y2={game.arrow[3]} style={{ stroke: kits.home.colour, strokeWidth: 7, strokeLinecap: 'round' }} />
        {dots.map((d, i) => (
          <g key={i} className="anim-pop" style={{ animationDelay: `calc(var(--stagger) * ${i / 2})` }}>
            <circle cx={d.x} cy={d.y} r={15} style={{ fill: d.home ? kits.home.colour : kits.away.colour, stroke: 'var(--halo)', strokeWidth: 3 }} />
            {!d.home && kits.away.pattern === 'hoops' && <circle cx={d.x} cy={d.y} r={9} style={{ fill: 'none', stroke: 'var(--halo)', strokeWidth: 3 }} />}
          </g>
        ))}
      </svg>
      <CaptionReveal text={game.text} startAfter={8} style={{ fontSize: 20, lineHeight: 1.4, fontWeight: 500 }} />
      <span className="sweep" aria-hidden="true" style={{ position: 'absolute', top: 0, bottom: 0, left: 0, width: '40%', background: 'linear-gradient(90deg, transparent, rgb(var(--space-rgb) / 0.08), transparent)', pointerEvents: 'none' }} />
    </div>
  );
}

/** A matchday whip-around that jumps to the biggest off-ball moment anywhere (PRD 10.7, 15.10). */
export function SpaceCentre() {
  // Re-renders every 100 ms, which also picks up a theme change for the kit check below.
  const now = useNow(100);
  const [mountedAt] = useState(() => Date.now());
  const [since, setSince] = useState(() => Date.now());
  const [pinned, setPinned] = useState<number | null>(null);
  const [tickerPaused, setTickerPaused] = useState(false);
  const jumpMs = 7000;

  // The clock's first reading can come a millisecond before `since` (and after a resume, until it next ticks); a
  // negative time would pick game −1, which doesn't exist.
  const elapsed = Math.max(0, now - since);
  const featured = pinned ?? Math.floor(elapsed / jumpMs) % TOP;
  const progress = pinned === null ? (elapsed % jumpMs) / jumpMs : 1;
  // The colour-vision kit check runs against this theme's pitch (PRD 16.3).
  const pitch = readToken('--pitch') || '#14301f';
  const kits = MATCHDAY.map((g) => checkFixture(g.home, g.away, pitch));

  const clock = (g: MatchdayGame) => {
    const sec = g.base + Math.floor((now - mountedAt) / 1000);
    return `${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, '0')}`;
  };
  const game = MATCHDAY[featured];
  const ticker = MATCHDAY.map((g) => `${clock(g)}  ${name(g.home)} v ${name(g.away)} · ${g.type}`);

  const togglePin = () => {
    if (pinned === null) setPinned(featured);
    else {
      setPinned(null);
      setSince(Date.now());
    }
  };

  return (
    <div className="screen" style={{ paddingBottom: 0, display: 'flex', flexDirection: 'column' }}>
      <div className="container stack" style={{ width: '100%', gap: 16, flex: 1 }}>
        <header className="cluster anim-rise" style={{ gap: '12px 20px' }}>
          <Logo href="#/match" />
          <h1 className="display muted" style={{ fontSize: 28, fontWeight: 600 }}>
            Space Centre · Round 27
          </h1>
          <LiveBadge label="10 LIVE" />
          <div className="cluster spacer">
            <span className="muted" style={{ fontSize: 13 }} role="status">
              {pinned === null ? 'Jumping to the biggest moment every 7 s' : 'Whip-around paused'}
            </span>
            <Button variant={pinned === null ? 'secondary' : 'primary'} aria-pressed={pinned !== null} onClick={togglePin}>
              <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
                <path d="M6 2 H10 L9.5 6.5 L12 9 H4 L6.5 6.5 Z M8 9 V14.5" style={{ fill: 'none', stroke: 'currentColor', strokeWidth: 1.6, strokeLinejoin: 'round', strokeLinecap: 'round' }} />
              </svg>
              {pinned === null ? 'Pin this match' : 'Pinned · tap to resume'}
            </Button>
          </div>
        </header>

        <div className="row row-stretch" style={{ gap: 18 }}>
          <section aria-label="Spotlight" aria-live="polite" className="grow card anim-rise" style={{ display: 'flex', flexDirection: 'column', gap: 12, position: 'relative', overflow: 'hidden' }}>
            <Spotlight key={featured} game={game} index={featured} clock={clock(game)} kits={kits[featured]} />
            <div aria-hidden="true" style={{ height: 4, borderRadius: 2, background: 'var(--surface-2)', overflow: 'hidden' }}>
              <div style={{ height: '100%', background: 'var(--space)', transformOrigin: 'left', transform: `scaleX(${progress.toFixed(3)})`, transition: 'transform var(--dur-quick) var(--ease-linear)' }} />
            </div>
          </section>

          <aside aria-label="Ranked moments" className="side card anim-rise">
            <h2 className="card-h3">Ranked by space value right now</h2>
            <ol style={{ listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexDirection: 'column', gap: 8 }}>
              {MATCHDAY.slice(0, TOP).map((g, i) => {
                const on = i === featured;
                return (
                  <li
                    key={g.home}
                    aria-current={on ? 'true' : undefined}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: 12,
                      padding: '10px 12px',
                      borderRadius: 12,
                      transition: 'background-color var(--dur-smooth), box-shadow var(--dur-smooth), transform var(--dur-smooth) var(--ease-pop)',
                      background: on ? 'var(--surface-2)' : 'transparent',
                      boxShadow: `inset 0 0 0 ${on ? '2px var(--space)' : '1px var(--line)'}`,
                      transform: on ? 'translateX(4px)' : 'none',
                    }}
                  >
                    <span className="display muted" style={{ fontSize: 22, width: 22 }}>
                      {i + 1}
                    </span>
                    <span style={{ flex: 1, minWidth: 0 }}>
                      <span style={{ display: 'block', fontSize: 14, fontWeight: 600 }}>
                        {name(g.home)} v {name(g.away)}
                      </span>
                      <span className="muted" style={{ display: 'block', fontSize: 12 }}>
                        {g.type} · {g.value} m²
                      </span>
                    </span>
                    <span className="meter" style={{ width: 64, height: 6 }} aria-hidden="true">
                      <span className="meter-fill" style={{ width: `${((g.value / 41) * 100).toFixed(0)}%`, background: on ? 'var(--space)' : 'var(--kes)', transition: 'background-color var(--dur-smooth)' }} />
                    </span>
                  </li>
                );
              })}
            </ol>
          </aside>
        </div>

        <section aria-label="All matches" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(250px, 1fr))', gap: 12 }}>
          {MATCHDAY.map((g, i) => {
            const on = i === featured;
            const heat = Math.min(1, 0.25 + 0.6 * Math.abs(Math.sin((now - mountedAt) / 2400 + i * 0.9)) * (g.value / 41 + 0.3));
            let spark = '';
            for (let k = 0; k <= 20; k++) spark += `${k * 10},${(15 - Math.sin(k / 2.2 + i) * 9 * rnd(i, 1) - Math.sin(k / 0.9 + i * 2) * 3).toFixed(1)} `;
            const kit = kits[i];
            return (
              <button key={g.home} type="button" aria-pressed={on} onClick={() => setPinned(i)} className="choice press anim-rise" style={{ gap: 6, padding: '12px 14px', borderRadius: 14, animationDelay: `calc(var(--stagger) * ${i})` }}>
                <span style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', width: '100%' }}>
                  <span className="mono muted" style={{ fontSize: 12 }}>
                    {clock(g)}
                  </span>
                  {i < TOP && <PulseDot />}
                </span>
                {[
                  [name(g.home), g.hs, kit.home.colour, 'plain'],
                  [name(g.away), g.as, kit.away.colour, kit.away.pattern],
                ].map(([team, score, color, pattern]) => (
                  <span key={String(team)} style={{ display: 'flex', alignItems: 'center', gap: 8, width: '100%', fontSize: 14, fontWeight: 600 }}>
                    <span style={{ width: 10, height: 10, borderRadius: 2, background: String(color), boxShadow: pattern === 'hoops' ? 'inset 0 0 0 2px var(--halo)' : undefined }} />
                    <span style={{ flex: 1 }}>{team}</span>
                    <span className="display" style={{ fontSize: 20 }}>
                      {score}
                    </span>
                  </span>
                ))}
                <svg viewBox="0 0 200 30" aria-hidden="true" style={{ width: '100%', height: 'auto', display: 'block', marginTop: 4 }}>
                  <line x1={0} y1={15} x2={200} y2={15} style={{ stroke: 'var(--line)', strokeWidth: 1 }} />
                  <polyline points={spark.trim()} style={{ fill: 'none', stroke: 'var(--kes)', strokeWidth: 2, strokeLinejoin: 'round' }} />
                </svg>
                <span className="muted" style={{ display: 'flex', alignItems: 'center', gap: 8, width: '100%', fontSize: 11 }}>
                  Space heat
                  <span className="meter" style={{ flex: 1, height: 5 }}>
                    <span className="meter-fill" style={{ width: '100%', transform: `scaleX(${heat.toFixed(2)})`, background: 'var(--space)', transition: 'transform var(--dur-slide) var(--ease-linear)' }} />
                  </span>
                </span>
              </button>
            );
          })}
        </section>
      </div>

      <section className={`ticker-wrap ${tickerPaused ? 'ticker-paused' : ''}`} aria-label="Moments ticker" style={{ margin: '18px -24px 0', borderTop: '1px solid var(--line)', background: 'var(--surface)', overflow: 'hidden', height: 48, display: 'flex', alignItems: 'center', gap: 8 }}>
        <button type="button" className="btn btn-ghost btn-sm press" aria-pressed={tickerPaused} onClick={() => setTickerPaused((p) => !p)} style={{ marginInlineStart: 12, flex: 'none' }}>
          {tickerPaused ? 'Play ticker' : 'Pause ticker'}
        </button>
        <div style={{ overflow: 'hidden', flex: 1 }}>
          <div className="ticker">
            {[...ticker, ...ticker].map((line, i) => (
              <span key={i} aria-hidden={i >= ticker.length ? true : undefined} style={{ display: 'inline-flex', alignItems: 'center', gap: 10, padding: '0 22px', fontSize: 13, whiteSpace: 'nowrap' }}>
                <span style={{ width: 6, height: 6, borderRadius: 3, background: 'var(--space)' }} />
                {line}
              </span>
            ))}
          </div>
        </div>
      </section>
    </div>
  );
}
