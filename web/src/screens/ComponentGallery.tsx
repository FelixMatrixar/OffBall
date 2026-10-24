import { useState, type ReactNode } from 'react';
import { AgentTrace, BarList, ChartFrame, Leaderboard, MomentumRibbon, PassNetwork, ShotMap, Sparkline, VegaChart, controlIndexSpec, passNetworkTable, shotTable } from '../components/charts';
import { ModeSwitcher, Scoreboard, Stage2D } from '../components/match';
import { Ball, BackLine, ControlField, Contours, Displacement, GapRing, Ghost, PassLine, Pitch, PlayerDot, RunArrow, ShutRing, type Orientation } from '../components/pitch';
import {
  BottomSheet,
  Button,
  CaptionReveal,
  Chip,
  CountUp,
  Dialog,
  Drawer,
  Equalizer,
  LinkButton,
  LiveBadge,
  Logo,
  PendingChip,
  PulseDot,
  QrCode,
  Segmented,
  Skeleton,
  Spinner,
  Stepper,
  Switch,
  ToastStack,
  TypingDots,
  VerifiedChip,
  useToasts,
} from '../components/ui';
import { LEADERS } from '../lib/content';
import { fixedTime, frameState, getStore } from '../lib/feed';
import { LANGS, PACKS, useI18n } from '../lib/i18n';
import { PLAYERS, playerLabel } from '../lib/match';
import { usePrefs, type Lang, type Mode } from '../lib/prefs';
import { CONTROL_INDEX } from '../lib/stats';

function Showcase({ name, file, children }: { name: string; file: string; children: ReactNode }) {
  return (
    <section className="card anim-rise" style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 10, flexWrap: 'wrap' }}>
        <h2 className="display" style={{ fontSize: 24 }}>
          {name}
        </h2>
        <span className="mono muted" style={{ fontSize: 12 }}>
          {file}
        </span>
      </div>
      {children}
    </section>
  );
}

type OverlayDemo = 'gap' | 'shut' | 'run' | 'pass' | 'ghost' | 'analyst';

/** Every component, live and interactive, with the file it lives in. */
export function ComponentGallery() {
  const { prefs } = usePrefs();
  const i18n = useI18n();
  const [seg, setSeg] = useState<'a' | 'b' | 'c'>('a');
  const [mode, setMode] = useState<Mode>('casual');
  const [sw, setSw] = useState(true);
  const [step, setStep] = useState(1);
  const [drawer, setDrawer] = useState(false);
  const [dialog, setDialog] = useState(false);
  const [sheet, setSheet] = useState(false);
  const [lang, setLang] = useState<Lang>('en');
  const [replay, setReplay] = useState(0);
  const [overlay, setOverlay] = useState<OverlayDemo>('gap');
  const [orientation, setOrientation] = useState<Orientation>('h');
  const { toasts, push } = useToasts();
  const store = getStore();
  const fs = frameState(store, 4.9, { cf: overlay === 'shut' || overlay === 'ghost' });
  const speeds = Array.from({ length: 37 }, (_, i) => frameState(store, i * 0.25, { fields: false }).speedOf('kes-09'));

  return (
    <div className="screen">
      <div className="container stack-lg">
        <header className="anim-rise">
          <Logo />
          <h1 className="display" style={{ fontSize: 56, lineHeight: 1, marginTop: 16 }}>
            Components
          </h1>
          <p className="muted" style={{ fontSize: 17, marginTop: 10, maxWidth: 900 }}>
            The building blocks of every OffBall screen, live and interactive. Each card names the file the component lives in.
          </p>
        </header>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(min(100%, 440px), 1fr))', gap: 18 }}>
          <Showcase name="Buttons" file="components/ui/Button.tsx">
            <div className="cluster">
              <Button variant="primary">Primary</Button>
              <Button>Secondary</Button>
              <Button variant="ghost">Ghost</Button>
              <Button variant="danger">Retract</Button>
              <Button variant="solid" icon round aria-label="Play">
                <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
                  <path d="M4 2 L14 8 L4 14 Z" style={{ fill: 'currentColor' }} />
                </svg>
              </Button>
              <LinkButton href="#/match" variant="primary" size="lg">
                Watch the match
              </LinkButton>
            </div>
          </Showcase>

          <Showcase name="Switch and segmented control" file="components/ui/Switch.tsx · Segmented.tsx">
            <Switch checked={sw} onChange={setSw} label="What if no run?" />
            <Segmented
              options={[
                { value: 'a', label: 'Minimal' },
                { value: 'b', label: 'Standard' },
                { value: 'c', label: 'Rich' },
              ]}
              value={seg}
              onChange={setSeg}
              label="Overlay density"
            />
            <ModeSwitcher value={mode} onChange={setMode} />
            <p className="muted" style={{ fontSize: 12 }}>
              A radio group: Tab in, then arrow keys. The indicator stays under its option when the control scrolls.
            </p>
          </Showcase>

          <Showcase name="Chips and live indicators" file="components/ui/Chip.tsx · Live.tsx">
            <div className="cluster">
              <Chip tone="space">Space</Chip>
              <Chip tone="outline">Outline</Chip>
              <Chip tone="accent">Waiting</Chip>
              <Chip tone="danger">Retracted</Chip>
              <Chip tone="alert">Correction</Chip>
              <span key={replay}>
                <VerifiedChip />
              </span>
              <PendingChip />
            </div>
            <div className="cluster" style={{ gap: 18 }}>
              <LiveBadge />
              <PulseDot />
              <Equalizer active />
              <Spinner />
              <TypingDots label="Checking the data" />
            </div>
          </Showcase>

          <Showcase name="Scoreboard" file="components/match/Scoreboard.tsx">
            <Scoreboard score={{ kes: replay % 2, ash: 0 }} clock="63:07" yours="kes" />
            <Button onClick={() => setReplay((n) => n + 1)}>Score a goal</Button>
          </Showcase>

          <Showcase name="Caption reveal" file="components/ui/CaptionReveal.tsx">
            <label htmlFor="cg-lang" className="field-label" style={{ marginBottom: 0 }}>
              Language
            </label>
            <select id="cg-lang" className="select" value={lang} onChange={(e) => setLang(e.target.value as Lang)}>
              {LANGS.map((l) => (
                <option key={l.code} value={l.code}>
                  {l.native}
                </option>
              ))}
            </select>
            <CaptionReveal key={`${lang}-${replay}`} text={PACKS[lang].preview} lang={lang} style={{ fontSize: 20, fontWeight: 500, lineHeight: 1.4 }} />
            <Button onClick={() => setReplay((n) => n + 1)}>Replay</Button>
          </Showcase>

          <Showcase name="Count-up and skeleton" file="components/ui/CountUp.tsx · Feedback.tsx">
            <div className="display" style={{ fontSize: 44 }}>
              <CountUp key={replay} value={41} suffix=" m²" />
            </div>
            <Skeleton height={14} />
            <Skeleton width="60%" height={26} />
            <Button onClick={() => setReplay((n) => n + 1)}>Replay</Button>
          </Showcase>

          <Showcase name="Toasts" file="components/ui/Feedback.tsx">
            <div className="cluster">
              <Button onClick={() => push('Switched to the 2D view (Tier C) to hold 30 fps.', 'info')}>Quality step-down</Button>
              <Button onClick={() => push('Back in sync. Nothing was missed.', 'success')}>Back in sync</Button>
              <Button onClick={() => push('Fatigue gap forming on Ashmoor’s right.', 'warn')}>Alert</Button>
            </div>
            <div style={{ minHeight: 60, display: 'flex', justifyContent: 'flex-end' }}>
              <ToastStack toasts={toasts} />
            </div>
          </Showcase>

          <Showcase name="Stepper, drawer, dialog and sheet" file="components/ui/Stepper.tsx · Drawer.tsx · BottomSheet.tsx">
            <Stepper steps={['Watch', 'Club', 'Language', 'Ready']} current={step} />
            <div className="cluster">
              <Button onClick={() => setStep((s) => Math.max(0, s - 1))}>Back</Button>
              <Button variant="primary" onClick={() => setStep((s) => Math.min(4, s + 1))}>
                Next
              </Button>
              <Button variant="ghost" onClick={() => setDrawer(true)}>
                Open a drawer
              </Button>
              <Button variant="ghost" onClick={() => setDialog(true)}>
                Open a dialog
              </Button>
              <Button variant="ghost" onClick={() => setSheet((s) => !s)}>
                {sheet ? 'Close the sheet' : 'Open a sheet'}
              </Button>
            </div>
            <Drawer open={drawer} onClose={() => setDrawer(false)} title="Drawer">
              <p className="muted">The page behind is inert while it’s open, so Tab stays inside. Closes from its button, the backdrop or Escape, slides out, and returns focus.</p>
            </Drawer>
            <Dialog open={dialog} onClose={() => setDialog(false)} title="Dialog">
              <p className="muted">The same modal behaviour, centred: keyboard shortcuts, pairing and voice consent use it.</p>
            </Dialog>
            {sheet && (
              <BottomSheet title="Bottom sheet" open onToggle={(o) => !o && setSheet(false)}>
                <p className="muted" style={{ fontSize: 14 }}>
                  The phone layout’s panel. Not modal; Escape collapses it.
                </p>
              </BottomSheet>
            )}
          </Showcase>

          <Showcase name="QR code" file="components/ui/QrCode.tsx">
            <QrCode value={`${window.location.origin}${window.location.pathname}#/phone?pair=K7MQ4P`} label="Sample pairing QR code" />
          </Showcase>

          <Showcase name="Charts" file="components/charts/*">
            <MomentumRibbon key={`r${replay}`} minute={63} label="Momentum ribbon" />
            <Sparkline values={speeds} max={36} span={37} threshold={25.2} thresholdLabel="sprint 25.2" label="No. 9 speed" />
            <Leaderboard key={`l${replay}`} rows={LEADERS} max={140} />
            <BarList
              key={`b${replay}`}
              bars={[
                { label: 'No. 5', value: 71, color: 'var(--ash)' },
                { label: 'League', value: 52, color: 'var(--muted)' },
              ]}
              max={100}
              suffix="%"
            />
            <AgentTrace
              key={`t${replay}`}
              rows={[
                { agent: 'Scout', start: 0, end: 0.28 },
                { agent: 'Explainer', start: 0.3, end: 1.15 },
                { agent: 'Fact-checker', start: 1.15, end: 1.62, kind: 'rejected' },
                { agent: 'Explainer · retry', start: 1.62, end: 2.05 },
                { agent: 'Persona', start: 2.05, end: 2.6 },
              ]}
            />
            <Button onClick={() => setReplay((n) => n + 1)}>Replay charts</Button>
          </Showcase>

          <Showcase name="Chart frame and Vega-Lite" file="components/charts/ChartFrame.tsx · VegaChart.tsx">
            <ChartFrame title="Control index" name="control-index" summary="Each chart has a text summary, a table view and exports, each labelled synthetic and AI-generated." columns={['Minute', 'Kestrel Bay', 'Ashmoor']} rows={CONTROL_INDEX.filter((d) => d.minute % 10 === 0).map((d) => [d.minute, d.kes, d.ash])}>
              <VegaChart spec={controlIndexSpec(63)} label="Control index" />
            </ChartFrame>
          </Showcase>

          <Showcase name="Pitch charts" file="components/charts/PitchCharts.tsx">
            <ChartFrame title="Pass network" name="pass-network" summary="Kestrel Bay’s passes between players." {...passNetworkTable()}>
              <PassNetwork />
            </ChartFrame>
            <ChartFrame title="Shot map" name="shot-map" summary="Shots sized by xG." {...shotTable()}>
              <ShotMap />
            </ChartFrame>
          </Showcase>
        </div>

        <Showcase name="Pitch and overlays" file="components/pitch/*">
          <div className="cluster">
            <Segmented
              options={[
                { value: 'gap', label: 'Gap ring' },
                { value: 'shut', label: 'Gap shut' },
                { value: 'run', label: 'Run arrow' },
                { value: 'pass', label: 'Pass line' },
                { value: 'ghost', label: 'Ghosts' },
                { value: 'analyst', label: 'Analyst' },
              ]}
              value={overlay}
              onChange={setOverlay}
              label="Overlay"
              minWidth={104}
            />
            <Segmented
              options={[
                { value: 'h', label: 'Horizontal' },
                { value: 'v', label: 'Vertical' },
              ]}
              value={orientation}
              onChange={setOrientation}
              label="Orientation"
            />
          </div>
          <div className="pitch-card" style={{ maxWidth: orientation === 'v' ? 420 : undefined }}>
            <Pitch label="Component demo pitch" orientation={orientation} field={<ControlField field={overlay === 'shut' || overlay === 'ghost' ? fs.cfField : fs.field} strength={overlay === 'analyst' ? 1 : 0.6} orientation={orientation} theme={prefs.theme} stamp={orientation === 'h' ? 1 : 2} />}>
              <Contours field={fs.field} levels={overlay === 'analyst' ? [0.25, 0.5, 0.75] : [0.5]} stamp={1} />
              {overlay === 'gap' && <GapRing key="gap" at={[88.5, 40]} label="Space opens here" />}
              {overlay === 'shut' && <ShutRing key="shut" at={[88.5, 40]} label="Gap stays shut" />}
              {overlay === 'run' && <RunArrow key="run" from={[84, 34]} runner={fs.pos['kes-09']} ahead={[91, 53]} />}
              {overlay === 'pass' && <PassLine key="pass" from={[60.6, 40.4]} ball={fs.ballXY} to={[88, 40.3]} difficulty={6.1} />}
              {overlay === 'ghost' && (
                <>
                  <Ghost at={[84.6, 34.6]} team="kes" label="9 · no run" />
                  <Ghost at={[90.3, 37.3]} team="ash" label="5 · stays" />
                </>
              )}
              {overlay === 'analyst' && (
                <>
                  <BackLine x={105 - fs.depth} label={`Ashmoor line · ${fs.depth.toFixed(1)} m`} />
                  <Displacement from={[90, 37]} to={fs.pos['ash-05']} label={`${fs.displacement.toFixed(1)} m`} />
                </>
              )}
              {PLAYERS.map((p) => (
                <PlayerDot key={p.id} at={fs.pos[p.id]} team={p.team} num={p.num} label={playerLabel(p.id)} />
              ))}
              <Ball at={fs.ballXY} trail={fs.trail} />
            </Pitch>
          </div>
        </Showcase>

        <Showcase name="Stage, from the feed" file="components/match/Stage2D.tsx">
          <p className="muted" style={{ fontSize: 13 }}>
            The full 2D stage reading the overlay feed: Tab into the pitch and use the arrow keys to move between players.
          </p>
          <div className="pitch-card">
            <Stage2D store={store} time={fixedTime(4.9)} mode="analyst" density="standard" theme={prefs.theme} fav="kes-09" i18n={i18n} orientation="h" variant="real" ghosts={false} onFollow={() => {}} />
          </div>
        </Showcase>
      </div>
    </div>
  );
}
