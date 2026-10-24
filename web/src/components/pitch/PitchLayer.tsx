// The DOM layer over every pitch, 2D or 3D (PRD 16.2: text lives in the DOM, so it stays sharp, shapes correctly in
// every script and reaches screen readers). It decides what the labels say and keeps them readable: laid out clear
// of each other and the players, moved by transform only. Each player is a focusable button (PRD 15.4). Each stage
// says where things are in its own picture by resolving anchors given in metres.
import { useRef, useState, type CSSProperties, type KeyboardEvent } from 'react';
import { cx } from '../../lib/cx';
import type { ActiveOverlay, FrameState } from '../../lib/feed';
import { fill, isRtl } from '../../lib/i18n';
import { LABELS } from '../../lib/i18n/labels';
import { PLAYERS, playerLabel, type Key, type XY } from '../../lib/match';
import type { Density, Lang, Mode } from '../../lib/prefs';
import { labelBox, layoutLabels, textWidth100, type Box, type LabelIn, type Spot } from './labels';

export type Num = (n: number, digits?: number) => string;
export type Tone = 'text' | 'space' | 'danger' | 'muted';

/** What a label hangs from, in metres. Each stage turns it into a point in its own picture. */
export type Anchor =
  | { kind: 'player'; id: string }
  | { kind: 'point'; at: XY }
  | { kind: 'ring'; centre: XY; rx: number; ry: number }
  | { kind: 'backline' }
  | { kind: 'pulled'; id: string; from: XY | null }
  | { kind: 'ghost'; track: readonly Key[] };

/** An anchor placed in a stage's layout space: units of `u` CSS pixels, with (−30, −30) at the top-left corner. */
export interface Resolved {
  at: XY;
  /** Overrides the label's alignment, such as the back line's label on a vertical pitch. */
  align?: 'start' | 'end';
  /**
   * Other places a fixed label may go when `at` would cover a player, best first: below a ring or beside it. The label
   * takes the first that is clear (PRD 15.2), so text never sits on a player while there is room nearby.
   */
  alts?: readonly Spot[];
}

export interface LabelSpec {
  key: string;
  /** What it labels: an overlay kind, 'correction' or 'hint'. */
  kind: string;
  text: string;
  /** What it says when it joins another label on the same player, such as a badge's speed after a name. */
  short?: string;
  tone: Tone;
  /** Font size in layout units. */
  size: number;
  anchor: Anchor;
  /** Placed around the anchor clear of other labels and players (PRD 15.2); otherwise at the anchor plus dx, dy. */
  avoid: boolean;
  dx?: number;
  /** For placed labels, the preferred side: above the player (negative) or below. */
  dy: number;
  align?: 'start' | 'end';
  mono?: boolean;
  anim?: 'pop' | 'fade' | 'shake';
  /** Pops in once its ring has drawn. */
  late?: boolean;
  retracted?: boolean;
  /** Repeats something already said, such as the focused player's name: hidden from screen readers. */
  decorative?: boolean;
}

/** A stat card pinned beside a player, for broadcaster graphics. */
export interface PinSpec {
  key: string;
  title: string;
  value: string;
  id: string;
}

/**
 * Where a ring's label may go besides straight above it, best first: above but running right or left from the
 * middle, a line higher, below, then beside the ring. `half` is the ring's half-width on screen.
 */
export function ringSpots(above: XY, below: XY, east: number, west: number, mid: number, half: number): Spot[] {
  const [x, y] = above;
  const along = (at: XY, k: number): Spot[] => [
    { at: [at[0] - half * k, at[1]], align: 'start' },
    { at: [at[0] + half * k, at[1]], align: 'end' },
  ];
  return [
    ...along(above, 0.6),
    ...along(above, 1.2),
    { at: [x, y - 20] },
    ...along([x, y - 20], 0.9),
    { at: below },
    ...along(below, 0.6),
    ...along(below, 1.2),
    { at: [east, mid], align: 'start' },
    { at: [west, mid], align: 'end' },
  ];
}

/** Labels never shrink below this, however small the pitch. */
const MIN_LABEL_PX = 11;
/** How close a pointer must be to a player to point at them, in layout units: the dot, plus room for a finger. */
const REACH = { mouse: 20, touch: 30 } as const;

const textOf = (o: ActiveOverlay['overlay'], lang: Lang) => o.text[lang] ?? o.text.en ?? '';
const signed = (n: number, num: Num) => `${n >= 0 ? '+' : '−'}${num(Math.abs(n))}`;

/** The hover and focus hint: shirt number and name, then speed while the player is running. */
export function hintText(id: string, lang: Lang, num: Num, speed: number): string {
  const p = PLAYERS.find((q) => q.id === id)!;
  const tag = fill(LABELS[lang].named, { num: p.num, name: p.name.split(' ').slice(-1)[0] });
  return speed > 1 ? `${tag} · ${num(speed, 1)} km/h` : tag;
}

/**
 * Every label on the pitch for this viewer, from the feed's overlays: rings, the back line, ghosts, tags, badges,
 * Correction tags and stat cards, with live numbers refreshed ten times a second.
 */
export function buildLabels(items: readonly ActiveOverlay[], fs: FrameState, lang: Lang, num: Num, density: Density, hint: { id: string; text: string } | null): { labels: LabelSpec[]; pins: PinSpec[] } {
  const labels: LabelSpec[] = [];
  const pins: PinSpec[] = [];
  // The hint goes first, so it keeps its place above the player being pointed at.
  if (hint) labels.push({ key: `hint:${hint.id}`, kind: 'hint', text: hint.text, tone: 'text', size: 18, anchor: { kind: 'player', id: hint.id }, avoid: true, dy: -26, anim: 'fade', decorative: true });
  for (const { overlay: ov, retraction } of items) {
    const d = (ov.data ?? {}) as Record<string, unknown>;
    const key = `${ov.overlay_id}:${ov.rev}`;
    const id = ov.anchors.player_id ?? undefined;
    switch (ov.kind) {
      case 'offside_line':
        if (density === 'minimal') break;
        labels.push({ key: `${key}:line`, kind: 'offside_line', text: fill(textOf(ov, lang), { m: num(fs.depth, 1) }), tone: 'muted', size: 18, anchor: { kind: 'backline' }, avoid: false, dy: 0, anim: 'fade' });
        break;
      case 'gap_ring': {
        const c = ov.anchors.centre_xy;
        if (!c) break;
        const shut = !!d.shut;
        const text = !shut && d.live === 'gap_zone' ? fill(textOf(ov, lang), { pts: signed(fs.gapPts, num) }) : textOf(ov, lang);
        labels.push({
          key: `${key}:ring`,
          kind: 'gap_ring',
          text,
          tone: shut ? 'text' : 'space',
          size: 21,
          anchor: { kind: 'ring', centre: c, rx: Number(d.rx_m ?? 5.4), ry: Number(d.ry_m ?? 6.8) },
          avoid: false,
          dy: 0,
          anim: shut ? 'shake' : 'pop',
          late: !shut,
          retracted: !!retraction,
        });
        break;
      }
      case 'run_arrow':
        if (d.style === 'displacement' && id)
          labels.push({ key: `${key}:pulled`, kind: 'displacement', text: `${num(fs.displacement, 1)} m`, tone: 'text', size: 20, anchor: { kind: 'pulled', id, from: ov.anchors.from_xy ?? null }, avoid: false, dx: 14, dy: 0, align: 'start', mono: true, anim: 'fade' });
        break;
      case 'ghost': {
        const track = d.track as Key[] | undefined;
        // Ghosts that only move because of another's changed decision go unnamed (PRD 15.12).
        const text = textOf(ov, lang);
        if (track && text) labels.push({ key: `${key}:ghost`, kind: 'ghost', text, tone: 'text', size: 17, anchor: { kind: 'ghost', track }, avoid: false, dy: -24, anim: 'pop' });
        break;
      }
    }
    // Tags above the players: a retracted graphic shows a Correction tag instead (PRD 15.2).
    if (retraction && ov.layer !== 'dom') {
      const fixed = ov.anchors.centre_xy ?? ov.anchors.to_xy;
      const anchor: Anchor | null = fixed ? { kind: 'point', at: fixed } : id ? { kind: 'player', id } : null;
      if (anchor) labels.push({ key: `${key}:corr`, kind: 'correction', text: LABELS[lang].correction, tone: 'danger', size: 20, anchor, avoid: true, dy: 44, anim: 'pop' });
      continue;
    }
    if (density === 'minimal' || !id) continue;
    if (ov.kind === 'player_tag') labels.push({ key: `${key}:tag`, kind: 'player_tag', text: textOf(ov, lang), tone: 'text', size: 20, anchor: { kind: 'player', id }, avoid: true, dy: -26, anim: 'pop' });
    if (ov.kind === 'badge') {
      const speed = fs.speedOf(id);
      if (speed > 25.2) labels.push({ key: `${key}:badge`, kind: 'badge', text: fill(textOf(ov, lang), { speed: num(speed, 1) }), short: `${num(speed, 1)} km/h`, tone: 'space', size: 20, anchor: { kind: 'player', id }, avoid: true, dy: 40, anim: 'pop' });
    }
    if (ov.kind === 'stat_card') pins.push({ key: `${key}:pin`, title: textOf(ov, lang), value: `${num(Number(d.value ?? 0), 1)} ${String(d.unit ?? '')}`, id });
  }
  return { labels: oneTagPerPlayer(labels), pins };
}

/**
 * A player with both a name tag and a sprint badge gets one label, "No. 10 Arkwell · 32.2 km/h", in the badge's
 * colour: two labels on one player crowd the busiest part of the pitch, where the gap opens (PRD 15.2).
 */
function oneTagPerPlayer(labels: LabelSpec[]): LabelSpec[] {
  const playerOf = (l: LabelSpec) => (l.anchor.kind === 'player' ? l.anchor.id : null);
  const badges = new Map(labels.filter((l) => l.kind === 'badge').map((l) => [playerOf(l), l]));
  const merged = new Set<LabelSpec>();
  const out = labels.map((l) => {
    const badge = l.kind === 'player_tag' ? badges.get(playerOf(l)) : undefined;
    if (!badge) return l;
    merged.add(badge);
    return { ...l, text: `${l.text} · ${badge.short ?? badge.text}`, tone: badge.tone };
  });
  return out.filter((l) => !merged.has(l));
}

/** One frame's geometry, in the stage's layout space. */
export interface LayerFrame {
  /** CSS pixels per layout unit. */
  u: number;
  resolve: (a: Anchor) => Resolved | null;
  /** Each player in PLAYERS order, or null when they're out of the picture: focus targets and pointing go here. */
  players: readonly (XY | null)[];
  /** What labels keep clear of, if not the players' points: in 3D, their heads. */
  dots?: readonly (XY | null)[];
  /** Where labels may go. */
  bounds: Box;
  /** Players drawn larger than normal on a small pitch (render2d's dotScale): labels keep clear of the larger dots. */
  dotScale?: number;
}

/**
 * The state behind a pitch's DOM layer: label elements and their placement, the players' focus targets with roving
 * focus, and what the pointer is over. A stage calls `place` once per drawn frame.
 */
export function usePitchLayer() {
  // Players are one tab stop (roving focus); focus or hover shows that player's name and speed (PRD 15.4, 16.6).
  const [active, setActive] = useState(0);
  const [focused, setFocused] = useState<{ id: string; visible: boolean } | null>(null);
  const [hovered, setHovered] = useState<string | null>(null);
  const buttons = useRef<(HTMLButtonElement | null)[]>([]);
  const els = useRef(new Map<string, HTMLElement>());
  const placed = useRef(new Map<string, string>());
  const refFns = useRef(new Map<string, (el: HTMLElement | null) => void>());
  const memory = useRef(new Map<string, number>());
  /** Where each player's focus target was last put, in CSS pixels. */
  const targets = useRef<({ x: number; y: number } | undefined)[]>([]);
  const fonts = useRef({ body: 'system-ui, sans-serif', mono: 'ui-monospace, monospace' });
  const specs = useRef<{ labels: LabelSpec[]; pins: PinSpec[] }>({ labels: [], pins: [] });
  const last = useRef<LayerFrame | null>(null);

  /** One ref callback per label, so React doesn't detach and reattach every label on every render. */
  const keep = (key: string) => {
    let fn = refFns.current.get(key);
    if (!fn) {
      fn = (el: HTMLElement | null) => {
        if (el) els.current.set(key, el);
        else {
          els.current.delete(key);
          placed.current.delete(key);
          refFns.current.delete(key);
        }
      };
      refFns.current.set(key, fn);
    }
    return fn;
  };

  /** Puts every label, card and focus target where it belongs in a frame. Only writes a transform when it changes. */
  const place = (f: LayerFrame) => {
    last.current = f;
    const { u } = f;
    if (!u) return;
    const move = (key: string, x: number, y: number) => {
      const el = els.current.get(key);
      if (!el) return;
      const v = `translate3d(${((x + 30) * u).toFixed(1)}px, ${((y + 30) * u).toFixed(1)}px, 0)`;
      if (placed.current.get(key) === v) return;
      placed.current.set(key, v);
      el.style.transform = v;
      el.style.visibility = '';
    };
    const hide = (key: string) => {
      const el = els.current.get(key);
      if (el && el.style.visibility !== 'hidden') {
        el.style.visibility = 'hidden';
        placed.current.delete(key);
      }
    };
    /** Which way a label's text runs from its point; only written when it changes. */
    const align = (key: string, to: 'start' | 'end' | undefined) => {
      const el = els.current.get(key)?.firstElementChild as HTMLElement | null | undefined;
      if (!el || el.dataset.align === to) return;
      if (to) el.dataset.align = to;
      else delete el.dataset.align;
    };
    const minSize = MIN_LABEL_PX / u;
    const avoid: LabelIn[] = [];
    // Fixed labels with somewhere else to go: a ring's label, the displacement in metres.
    const flexible: LabelIn[] = [];
    const flexAlign = new Map<string, 'start' | 'end' | undefined>();
    // Fixed labels and stat cards go down first; tags and badges then steer around them as well as the players.
    const fixed: Box[] = [];
    for (const l of specs.current.labels) {
      const r = f.resolve(l.anchor);
      if (!r) {
        hide(l.key);
        continue;
      }
      const size = Math.max(l.size, minSize);
      const w100 = textWidth100(l.text, l.mono ? 500 : l.tone === 'muted' ? 600 : 700, l.mono ? fonts.current.mono : fonts.current.body);
      const width = w100 === null ? undefined : (w100 / 100) * size;
      if (l.avoid) {
        avoid.push({ key: l.key, anchor: r.at, text: l.text, size, dy: l.dy, width });
        continue;
      }
      const x = r.at[0] + (l.dx ?? 0);
      const y = r.at[1] + l.dy;
      const side = r.align ?? l.align;
      // A label set off to one side of its point may also sit on the other side, mirrored.
      const mirror: Spot[] = l.dx && side === 'start' ? [{ at: [r.at[0] - l.dx, y], align: 'end' }] : [];
      const spots: Spot[] = [{ at: [x, y], align: side }, ...(r.alts ?? []), ...mirror];
      if (spots.length > 1) {
        flexible.push({ key: l.key, anchor: r.at, text: l.text, size, width, spots });
        flexAlign.set(l.key, l.align);
        continue;
      }
      fixed.push(labelBox(x, y, l.text, size, side ?? 'middle', width));
      move(l.key, x, y);
      if (r.align) align(l.key, r.align);
    }
    for (const pin of specs.current.pins) {
      const i = PLAYERS.findIndex((p) => p.id === pin.id);
      const at = f.players[i];
      if (!at) {
        hide(pin.key);
        continue;
      }
      fixed.push({ x0: at[0] + 30, y0: at[1] - 70, x1: at[0] + 30 + Math.max(170, 120 / u), y1: at[1] - 6 });
      move(pin.key, at[0] + 30, at[1] - 70);
    }
    const dots = (f.dots ?? f.players).filter((p): p is XY => !!p);
    // The flexible fixed labels take the clearest of their spots, then count as fixed for the tags placed after them.
    for (const p of layoutLabels(flexible, dots, memory.current, fixed, f.bounds, 16 * (f.dotScale ?? 1))) {
      move(p.key, p.x, p.y);
      align(p.key, p.align ?? flexAlign.get(p.key));
      fixed.push(labelBox(p.x, p.y, p.text, p.size ?? 20, p.align ?? 'middle', p.width));
    }
    for (const p of layoutLabels(avoid, dots, memory.current, fixed, f.bounds, 16 * (f.dotScale ?? 1))) move(p.key, p.x, p.y);
    // The focus targets follow their players for screen readers' touch exploration, moved only once a player has
    // gone a few pixels, so they cost a handful of style updates a second rather than 22 every frame.
    f.players.forEach((p, i) => {
      const el = buttons.current[i];
      if (!el || !p) return;
      const x = (p[0] + 30) * u;
      const y = (p[1] + 30) * u;
      const was = targets.current[i];
      if (was && Math.abs(was.x - x) < 4 && Math.abs(was.y - y) < 4) return;
      targets.current[i] = { x, y };
      el.style.transform = `translate(${x.toFixed(1)}px, ${y.toFixed(1)}px)`;
    });
  };

  /** The player under a pointer, if any, from the last placed frame. `rect` is the layer's box on screen. */
  const hit = (e: { clientX: number; clientY: number; pointerType?: string }, rect: DOMRect): number => {
    const f = last.current;
    if (!f?.u) return -1;
    const x = (e.clientX - rect.left) / f.u - 30;
    const y = (e.clientY - rect.top) / f.u - 30;
    let best = -1;
    let bestD: number = e.pointerType === 'touch' ? REACH.touch : REACH.mouse;
    f.players.forEach((p, i) => {
      if (!p) return;
      const d = Math.hypot(p[0] - x, p[1] - y);
      if (d < bestD) {
        bestD = d;
        best = i;
      }
    });
    return best;
  };

  /** Forget cached placements, after a resize or a new view. */
  const reset = () => {
    placed.current.clear();
    targets.current.length = 0;
  };

  return {
    active,
    setActive,
    focused,
    setFocused,
    hovered,
    setHovered,
    /** The player whose name shows: focused, else hovered. */
    hintId: focused?.id ?? hovered,
    /** The player with a visible keyboard focus ring. */
    ringId: focused?.visible ? focused.id : null,
    buttons,
    fonts,
    specs,
    last,
    keep,
    place,
    hit,
    reset,
  };
}

export type PitchLayerState = ReturnType<typeof usePitchLayer>;

/** The labels and stat cards. They render hidden and the stage's frame loop places them before they paint. */
export function PitchLabels({ layer, labels, pins, lang }: { layer: PitchLayerState; labels: readonly LabelSpec[]; pins: readonly PinSpec[]; lang: Lang }) {
  layer.specs.current = { labels: [...labels], pins: [...pins] };
  const spoken = labels.some((l) => !l.decorative) || pins.length > 0;
  return (
    // The pitch stays left to right, but its labels read in the viewer's direction (PRD 15.3).
    <div className="pitch-labels" dir={isRtl(lang) ? 'rtl' : 'ltr'} role={spoken ? 'list' : undefined} aria-label={spoken ? 'On the pitch' : undefined}>
      {labels.map((l) => (
        <div key={l.key} ref={layer.keep(l.key)} className="pitch-label" data-kind={l.kind} data-player={l.anchor.kind === 'player' ? l.anchor.id : undefined} role={l.decorative ? undefined : 'listitem'} aria-hidden={l.decorative || undefined} style={{ visibility: 'hidden' }}>
          <span className={cx('pitch-label-text', `tone-${l.tone}`, l.anim && `anim-${l.anim}`, l.late && 'is-late', l.mono && 'is-mono', l.retracted && 'is-retracted')} data-align={l.align} style={{ '--size': l.size } as CSSProperties}>
            {l.text}
          </span>
        </div>
      ))}
      {pins.map((p) => (
        <div key={p.key} ref={layer.keep(p.key)} className="pitch-label" data-kind="stat_card" role="listitem" style={{ visibility: 'hidden' }}>
          <div className="stat-pin anim-rise">
            <span className="stat-pin-title">{p.title}</span>
            <span className="stat-pin-value">{p.value}</span>
          </div>
        </div>
      ))}
    </div>
  );
}

/** A focusable button per player: arrow keys move between them, Home and End jump to the ends, Enter follows. */
export function PlayerTargets({ layer, mode, fav, onFollow }: { layer: PitchLayerState; mode: Mode; fav: string; onFollow: (id: string) => void }) {
  const { active, setActive, setFocused, buttons } = layer;
  const move = (to: number) => {
    const n = PLAYERS.length;
    const i = ((to % n) + n) % n;
    setActive(i);
    buttons.current[i]?.focus();
  };
  const onKeyDown = (i: number) => (e: KeyboardEvent<HTMLButtonElement>) => {
    const half = PLAYERS.length / 2;
    if (!['ArrowRight', 'ArrowLeft', 'ArrowUp', 'ArrowDown', 'Home', 'End', 'Enter', ' '].includes(e.key)) return;
    e.preventDefault();
    e.stopPropagation();
    if (e.key === 'ArrowRight') move(i + 1);
    if (e.key === 'ArrowLeft') move(i - 1);
    // Up and down switch teams, keeping the shirt number.
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') move(i < half ? i + half : i - half);
    if (e.key === 'Home') move(0);
    if (e.key === 'End') move(PLAYERS.length - 1);
    if (e.key === 'Enter' || e.key === ' ') onFollow(PLAYERS[i].id);
  };
  return (
    <div className="player-targets" role="group" aria-label="Players. Arrow keys move between players; Enter follows one.">
      {PLAYERS.map((p, i) => (
        <button
          key={p.id}
          ref={(el) => {
            buttons.current[i] = el;
          }}
          type="button"
          className="player-target"
          data-player={p.id}
          tabIndex={i === active ? 0 : -1}
          aria-label={mode === 'player' && p.id === fav ? `${playerLabel(p.id)}, followed` : playerLabel(p.id)}
          onFocus={(e) => {
            setActive(i);
            setFocused({ id: p.id, visible: e.currentTarget.matches(':focus-visible') });
          }}
          onBlur={() => setFocused((f) => (f?.id === p.id ? null : f))}
          onKeyDown={onKeyDown(i)}
        />
      ))}
    </div>
  );
}
