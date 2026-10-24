import { useMemo, useRef, useState, type FormEvent } from 'react';
import { AskPanel } from '../components/ask/AskPanel';
import { RunMap, ChartFrame, runTable } from '../components/charts';
import { Stage2D, byMetric, type StatItem } from '../components/match';
import { Button, CaptionReveal, CountUp, LogoMark, PulseDot, Segmented, Spinner } from '../components/ui';
import { focusStats } from '../lib/content';
import { frameState, useFeedStore, useMatchClock, type TimeSource } from '../lib/feed';
import { useHashQuery } from '../lib/hooks';
import { useDocumentLocale, useI18n } from '../lib/i18n';
import { CLUBS, T_END, clockLabel, player } from '../lib/match';
import { isValidCode, normaliseCode, usePairGuest } from '../lib/pairing';
import { usePrefs } from '../lib/prefs';

type Tab = 'moment' | 'player' | 'ask';

const TABS: readonly { value: Tab; label: string }[] = [
  { value: 'moment', label: 'Moment' },
  { value: 'player', label: 'Player' },
  { value: 'ask', label: 'Ask' },
];

/** Pairing: a code from the QR link, or typed in (PRD 15.5). */
function PairBar({ status, onJoin, onLeave }: { status: ReturnType<typeof usePairGuest>['status']; onJoin: (code: string) => void; onLeave: () => void }) {
  const [code, setCode] = useState('');
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (isValidCode(code)) onJoin(code);
  };
  if (status === 'paired')
    return (
      <div className="cluster" style={{ gap: 8, fontSize: 12, color: 'var(--muted)' }} role="status">
        <PulseDot size={8} />
        Paired with your screen · in sync
        <button type="button" className="btn btn-ghost btn-sm press spacer" onClick={onLeave}>
          Unpair
        </button>
      </div>
    );
  if (status === 'joining')
    return (
      <p className="cluster" style={{ gap: 8, fontSize: 13 }} role="status">
        <Spinner /> Looking for your screen…
      </p>
    );
  return (
    <form className="stack" style={{ gap: 6 }} onSubmit={submit}>
      <label htmlFor="pair-code" style={{ fontSize: 13, fontWeight: 600 }}>
        Pair with your screen
      </label>
      <div className="cluster" style={{ gap: 6, flexWrap: 'nowrap' }}>
        <input
          id="pair-code"
          className="input mono"
          value={code}
          onChange={(e) => setCode(normaliseCode(e.target.value))}
          placeholder="6-character code"
          autoComplete="off"
          inputMode="text"
          style={{
            flex: 1,
            letterSpacing: '0.2em',
            textTransform: 'uppercase',
          }}
        />
        <Button variant="primary" type="submit" disabled={!isValidCode(code)}>
          Pair
        </Button>
      </div>
      <p className="muted" style={{ fontSize: 12 }} role="status">
        {status === 'not-found'
          ? 'No screen with that code is open on this device. Pairing across devices arrives with the live service.'
          : status === 'expired'
            ? 'That code has expired. Your screen can make a new one.'
            : 'Or keep watching here on its own. Find the code under “Pair a phone” on your screen.'}
      </p>
    </form>
  );
}

/** The second-screen companion (PRD 15.5): the moment, your player and Ask OffBall, in step with the main screen. */
export function PhoneCompanion() {
  const { prefs } = usePrefs();
  const i18n = useI18n();
  const { lang, num } = i18n;
  useDocumentLocale(prefs.lang);
  const store = useFeedStore();
  const fromLink = useHashQuery('pair');
  const [code, setCode] = useState<string | null>(fromLink && isValidCode(normaliseCode(fromLink)) ? normaliseCode(fromLink) : null);
  const pair = usePairGuest(code);
  const own = useMatchClock(store, false);
  const [tab, setTab] = useState<Tab>('moment');
  const host = pair.status === 'paired' ? pair.state : null;
  // Follow the main screen's clock, allowing for the time since it sent it.
  const t = host ? Math.min(T_END, host.t + (host.playing ? (Date.now() - host.at) / 1000 : 0)) : own.t;
  // The pitch reads the paired clock every frame, extrapolating from the last message like the text does.
  const hostRef = useRef(host);
  hostRef.current = host;
  const time = useMemo<TimeSource>(() => {
    const now = () => {
      const h = hostRef.current;
      return h ? Math.min(T_END, h.t + (h.playing ? (Date.now() - h.at) / 1000 : 0)) : own.now();
    };
    return { t, now };
  }, [t, own.now]);
  const fav = host?.fav ?? prefs.fav;
  const mode = prefs.mode === 'broadcaster' ? 'casual' : prefs.mode;
  const fs = frameState(store, t);
  const score = store.scoreAt(fs.t_ms);
  const caption = store.active(fs.t_ms, { mode, whatIf: false, fav }).find((a) => a.overlay.kind === 'caption');
  const text = (caption?.overlay.text[lang] ?? caption?.overlay.text.en ?? '').replace('{count}', '1');
  const p = player(fav);
  const s = focusStats(fav);
  const stats: StatItem[] = byMetric(
    [
      {
        key: 'pulled',
        label: 'No. 5 pulled',
        value: num(fs.displacement, 1),
        unit: 'm',
      },
      {
        key: 'gap',
        label: 'Gap control',
        value: `${fs.gapPts >= 0 ? '+' : '−'}${num(Math.abs(fs.gapPts))}`,
        metric: 'space',
      },
      {
        key: 'speed',
        label: `No. ${p.num} speed`,
        value: num(fs.speedOf(fav), 1),
        unit: 'km/h',
        metric: 'sprint',
      },
    ],
    prefs.metric,
  );

  return (
    <div className="screen" style={{ display: 'flex', justifyContent: 'center' }}>
      <div className="phone-frame">
        <h1 className="sr-only">OffBall second screen</h1>
        <header
          className="anim-rise"
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: 8,
          }}
        >
          <a href="#/" className="logo" aria-label="OffBall, all screens">
            <LogoMark size={24} />
            <span className="logo-word" style={{ fontSize: 22 }}>
              OffBall
            </span>
          </a>
          <div
            className="display"
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 8,
              fontWeight: 600,
              fontSize: 19,
            }}
            role="group"
            aria-label={`${CLUBS.kes.name} ${score.kes}, ${CLUBS.ash.name} ${score.ash}, ${clockLabel(t)}`}
            dir="ltr"
          >
            <span
              aria-hidden="true"
              style={{
                width: 8,
                height: 8,
                borderRadius: 2,
                background: 'var(--kes)',
              }}
            />
            <span aria-hidden="true">KES</span>
            <span className="tabular" style={{ fontSize: 22 }} aria-hidden="true">
              {score.kes}–{score.ash}
            </span>
            <span aria-hidden="true">ASH</span>
            <span
              aria-hidden="true"
              style={{
                width: 8,
                height: 8,
                borderRadius: 2,
                background: 'var(--ash)',
              }}
            />
            <span className="tabular muted" aria-hidden="true">
              {clockLabel(t)}
            </span>
          </div>
        </header>
        <PairBar status={pair.status} onJoin={setCode} onLeave={() => (pair.leave(), setCode(null))} />
        <Segmented options={TABS} value={tab} onChange={setTab} label="Companion sections" />
        <div
          key={tab}
          style={{
            display: 'flex',
            flexDirection: 'column',
            gap: 10,
            flex: 1,
            minHeight: 0,
          }}
        >
          {tab === 'moment' && (
            <>
              <div className="card anim-rise" style={{ padding: 6 }}>
                <Stage2D store={store} time={time} mode={mode} density="minimal" theme={prefs.theme} fav={fav} i18n={i18n} orientation="v" variant="real" ghosts={false} onFollow={() => {}} />
              </div>
              <div className="card anim-rise" style={{ padding: '12px 14px' }}>
                <CaptionReveal text={text || ' '} lang={lang} style={{ fontSize: 17, lineHeight: 1.4, fontWeight: 500 }} />
                <p style={{ marginTop: 6, fontSize: 11, color: 'var(--muted)' }}>AI-generated · fact-checked · synthetic match</p>
              </div>
              <div
                className="anim-rise"
                style={{
                  display: 'grid',
                  gridTemplateColumns: 'repeat(3, minmax(0, 1fr))',
                  gap: 8,
                }}
              >
                {stats.map((st) => (
                  <div
                    key={st.key}
                    className="card"
                    style={{
                      padding: '8px 10px',
                      boxShadow: st.metric === prefs.metric ? 'inset 0 0 0 2px var(--space)' : undefined,
                    }}
                  >
                    <div style={{ fontSize: 11, color: 'var(--muted)' }}>{st.label}</div>
                    <div className="display tabular" style={{ fontSize: 22 }}>
                      {st.value}
                      {st.unit && <span className="tile-unit"> {st.unit}</span>}
                    </div>
                  </div>
                ))}
              </div>
            </>
          )}
          {tab === 'player' && (
            <>
              <div
                className="card anim-rise"
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 12,
                  padding: 16,
                }}
              >
                <span
                  className="display"
                  aria-hidden="true"
                  style={{
                    width: 56,
                    height: 56,
                    borderRadius: 28,
                    background: `var(--${p.team})`,
                    color: `var(--on-${p.team})`,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    fontSize: 30,
                    flex: 'none',
                  }}
                >
                  {p.num}
                </span>
                <div>
                  <div className="display" style={{ fontSize: 28 }}>
                    {p.name}
                  </div>
                  <div style={{ fontSize: 13, color: 'var(--muted)' }}>{CLUBS[p.team].name} · your player</div>
                </div>
              </div>
              <div className="grid-2" style={{ gap: 8 }}>
                {(
                  [
                    ['Off-ball runs', s.runs[1], 0, ''],
                    ['Defenders dragged', s.dragged[1], 0, ''],
                    ['Space created', s.space[1], 0, ' m²'],
                    ['Top speed', s.topSpeed, 1, ' km/h'],
                  ] as const
                ).map(([label, value, decimals, suffix], i) => (
                  <div
                    key={label}
                    className="card anim-rise"
                    style={{
                      padding: 12,
                      animationDelay: `calc(var(--stagger) * ${i + 2})`,
                    }}
                  >
                    <div style={{ fontSize: 12, color: 'var(--muted)' }}>{label}</div>
                    <div className="display" style={{ fontSize: 32 }}>
                      <CountUp value={value} decimals={decimals} suffix={suffix} format={(n) => num(n, decimals)} />
                    </div>
                  </div>
                ))}
              </div>
              <div className="card anim-rise" style={{ padding: 14 }}>
                <ChartFrame
                  title={`No. ${p.num}’s runs today`}
                  name={`runs-${fav}`}
                  summary={s.runsByType.map((r) => `${r.type}: ${r.n}`).join('; ') || 'No off-ball runs recorded.'}
                  {...runTable(fav)}
                >
                  <RunMap id={fav} />
                </ChartFrame>
              </div>
              <p className="anim-fade muted" style={{ fontSize: 13 }}>
                {s.season}
              </p>
            </>
          )}
          {tab === 'ask' && (
            <div className="card anim-rise" style={{ padding: '12px 14px', flex: 1, minHeight: 0 }}>
              <AskPanel t={t} />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
