import { useEffect, useRef, useState, type CSSProperties } from 'react';
import { LogoMark, Logo, Segmented, Switch } from '../components/ui';
import { PLAYERS, at } from '../lib/match';
import { cx } from '../lib/cx';

// A fixed broadcast camera on the near touchline, looking across Ashmoor's half.
const F = 7200;
const XC = 84;
const C = 150;
const K = 471300;
const H0 = -1992;
const V = 5760;
const T = 4.6;

const project = (x: number, y: number) => {
  const d = y + C;
  return { x: 960 + (F * (x - XC)) / d, y: H0 + K / d, d };
};
const pt = (x: number, y: number) => {
  const p = project(x, y);
  return `${p.x.toFixed(1)},${p.y.toFixed(1)}`;
};
const arc = (cx: number, cy: number, r: number, a0: number, a1: number, keep: (x: number) => boolean = () => true) => {
  const out: string[] = [];
  for (let i = 0; i <= 48; i++) {
    const a = a0 + ((a1 - a0) * i) / 48;
    const x = cx + r * Math.cos(a);
    const y = cy + r * Math.sin(a);
    if (keep(x)) out.push(pt(x, y));
  }
  return out.join(' ');
};

function useFitScale(width: number) {
  const ref = useRef<HTMLDivElement>(null);
  const [scale, setScale] = useState(0.5);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const observer = new ResizeObserver(([entry]) => setScale(entry.contentRect.width / width));
    observer.observe(el);
    return () => observer.disconnect();
  }, [width]);
  return { ref, scale };
}

function Scene() {
  const stripes: { pts: string; fill: string }[] = [];
  for (let i = 0; i < 20; i++) {
    const x0 = i * 5.25;
    const x1 = x0 + 5.25;
    if (x1 < 40) continue;
    stripes.push({ pts: [pt(x0, 0), pt(x1, 0), pt(x1, 68), pt(x0, 68)].join(' '), fill: i % 2 ? 'var(--bc-grass-1)' : 'var(--bc-grass-2)' });
  }
  stripes.push({ pts: [pt(105, -6), pt(115, -6), pt(115, 74), pt(105, 74)].join(' '), fill: 'var(--bc-grass-3)' });

  const lines = [
    [pt(30, 0), pt(105, 0)].join(' '),
    [pt(30, 68), pt(105, 68)].join(' '),
    [pt(105, 0), pt(105, 68)].join(' '),
    [pt(52.5, 0), pt(52.5, 68)].join(' '),
    [pt(105, 13.84), pt(88.5, 13.84), pt(88.5, 54.16), pt(105, 54.16)].join(' '),
    [pt(105, 24.84), pt(99.5, 24.84), pt(99.5, 43.16), pt(105, 43.16)].join(' '),
    arc(94, 34, 9.15, Math.PI * 0.5, Math.PI * 1.5, (x) => x <= 88.5),
    arc(52.5, 34, 9.15, -Math.PI * 0.5, Math.PI * 0.5),
  ];
  const gap = Array.from({ length: 48 }, (_, i) => {
    const a = (i / 48) * Math.PI * 2;
    return pt(88.5 + 6.2 * Math.cos(a), 40 + 6.2 * Math.sin(a));
  }).join(' ');

  const k9Keys = PLAYERS.find((p) => p.id === 'kes-09')!.keys;
  const lead = at(k9Keys, Math.min(4.6, T + 0.8));
  const run = Array.from({ length: 13 }, (_, i) => pt(84 + (lead[0] - 84) * (i / 12), 34 + (lead[1] - 34) * (i / 12))).join(' ');
  const e = project(lead[0], lead[1]);
  const s0 = project(84 + (lead[0] - 84) * 0.9, 34 + (lead[1] - 34) * 0.9);
  const len = Math.hypot(e.x - s0.x, e.y - s0.y) || 1;
  const ux = (e.x - s0.x) / len;
  const uy = (e.y - s0.y) / len;
  const head = `${(e.x + ux * 22).toFixed(1)},${(e.y + uy * 22).toFixed(1)} ${(e.x - uy * 16).toFixed(1)},${(e.y + ux * 16).toFixed(1)} ${(e.x + uy * 16).toFixed(1)},${(e.y - ux * 16).toFixed(1)}`;

  const bu = (T - 4.2) / 1.4;
  const ball = project(60.6 + (88 - 60.6) * bu, 40.4 - 0.1 * bu);
  const target = project(88, 40.3);

  const posts = [project(105, 30.34), project(105, 37.66)];
  const goal = [
    [posts[0].x, posts[0].y],
    [posts[0].x, posts[0].y - (V * 2.44) / posts[0].d],
    [posts[1].x, posts[1].y - (V * 2.44) / posts[1].d],
    [posts[1].x, posts[1].y],
  ]
    .map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`)
    .join(' ');

  const figures = PLAYERS.filter((p) => p.id !== 'kes-01')
    .map((p) => {
      const [x, y] = at(p.keys, T);
      const q = project(x, y);
      return { p, q };
    })
    .filter(({ q }) => q.x > -60 && q.x < 1980)
    .sort((a, b) => b.q.d - a.q.d);

  return (
    <svg viewBox="0 0 1920 1080" role="img" aria-label="Broadcast camera view of Ashmoor's half. No. 9 has pulled No. 5 wide and a gap is open in the centre." style={{ position: 'absolute', inset: 0, width: 1920, height: 1080 }}>
      <rect x={0} y={0} width={1920} height={1080} style={{ fill: 'var(--bg)' }} />
      <rect x={0} y={0} width={1920} height={64} style={{ fill: 'var(--bc-stand-1)' }} />
      <rect x={0} y={64} width={1920} height={40} style={{ fill: 'var(--bc-stand-2)' }} />
      <rect x={0} y={104} width={1920} height={38} style={{ fill: 'var(--bc-stand-3)' }} />
      <rect x={0} y={142} width={1920} height={22} style={{ fill: 'var(--bc-stand-4)' }} />
      {stripes.map((s, i) => (
        <polygon key={i} points={s.pts} style={{ fill: s.fill }} />
      ))}
      <g style={{ fill: 'none', stroke: 'var(--bc-chalk)', strokeWidth: 3, strokeLinejoin: 'round' }}>
        {lines.map((l, i) => (
          <polyline key={i} points={l} />
        ))}
      </g>
      <polygon className="bc-ring" points={gap} style={{ fill: 'var(--bc-ring-fill)', stroke: 'var(--space)', strokeWidth: 6, strokeLinejoin: 'round' }} />
      <polyline className="bc-run" points={run} style={{ fill: 'none', stroke: 'var(--kes)', strokeWidth: 9, strokeLinecap: 'round' }} />
      <polygon className="bc-head" points={head} style={{ fill: 'var(--kes)' }} />
      <line x1={ball.x} y1={ball.y} x2={target.x} y2={target.y} style={{ stroke: 'var(--text)', strokeWidth: 5, strokeDasharray: '16 12', opacity: 0.9 }} />
      {figures.map(({ p, q }) => {
        const h = (V * 1.85) / q.d;
        const w = (F * 0.62) / q.d;
        const bodyH = h * 0.78;
        const hr = w * 0.42;
        const kes = p.team === 'kes';
        return (
          <g key={p.id}>
            <ellipse cx={q.x} cy={q.y} rx={(F * 0.6) / q.d} ry={(F * 0.18) / q.d} style={{ fill: 'var(--bc-shadow)' }} />
            <rect x={q.x - w / 2} y={q.y - bodyH} width={w} height={bodyH} rx={w / 2.4} style={{ fill: kes ? 'var(--kes)' : 'var(--ash)', stroke: 'var(--bc-outline)', strokeWidth: 1.5 }} />
            <circle cx={q.x} cy={q.y - bodyH - hr * 0.9} r={hr} style={{ fill: 'var(--bc-skin)', stroke: 'var(--bc-outline)', strokeWidth: 1 }} />
            <text x={q.x} y={q.y - bodyH * 0.45} style={{ fill: kes ? 'var(--on-kes)' : 'var(--on-ash)', fontFamily: 'var(--font-body)', fontWeight: 700, fontSize: w * 0.62, textAnchor: 'middle', dominantBaseline: 'middle' }}>
              {p.num}
            </text>
          </g>
        );
      })}
      <circle cx={ball.x} cy={ball.y - 4} r={(F * 0.16) / ball.d} style={{ fill: 'var(--ball)', stroke: 'var(--ball-edge)', strokeWidth: 2 }} />
      <polyline points={goal} style={{ fill: 'none', stroke: 'var(--text)', strokeWidth: 4 }} />
    </svg>
  );
}

interface Box {
  x0: number;
  y0: number;
  x1: number;
  y1: number;
}

const overlap = (a: Box, b: Box) => Math.max(0, Math.min(a.x1, b.x1) - Math.max(a.x0, b.x0)) * Math.max(0, Math.min(a.y1, b.y1) - Math.max(a.y0, b.y0));
/** EBU R 95 graphics-safe area: 90% of the frame. */
const GRAPHICS_SAFE: Box = { x0: 96, y0: 54, x1: 1824, y1: 1026 };

/** A player's figure on screen at the template's moment, head to shadow, with a little room around it. */
function figureBox(id: string): Box {
  const [x, y] = at(PLAYERS.find((p) => p.id === id)!.keys, T);
  const q = project(x, y);
  const h = (V * 1.85) / q.d;
  const w = (F * 0.62) / q.d;
  return { x0: q.x - w / 2 - 6, y0: q.y - h - 6, x1: q.x + w / 2 + 6, y1: q.y + 6 };
}

const TAGS = [
  { id: 'kes-09', text: 'No. 9 · decoy run' },
  { id: 'ash-05', text: 'No. 5 follows' },
] as const;

/**
 * Where each player tag goes: above its player, or nudged along, or beside them, whichever covers the fewest other
 * players and tags and stays inside graphics-safe (PRD 15.2, as on the live pitch). `left` is the tag's centre, which
 * its entrance animation keeps with translateX(−50%).
 */
const TAG_PLACES: Record<string, { left: number; top: number }> = (() => {
  const H = 47;
  const figures = PLAYERS.filter((p) => p.id !== 'kes-01').map((p) => ({ id: p.id, box: figureBox(p.id) }));
  const space = project(88.5, 46.8);
  const placed: Box[] = [{ x0: space.x - 70, y0: space.y - 58, x1: space.x + 70, y1: space.y - 14 }];
  const out: Record<string, { left: number; top: number }> = {};
  for (const tag of TAGS) {
    // 16 px padding each side, the 14 px team dot and its gap, and about 15 px a character at 26 px bold.
    const W = 56 + tag.text.length * 15;
    const b = figureBox(tag.id);
    const cx = (b.x0 + b.x1) / 2;
    const above = b.y0 - H - 12;
    const beside = (b.y0 + b.y1) / 2 - H / 2 - 12;
    const spots = [
      { left: cx, top: above },
      { left: cx + W / 2 - 30, top: above },
      { left: cx - W / 2 + 30, top: above },
      { left: b.x1 + 14 + W / 2, top: beside },
      { left: b.x0 - 14 - W / 2, top: beside },
      { left: cx, top: above - H - 8 },
    ];
    const boxOf = (s: { left: number; top: number }): Box => ({ x0: s.left - W / 2, y0: s.top, x1: s.left + W / 2, y1: s.top + H });
    const cost = (s: { left: number; top: number }, i: number) => {
      const t = boxOf(s);
      let c = i * 4 + (W * H - overlap(t, GRAPHICS_SAFE)) * 6;
      for (const f of figures) if (f.id !== tag.id) c += overlap(t, f.box) * 2;
      for (const p of placed) c += overlap(t, p) * 3;
      return c;
    };
    const costs = spots.map(cost);
    const best = spots[costs.indexOf(Math.min(...costs))];
    placed.push(boxOf(best));
    out[tag.id] = best;
  }
  return out;
})();

/** A tag by a player, entering a fraction `into` of the way through the template's 10 s loop. */
function tagStyle(id: string, into: number): CSSProperties {
  const { left, top } = TAG_PLACES[id];
  return {
    position: 'absolute',
    left,
    top,
    transform: 'translateX(-50%)',
    display: 'flex',
    alignItems: 'center',
    gap: 10,
    padding: '8px 16px',
    borderRadius: 999,
    background: 'var(--bc-chip)',
    color: 'var(--text)',
    font: '700 26px var(--font-body)',
    whiteSpace: 'nowrap',
    animationDelay: `calc(var(--bc-cycle) * ${into})`,
  };
}

/** The 1080p broadcast output with EBU R 95 safe areas, scaled to fit the window. */
export function BroadcastOutput() {
  const [output, setOutput] = useState<'program' | 'key'>('program');
  const [safe, setSafe] = useState(true);
  const [animate, setAnimate] = useState(true);
  const { ref, scale } = useFitScale(1920);
  const space = project(88.5, 46.8);

  return (
    <div className="screen">
      <div className="container stack">
        <h1 className="sr-only">Broadcast output</h1>
        <header className="cluster anim-rise" style={{ gap: '12px 20px' }}>
          <Logo suffix="Broadcast" />
          <div className="cluster spacer">
            <Segmented
              options={[
                { value: 'program', label: 'Program' },
                { value: 'key', label: 'Graphics only (key)' },
              ]}
              value={output}
              onChange={setOutput}
              label="Output"
            />
            <Switch checked={safe} onChange={setSafe} label="Safe areas" />
            <Switch checked={animate} onChange={setAnimate} label="Animate graphics" />
          </div>
        </header>

        <div ref={ref} className="anim-rise" style={{ position: 'relative', width: '100%', aspectRatio: '16 / 9', borderRadius: 12, overflow: 'hidden', border: '1px solid var(--line)', animationDelay: 'calc(var(--stagger) * 2)' }}>
          <div
            data-theme="broadcast"
            className={cx(animate && 'bc-anim')}
            style={{
              position: 'absolute',
              left: 0,
              top: 0,
              width: 1920,
              height: 1080,
              transform: `scale(${scale})`,
              transformOrigin: 'top left',
              fontFamily: 'var(--font-body)',
              color: 'var(--text)',
              ...(output === 'program'
                ? { background: 'var(--bg)' }
                : { backgroundColor: 'var(--bc-key-2)', backgroundImage: 'repeating-conic-gradient(var(--bc-key-1) 0% 25%, var(--bc-key-2) 0% 50%)', backgroundSize: '48px 48px' }),
            }}
          >
            {output === 'program' && <Scene />}

            {TAGS.map((tag, i) => (
              <div key={tag.id} className="bc-tag" style={tagStyle(tag.id, i * 0.035)}>
                <span style={{ width: 14, height: 14, borderRadius: 7, background: tag.id.startsWith('kes') ? 'var(--kes)' : 'var(--ash)' }} />
                {tag.text}
              </div>
            ))}
            <div
              className="bc-tag"
              style={{ position: 'absolute', left: space.x, top: space.y - 58, transform: 'translateX(-50%)', padding: '6px 14px', borderRadius: 6, background: 'var(--space)', color: 'var(--on-space)', font: '700 24px var(--font-body)', letterSpacing: '0.12em', animationDelay: 'calc(var(--bc-cycle) * 0.14)' }}
            >
              SPACE
            </div>

            <div className="bc-bug" style={{ position: 'absolute', left: 96, top: 54, display: 'flex', height: 64, fontFamily: 'var(--font-display)', fontWeight: 700, borderRadius: 6, overflow: 'hidden' }}>
              <span style={{ background: 'var(--kes)', width: 10 }} />
              <span style={{ background: 'var(--surface)', display: 'flex', alignItems: 'center', padding: '0 18px', fontSize: 36, letterSpacing: 1 }}>KES</span>
              <span style={{ background: 'var(--bc-score)', color: 'var(--bc-on-score)', display: 'flex', alignItems: 'center', padding: '0 18px', fontSize: 40 }}>0–0</span>
              <span style={{ background: 'var(--surface)', display: 'flex', alignItems: 'center', padding: '0 18px', fontSize: 36, letterSpacing: 1 }}>ASH</span>
              <span style={{ background: 'var(--ash)', width: 10 }} />
              <span style={{ background: 'var(--bc-clock)', display: 'flex', alignItems: 'center', padding: '0 18px', fontSize: 32, fontWeight: 600 }}>63:04</span>
            </div>

            <div className="bc-bug-r" style={{ position: 'absolute', right: 96, top: 54, display: 'flex', alignItems: 'center', gap: 10, height: 64, padding: '0 18px', borderRadius: 6, background: 'var(--bc-panel)', fontFamily: 'var(--font-display)', fontSize: 30, fontWeight: 700 }}>
              <LogoMark size={30} />
              OffBall · space view
            </div>

            <div className="bc-lower" style={{ position: 'absolute', left: 96, bottom: 54, width: 1220, display: 'flex', borderRadius: 8, overflow: 'hidden', background: 'var(--bc-panel)' }}>
              <span style={{ width: 12, background: 'var(--space)', flex: 'none' }} />
              <div style={{ padding: '22px 28px' }}>
                <p style={{ fontSize: 38, lineHeight: 1.25, fontWeight: 600 }}>Watch No. 9. This run isn’t to get the ball. It’s to pull a defender away.</p>
                <p style={{ marginTop: 10, fontSize: 20, color: 'var(--muted)' }}>OffBall · AI-generated · fact-checked · synthetic match</p>
              </div>
            </div>

            <div className="bc-stat" style={{ position: 'absolute', right: 96, bottom: 54, width: 420, borderRadius: 8, background: 'var(--bc-panel)', padding: '22px 26px' }}>
              <div style={{ fontSize: 18, fontWeight: 700, letterSpacing: '0.1em', color: 'var(--muted)' }}>DEFENDER PULLED</div>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 14, marginTop: 6 }}>
                <span style={{ fontFamily: 'var(--font-display)', fontSize: 76, fontWeight: 700, lineHeight: 1 }}>10.8 m</span>
                <span style={{ fontSize: 20, color: 'var(--ash)', fontWeight: 600 }}>No. 5</span>
              </div>
            </div>

            {safe && (
              <>
                <div aria-hidden="true" style={{ position: 'absolute', left: 67.2, top: 37.8, width: 1785.6, height: 1004.4, border: '2px dashed var(--bc-safe-action)', pointerEvents: 'none' }} />
                <div aria-hidden="true" style={{ position: 'absolute', left: 96, top: 54, width: 1728, height: 972, border: '2px dashed var(--bc-safe-graphics)', pointerEvents: 'none' }} />
                {/* The key sits in the margin outside action-safe, where nothing is ever drawn, so it never crosses a line or a graphic. */}
                <div aria-hidden="true" style={{ position: 'absolute', left: 67.2, top: 1047, display: 'flex', gap: 24, padding: '3px 10px', borderRadius: 6, background: 'var(--bc-panel)', font: '600 16px var(--font-body)', lineHeight: 1.2, pointerEvents: 'none' }}>
                  <span style={{ display: 'flex', alignItems: 'center', gap: 8, color: 'var(--bc-safe-action-text)' }}>
                    <span style={{ width: 26, borderTop: '2px dashed var(--bc-safe-action)' }} />
                    Action-safe 93%
                  </span>
                  <span style={{ display: 'flex', alignItems: 'center', gap: 8, color: 'var(--bc-safe-graphics-text)' }}>
                    <span style={{ width: 26, borderTop: '2px dashed var(--bc-safe-graphics)' }} />
                    Graphics-safe 90% · EBU R 95
                  </span>
                </div>
              </>
            )}
          </div>
        </div>
        <p className="muted" style={{ fontSize: 12 }}>
          In production, each graphic enters and leaves at its overlay’s own start and end times; here the reference template loops every 10 s.
        </p>

        {/* The same graphics, driven by the live overlay protocol, for a partner's own playout (PRD 15.7). */}
        <section className="card partner-card anim-rise" aria-labelledby="partner-title" style={{ animationDelay: 'calc(var(--stagger) * 3)' }}>
          <div className="stack" style={{ gap: 6 }}>
            <h2 id="partner-title" className="card-h3" style={{ margin: 0 }}>
              Partner template · OBS and CasparCG
            </h2>
            <p className="muted" style={{ fontSize: 14, lineHeight: 1.5, maxWidth: 760 }}>
              One HTML file with a transparent 1920 × 1080 page that reads the overlay protocol from a JSONL replay, Server-Sent Events or WebSocket. In OBS, add it as a Browser
              Source at 1920 × 1080. In CasparCG, play it on a layer and drive it with play, stop, next and update.
            </p>
            <p className="mono muted" style={{ fontSize: 12 }}>
              ?feed=sse:https://…/sse · ?lang=es · ?approvals=feed · ?key=1 · ?safe=1 · ?autoplay=0
            </p>
          </div>
          <div className="cluster" style={{ gap: 8 }}>
            <a className="btn btn-primary press" href="/partner/index.html?safe=1" target="_blank" rel="noreferrer">
              Open the template
            </a>
            <a className="btn btn-ghost press" href="/partner/index.html?key=1" target="_blank" rel="noreferrer">
              Key output
            </a>
          </div>
        </section>
      </div>
    </div>
  );
}
