import { useLayoutEffect, useState, type ReactNode } from 'react';
import { Ball, BackLine, GapRing, Ghost, PassLine, PlayerDot, RunArrow, Tag } from '../components/pitch';
import { Chip, Logo, Segmented } from '../components/ui';
import { VISIONS, contrast, deltaE, parseColor, simulate, luminance, type Vision } from '../lib/color';
import { MATCHDAY } from '../lib/content';
import { LEAGUE, MIN_DELTA, checkFixture } from '../lib/kits';
import type { Theme } from '../lib/prefs';

// The swatches and the colour-vision check (VIS-5) read each theme's live token values, so this page always shows
// what tokens.css says.
const SWATCHES: readonly (readonly [name: string, token: string])[] = [
  ['Ground', '--bg'],
  ['Surface', '--surface'],
  ['Line', '--line'],
  ['Text', '--text'],
  ['Muted text', '--muted'],
  ['Pitch', '--pitch'],
  ['Kestrel Bay', '--kes'],
  ['Ashmoor', '--ash'],
  ['Space', '--space'],
];
const THEMES: readonly Theme[] = ['dark', 'light', 'contrast'];
const THEME_LABEL: Record<Theme, string> = { dark: 'Dark · default, broadcast', light: 'Light', contrast: 'High contrast' };
const VISION_LABEL: Record<Vision, string> = { typical: 'Typical vision', deuteranopia: 'Deuteranopia', protanopia: 'Protanopia', tritanopia: 'Tritanopia' };

type Palettes = Record<Theme, Record<string, string>>;

/** Every theme's swatch values, read from a probe element scoped to each theme. */
function usePalettes(): Palettes | null {
  const [palettes, setPalettes] = useState<Palettes | null>(null);
  useLayoutEffect(() => {
    const out = {} as Palettes;
    for (const theme of THEMES) {
      const probe = document.createElement('div');
      probe.dataset.theme = theme;
      probe.hidden = true;
      document.body.append(probe);
      const cs = getComputedStyle(probe);
      out[theme] = Object.fromEntries(SWATCHES.map(([, token]) => [token, cs.getPropertyValue(token).trim()]));
      probe.remove();
    }
    setPalettes(out);
  }, []);
  return palettes;
}
const rgb = (c: number[]) => `rgb(${c.join(',')})`;

function Section({ title, children, note }: { title: string; children: ReactNode; note?: string }) {
  return (
    <section className="card anim-rise">
      <h2 className="card-title">{title}</h2>
      {note && (
        <p className="muted" style={{ fontSize: 13, marginTop: -6, marginBottom: 14 }}>
          {note}
        </p>
      )}
      {children}
    </section>
  );
}

function Grammar({ name, rule, children, viewBox = '760 160 340 260' }: { name: string; rule: string; children: ReactNode; viewBox?: string }) {
  return (
    <div className="card" style={{ padding: 12 }}>
      <div className="mono" style={{ fontSize: 13, marginBottom: 8 }}>
        {name}
      </div>
      <svg viewBox={viewBox} aria-hidden="true" style={{ width: '100%', height: 140, display: 'block', borderRadius: 8, background: 'var(--pitch)' }}>
        {children}
      </svg>
      <p className="muted" style={{ fontSize: 12, lineHeight: 1.45, marginTop: 8 }}>
        {rule}
      </p>
    </div>
  );
}

/** Colour, type, field ramps, the colour-vision and kit checks, and the overlay grammar (PRD 16.3), drawn with the real components. */
export function VisualLanguage() {
  const [theme, setTheme] = useState<Theme>('dark');
  const palettes = usePalettes();
  if (!palettes) return null;
  const pick = (t: Theme, token: string) => palettes[t][token];
  const pitch = pick(theme, '--pitch');
  const teams = [pick(theme, '--kes'), pick(theme, '--ash'), pick(theme, '--space')].map(parseColor);
  return (
    <div className="screen">
      <div className="container stack-lg">
        <header className="anim-rise">
          <Logo />
          <h1 className="display" style={{ fontSize: 56, lineHeight: 1, marginTop: 16 }}>
            Visual language
          </h1>
          <p className="muted" style={{ fontSize: 17, marginTop: 10, maxWidth: 880 }}>
            One grammar for every surface. Colour is never the only cue, lime always means space, and every visual has a text equivalent.
          </p>
        </header>

        <Section title="Colour tokens" note="Each theme is a token set; components never use raw colours.">
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(240px, 1fr))', gap: 18 }}>
            {THEMES.map((t) => (
              <div key={t}>
                <h3 className="card-h3 muted">{THEME_LABEL[t]}</h3>
                <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexDirection: 'column', gap: 6 }}>
                  {SWATCHES.map(([name, token]) => (
                    <li key={name} style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: 13 }}>
                      <span style={{ width: 28, height: 28, borderRadius: 6, background: pick(t, token), border: '1px solid var(--line)', flex: 'none' }} />
                      <span style={{ flex: 1 }}>{name}</span>
                      <span className="mono muted" style={{ fontSize: 12 }} title={token}>
                        {pick(t, token).toUpperCase()}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </Section>

        <Section title="Colour-vision check, every theme" note="VIS-5: the team pair must stay apart under every simulated vision, in every theme. Distance is in OKLab; 0.1 or more passes.">
          <Segmented options={THEMES.map((t) => ({ value: t, label: THEME_LABEL[t].split(' · ')[0] }))} value={theme} onChange={setTheme} label="Theme to check" />
          <ul style={{ listStyle: 'none', margin: '14px 0 0', padding: 0, display: 'flex', flexDirection: 'column', gap: 8 }}>
            {VISIONS.map((v) => {
              const sim = teams.map((c) => simulate(c, v));
              const d = deltaE(sim[0], sim[1]);
              return (
                <li key={v} style={{ display: 'grid', gridTemplateColumns: '130px minmax(0, 1fr) auto', alignItems: 'center', gap: 12 }}>
                  <span style={{ fontSize: 13, fontWeight: 600 }}>{VISION_LABEL[v]}</span>
                  <span style={{ display: 'flex', alignItems: 'center', gap: 18, background: rgb(simulate(parseColor(pitch), v)), borderRadius: 8, padding: '8px 14px' }}>
                    {sim.map((c, i) => (
                      <span key={i} style={{ width: 26, height: 26, borderRadius: 13, background: rgb(c), boxShadow: '0 0 0 2px var(--halo)' }} />
                    ))}
                  </span>
                  <Chip tone={d >= MIN_DELTA ? 'space' : 'danger'}>
                    ΔE {d.toFixed(2)} {d >= MIN_DELTA ? 'pass' : 'fail'}
                  </Chip>
                </li>
              );
            })}
          </ul>
          <p className="muted" style={{ fontSize: 12, marginTop: 12 }}>
            Dots, left to right: Kestrel Bay, Ashmoor, space. Greyscale luminance {teams.map((c) => luminance(c).toFixed(2)).join(' · ')}; team contrast against the pitch {contrast(teams[0], parseColor(pitch)).toFixed(1)}:1 and {contrast(teams[1], parseColor(pitch)).toFixed(1)}:1.
          </p>
        </Section>

        <Section title="Kit check · Round 27" note="For each fixture the away team switches to its alternate kit when the colours clash under any vision, and gets a pattern if that clashes too (PRD 16.3). Checked against this theme’s pitch.">
          <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: 10 }}>
            {MATCHDAY.map((g) => {
              const r = checkFixture(g.home, g.away, pitch);
              return (
                <li key={g.home} className="tile" style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  <svg width="58" height="28" viewBox="0 0 58 28" aria-hidden="true" style={{ flex: 'none' }}>
                    <rect width="58" height="28" rx="6" style={{ fill: pitch }} />
                    <circle cx="16" cy="14" r="9" style={{ fill: r.home.colour, stroke: 'var(--halo)', strokeWidth: 2 }} />
                    <circle cx="42" cy="14" r="9" style={{ fill: r.away.colour, stroke: 'var(--halo)', strokeWidth: 2 }} />
                    {r.away.pattern === 'hoops' && <circle cx="42" cy="14" r="5" style={{ fill: 'none', stroke: 'var(--halo)', strokeWidth: 2 }} />}
                  </svg>
                  <span style={{ flex: 1, minWidth: 0, fontSize: 13 }}>
                    <strong>
                      {LEAGUE[g.home].short} v {LEAGUE[g.away].short}
                    </strong>
                    <span className="muted" style={{ display: 'block', fontSize: 12 }}>
                      ΔE {r.minDelta.toFixed(2)} at worst ({VISION_LABEL[r.worst].toLowerCase()})
                    </span>
                  </span>
                  <Chip tone={r.decision === 'primary' ? 'outline' : 'accent'}>{r.decision}</Chip>
                </li>
              );
            })}
          </ul>
        </Section>

        <div className="row row-stretch">
          <div className="grow" style={{ flexBasis: 520 }}>
            <Section title="Field ramps">
              <h3 className="card-h3">Space control · diverging, neutral midpoint, with contours</h3>
              <div style={{ position: 'relative', display: 'flex', height: 40, borderRadius: 8, overflow: 'hidden', background: 'var(--pitch)' }} dir="ltr">
                {Array.from({ length: 21 }, (_, i) => {
                  const p = i / 20;
                  const a = (Math.abs(p - 0.5) * 2).toFixed(2);
                  return <span key={i} style={{ flex: 1, backgroundColor: `rgb(${p >= 0.5 ? 'var(--kes-rgb)' : 'var(--ash-rgb)'} / calc(var(--field-max) * ${a}))` }} />;
                })}
                {[0.25, 0.5, 0.75].map((l) => (
                  <span key={l} aria-hidden="true" style={{ position: 'absolute', top: 0, bottom: 0, left: `${l * 100}%`, width: 0, borderLeft: `${l === 0.5 ? 2 : 1.5}px ${l === 0.5 ? 'solid' : 'dashed'} var(--contour)` }} />
                ))}
              </div>
              <div className="muted" style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, margin: '6px 0 18px' }} dir="ltr">
                <span>Ashmoor controls</span>
                <span>Contour lines at 25 · 50 · 75%</span>
                <span>Kestrel controls</span>
              </div>
              <h3 className="card-h3">Space value · sequential, one hue</h3>
              <div style={{ display: 'flex', height: 40, borderRadius: 8, overflow: 'hidden', background: 'var(--pitch)' }} dir="ltr">
                {Array.from({ length: 11 }, (_, i) => (
                  <span key={i} style={{ flex: 1, background: `rgb(var(--space-rgb) / ${((i / 10) * 0.6).toFixed(2)})` }} />
                ))}
              </div>
              <div className="muted" style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, marginTop: 6 }} dir="ltr">
                <span>Low value</span>
                <span>High value · near goal</span>
              </div>
            </Section>
          </div>
          <div className="grow" style={{ flexBasis: 520 }}>
            <Section title="Type">
              <div className="stack" style={{ gap: 16 }}>
                <div>
                  <div className="muted" style={{ fontSize: 12 }}>
                    Barlow Condensed · scores, headings, big numbers · tabular figures
                  </div>
                  <div className="display tabular" style={{ fontSize: 48, lineHeight: 1 }}>
                    KES 1–0 ASH · 63:04 · 10.8 m
                  </div>
                </div>
                <div>
                  <div className="muted" style={{ fontSize: 12 }}>
                    Inter · captions, UI, audio-description transcripts
                  </div>
                  <div style={{ fontSize: 22, fontWeight: 500, lineHeight: 1.35 }}>Watch No. 9. This run isn’t to get the ball. It’s to pull a defender away.</div>
                </div>
                <div>
                  <div className="muted" style={{ fontSize: 12 }}>
                    JetBrains Mono · evidence IDs, the overlay feed, flags
                  </div>
                  <div className="mono" style={{ fontSize: 17 }}>
                    m07-e0912 · overlay.upsert gap_ring
                  </div>
                </div>
              </div>
            </Section>
          </div>
        </div>

        <section>
          <h2 className="card-title">Overlay grammar</h2>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(240px, 1fr))', gap: 14 }}>
            <Grammar name="gap_ring" rule="Lime only ever means space. One ring at a time; it draws itself and pulses once.">
              <GapRing at={[93, 33]} label="Space opens here" />
            </Grammar>
            <Grammar name="run_arrow" rule="Solid behind the runner is the run so far; dashed ahead is where it’s going, drawn about 0.8 s ahead.">
              <RunArrow from={[84, 18]} runner={[92, 27]} ahead={[100, 36]} />
              <PlayerDot at={[92, 27]} team="kes" num={9} label="Kestrel Bay No. 9" />
            </Grammar>
            <Grammar name="pass_line" rule="Line weight carries pass difficulty; dashed ahead of the ball.">
              <PassLine from={[80, 30]} ball={[90, 30]} to={[104, 30]} difficulty={8} />
              <Ball at={[90, 30]} />
            </Grammar>
            <Grammar name="ghost" rule="Where a player would have been: a dashed, translucent outline, always labelled.">
              <Ghost at={[86, 26]} team="kes" label="without the run" />
              <PlayerDot at={[100, 40]} team="kes" num={9} label="Kestrel Bay No. 9" />
            </Grammar>
            <Grammar name="player_tag" rule="Text on a halo, so it reads over any field colour, placed clear of other labels and players.">
              <PlayerDot at={[93, 28]} team="kes" num={9} label="Kestrel Bay No. 9" />
              <Tag x={930} y={374} text="No. 9 Velmar" />
            </Grammar>
            <Grammar name="badge" rule="Threshold badges: sprints above 25.2 km/h and each kilometre covered.">
              <PlayerDot at={[93, 34]} team="kes" num={9} label="Kestrel Bay No. 9" />
              <Tag x={930} y={380} text="Sprint 31.2 km/h" color="var(--space-ink)" />
            </Grammar>
            <Grammar name="offside_line" rule="Analyst view: the defending team’s last line and its distance from goal.">
              <BackLine x={95} label="Ashmoor line · 10.0 m" />
              {[24, 30, 36, 42].map((y) => (
                <PlayerDot key={y} at={[94.5, y]} team="ash" num={4} label="Ashmoor defender" />
              ))}
            </Grammar>
            <div className="card" style={{ padding: 12 }}>
              <div className="mono" style={{ fontSize: 13, marginBottom: 8 }}>
                correction
              </div>
              <div style={{ height: 140, borderRadius: 8, background: 'var(--edge)', padding: 14, display: 'flex', flexDirection: 'column', justifyContent: 'center', gap: 10 }}>
                <Chip tone="alert" style={{ alignSelf: 'flex-end' }}>
                  Correction
                </Chip>
                <span className="strike" style={{ fontSize: 14 }}>
                  Pass No. 8 to No. 10: 28.0 m, difficulty 6.1 of 10.
                </span>
                <span style={{ fontSize: 14 }}>Pass No. 8 to No. 10: 27.4 m, difficulty 5.9 of 10.</span>
              </div>
              <p className="muted" style={{ fontSize: 12, lineHeight: 1.45, marginTop: 8 }}>
                A retracted claim stays struck through for 3 s with a Correction tag beside its patch.
              </p>
            </div>
          </div>
        </section>

        <div className="row row-stretch">
          <div className="grow" style={{ flexBasis: 520 }}>
            <Section title="Rendering tiers">
              <div className="grid-2">
                {[
                  ['A', 'WebGPU', 'Four 3D cameras with Babylon.js, the control field computed per pixel on the GPU, ghosts. 60–120 fps.'],
                  ['B', 'WebGL2', 'The same 3D views, with the worker’s control field as a smoothed texture and every overlay. 60 fps.'],
                  ['C', 'Canvas 2D', 'The 2D view: the 2 m field, smoothed contours and every overlay. 30 fps or better.'],
                  ['D', 'Video', 'Recorded clips with the graphics burned in, kept in step with the match clock, and a live caption track.'],
                ].map(([id, name, what]) => (
                  <div key={id} className="tile">
                    <div className="cluster" style={{ gap: 8 }}>
                      <span className="display" style={{ fontSize: 28, color: 'var(--space-ink)' }}>
                        {id}
                      </span>
                      <span style={{ fontWeight: 600 }}>{name}</span>
                    </div>
                    <p className="muted" style={{ fontSize: 12, lineHeight: 1.45, marginTop: 4 }}>
                      {what}
                    </p>
                  </div>
                ))}
              </div>
            </Section>
          </div>
          <div className="grow" style={{ flexBasis: 520 }}>
            <Section title="Density by mode">
              <div className="grid-2">
                {[
                  ['Casual', '1', 'One pitch overlay at a time, each held 2.5 s.'],
                  ['Learn', '1 + card', 'Casual, plus a definition the first time.'],
                  ['Analyst', 'Up to 4', 'Field, line, displacement and evidence.'],
                  ['Player focus', '2', 'The followed player and the key overlay.'],
                  ['Audio-described', 'Voice', 'Spoken lines and a stereo cue.'],
                  ['Broadcaster', 'Producer', 'Whatever the producer approves.'],
                ].map(([mode, max, note]) => (
                  <div key={mode} className="tile">
                    <div style={{ fontWeight: 600, fontSize: 14 }}>{mode}</div>
                    <div className="display" style={{ fontSize: 28 }}>
                      {max}
                    </div>
                    <div className="muted" style={{ fontSize: 12 }}>
                      {note}
                    </div>
                  </div>
                ))}
              </div>
            </Section>
          </div>
        </div>
      </div>
    </div>
  );
}
