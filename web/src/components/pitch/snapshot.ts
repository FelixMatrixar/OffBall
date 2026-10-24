// Snapshots of the pitch (PRD 16.8): the picture as drawn, with its labels, as a PNG, or for the 2D view an SVG whose
// shapes and words stay vectors. Each stage hands back its own picture; `composeSnapshot` lays out one or two (the
// side-by-side what-if) and adds the label every export carries.
import { EXPORT_LABEL, inlineStyles } from '../../lib/export';

export type SnapshotFormat = 'png' | 'svg';

/** One stage's picture, `width` × `height` CSS pixels: a canvas at the export scale for PNG, or SVG markup for SVG. */
export interface StageShot {
  width: number;
  height: number;
  canvas?: HTMLCanvasElement;
  svg?: string;
}

/** What a stage offers: its picture now, in a format it supports. */
export interface Snapshotter {
  formats: readonly SnapshotFormat[];
  take: (format: SnapshotFormat, scale: number) => Promise<StageShot>;
}

const NS = 'http://www.w3.org/2000/svg';
const TAU = Math.PI * 2;

const esc = (s: string) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
const n = (v: number) => (Math.round(v * 100) / 100).toString();

let probe: CanvasRenderingContext2D | null = null;
const probeCtx = () => (probe ??= document.createElement('canvas').getContext('2d'));

/** A CSS colour as #rrggbb and an alpha, which every SVG reader understands. Unknown syntax passes through. */
function paint(css: string): { hex: string; alpha: number } {
  const ctx = probeCtx();
  if (!ctx) return { hex: css, alpha: 1 };
  // A known value first, so an unparseable colour reads back as it rather than the last one parsed.
  ctx.fillStyle = '#000'; // tokens-ok: a parser reset, never drawn
  ctx.fillStyle = css;
  const v = String(ctx.fillStyle);
  if (v.startsWith('#')) return { hex: v, alpha: 1 };
  const m = /rgba?\(([^)]+)\)/.exec(v);
  if (!m) return { hex: v, alpha: 1 };
  const [r, g, b, a = 1] = m[1].split(/[\s,/]+/).filter(Boolean).map(Number);
  const hex = `#${[r, g, b].map((c) => Math.round(c).toString(16).padStart(2, '0')).join('')}`;
  return { hex, alpha: a };
}

const transparent = (css: string) => paint(css).alpha <= 0.001;

type Matrix = [number, number, number, number, number, number];

interface CtxState {
  m: Matrix;
  globalAlpha: number;
  lineWidth: number;
  lineCap: CanvasLineCap;
  lineJoin: CanvasLineJoin;
  strokeStyle: string;
  fillStyle: string;
  font: string;
  textAlign: CanvasTextAlign;
  textBaseline: CanvasTextBaseline;
  dash: number[];
}

/**
 * The part of the canvas API the 2D renderer uses, recorded as SVG elements instead of pixels: paths, arcs, dashes,
 * transforms, alpha and text. The renderer draws a still into it exactly as it draws into the canvas on the page.
 */
export class SvgContext {
  readonly canvas: { width: number; height: number };
  globalAlpha = 1;
  lineWidth = 1;
  lineCap: CanvasLineCap = 'butt';
  lineJoin: CanvasLineJoin = 'miter';
  strokeStyle = '#000'; // tokens-ok: the canvas API's default, which the renderer always sets
  fillStyle = '#000'; // tokens-ok: the canvas API's default, which the renderer always sets
  font = '10px sans-serif';
  textAlign: CanvasTextAlign = 'start';
  textBaseline: CanvasTextBaseline = 'alphabetic';
  private m: Matrix = [1, 0, 0, 1, 0, 0];
  private dash: number[] = [];
  private stack: CtxState[] = [];
  private d = '';
  private open = false;
  private readonly out: string[] = [];

  constructor(width: number, height: number) {
    this.canvas = { width, height };
  }

  /** The recorded drawing, as SVG elements. */
  markup(): string {
    return this.out.join('');
  }

  save(): void {
    const { globalAlpha, lineWidth, lineCap, lineJoin, strokeStyle, fillStyle, font, textAlign, textBaseline } = this;
    this.stack.push({ m: [...this.m], globalAlpha, lineWidth, lineCap, lineJoin, strokeStyle, fillStyle, font, textAlign, textBaseline, dash: [...this.dash] });
  }
  restore(): void {
    const s = this.stack.pop();
    if (!s) return;
    this.m = s.m;
    this.dash = s.dash;
    Object.assign(this, { globalAlpha: s.globalAlpha, lineWidth: s.lineWidth, lineCap: s.lineCap, lineJoin: s.lineJoin, strokeStyle: s.strokeStyle, fillStyle: s.fillStyle, font: s.font, textAlign: s.textAlign, textBaseline: s.textBaseline });
  }
  setTransform(a: number, b: number, c: number, d: number, e: number, f: number): void {
    this.m = [a, b, c, d, e, f];
  }
  translate(x: number, y: number): void {
    const [a, b, c, d, e, f] = this.m;
    this.m = [a, b, c, d, e + a * x + c * y, f + b * x + d * y];
  }
  scale(x: number, y: number): void {
    const [a, b, c, d, e, f] = this.m;
    this.m = [a * x, b * x, c * y, d * y, e, f];
  }
  setLineDash(segments: number[]): void {
    this.dash = [...segments];
  }
  getLineDash(): number[] {
    return [...this.dash];
  }
  /** A snapshot starts empty, so clearing has nothing to do. */
  clearRect(): void {}
  /** Bitmaps aren't drawn: a still draws its shirt numbers as text. */
  drawImage(): void {}

  beginPath(): void {
    this.d = '';
    this.open = false;
  }
  private pt(x: number, y: number): [number, number] {
    const [a, b, c, d, e, f] = this.m;
    return [a * x + c * y + e, b * x + d * y + f];
  }
  /** The current transform's scale, for line widths, dashes and font sizes. */
  private k(): number {
    const [a, b, c, d] = this.m;
    return Math.sqrt(Math.abs(a * d - b * c)) || 1;
  }
  moveTo(x: number, y: number): void {
    const [px, py] = this.pt(x, y);
    this.d += `M${n(px)} ${n(py)}`;
    this.open = true;
  }
  lineTo(x: number, y: number): void {
    const [px, py] = this.pt(x, y);
    this.d += `${this.open ? 'L' : 'M'}${n(px)} ${n(py)}`;
    this.open = true;
  }
  quadraticCurveTo(cpx: number, cpy: number, x: number, y: number): void {
    // As on a canvas, a curve with no current point starts at its control point.
    if (!this.open) this.moveTo(cpx, cpy);
    const [qx, qy] = this.pt(cpx, cpy);
    const [px, py] = this.pt(x, y);
    this.d += `Q${n(qx)} ${n(qy)} ${n(px)} ${n(py)}`;
  }
  closePath(): void {
    this.d += 'Z';
  }
  arc(x: number, y: number, r: number, start: number, end: number, ccw = false): void {
    this.ellipse(x, y, r, r, 0, start, end, ccw);
  }
  ellipse(x: number, y: number, rx: number, ry: number, rot: number, start: number, end: number, ccw = false): void {
    // How far to sweep, as the canvas does: a full turn or more is the whole ellipse.
    let sweep = ccw ? start - end : end - start;
    sweep = sweep >= TAU ? TAU : ((sweep % TAU) + TAU) % TAU;
    const dir = ccw ? -1 : 1;
    const cos = Math.cos(rot);
    const sin = Math.sin(rot);
    const at = (angle: number) => {
      const ex = rx * Math.cos(angle);
      const ey = ry * Math.sin(angle);
      return this.pt(x + ex * cos - ey * sin, y + ex * sin + ey * cos);
    };
    const [sx, sy] = at(start);
    this.d += `${this.open ? 'L' : 'M'}${n(sx)} ${n(sy)}`;
    this.open = true;
    if (sweep === 0) return;
    const [a, b, c, d] = this.m;
    const kx = Math.hypot(a, b);
    const ky = Math.hypot(c, d);
    const turn = ((rot + Math.atan2(b, a)) * 180) / Math.PI;
    const flag = (ccw ? 0 : 1) ^ (a * d - b * c < 0 ? 1 : 0);
    // Arcs of under half a turn each, so the large-arc flag is never in doubt.
    const parts = Math.max(1, Math.ceil(sweep / (Math.PI * 0.999)));
    for (let i = 1; i <= parts; i++) {
      const [px, py] = at(start + (dir * sweep * i) / parts);
      this.d += `A${n(rx * kx)} ${n(ry * ky)} ${n(turn)} 0 ${flag} ${n(px)} ${n(py)}`;
    }
  }
  fill(): void {
    if (!this.d) return;
    const { hex, alpha } = paint(this.fillStyle);
    const a = alpha * this.globalAlpha;
    if (a <= 0.002) return;
    this.out.push(`<path d="${this.d}" fill="${esc(hex)}"${a < 1 ? ` fill-opacity="${n(a)}"` : ''}/>`);
  }
  stroke(): void {
    if (!this.d) return;
    const { hex, alpha } = paint(this.strokeStyle);
    const a = alpha * this.globalAlpha;
    if (a <= 0.002) return;
    const k = this.k();
    const attrs = [`d="${this.d}"`, 'fill="none"', `stroke="${esc(hex)}"`, `stroke-width="${n(this.lineWidth * k)}"`];
    if (a < 1) attrs.push(`stroke-opacity="${n(a)}"`);
    if (this.lineCap !== 'butt') attrs.push(`stroke-linecap="${this.lineCap}"`);
    if (this.lineJoin !== 'miter') attrs.push(`stroke-linejoin="${this.lineJoin}"`);
    if (this.dash.length) attrs.push(`stroke-dasharray="${this.dash.map((v) => n(v * k)).join(' ')}"`);
    this.out.push(`<path ${attrs.join(' ')}/>`);
  }
  fillText(text: string, x: number, y: number): void {
    const { hex, alpha } = paint(this.fillStyle);
    const a = alpha * this.globalAlpha;
    if (a <= 0.002) return;
    const font = /^\s*(?:(normal|italic)\s+)?(\d{3}|bold|normal)?\s*([\d.]+)px\s+(.+)$/.exec(this.font);
    const weight = font?.[2] ?? '400';
    const size = Number(font?.[3] ?? 10) * this.k();
    const family = font?.[4] ?? 'sans-serif';
    const [px, py] = this.pt(x, y);
    const anchor = this.textAlign === 'center' ? 'middle' : this.textAlign === 'right' || this.textAlign === 'end' ? 'end' : 'start';
    const baseline = this.textBaseline === 'middle' ? ' dominant-baseline="central"' : this.textBaseline === 'top' ? ' dominant-baseline="hanging"' : '';
    this.out.push(`<text x="${n(px)}" y="${n(py)}" font-family="${esc(family)}" font-weight="${weight}" font-size="${n(size)}" text-anchor="${anchor}"${baseline} fill="${esc(hex)}"${a < 1 ? ` fill-opacity="${n(a)}"` : ''}>${esc(text)}</text>`);
  }
}

/** Where a painter puts a box or a line of text, in output pixels. */
interface Painter {
  box(x: number, y: number, w: number, h: number, radius: number, fill: string | null, border: { width: number; colour: string } | null, opacity: number): void;
  text(t: string, centreX: number, baseline: number, s: TextStyle): void;
}

interface TextStyle {
  font: string;
  family: string;
  weight: string;
  size: number;
  colour: string;
  halo: { width: number; colour: string } | null;
  letterSpacing: number;
  dir: 'ltr' | 'rtl';
  opacity: number;
}

function canvasPainter(ctx: CanvasRenderingContext2D): Painter {
  return {
    box(x, y, w, h, radius, fill, border, opacity) {
      ctx.save();
      ctx.globalAlpha = opacity;
      ctx.beginPath();
      ctx.roundRect(x, y, w, h, radius);
      if (fill) {
        ctx.fillStyle = fill;
        ctx.fill();
      }
      if (border) {
        ctx.lineWidth = border.width;
        ctx.strokeStyle = border.colour;
        ctx.stroke();
      }
      ctx.restore();
    },
    text(t, cx, baseline, s) {
      ctx.save();
      ctx.globalAlpha = s.opacity;
      ctx.font = s.font;
      ctx.direction = s.dir;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'alphabetic';
      if ('letterSpacing' in ctx) (ctx as CanvasRenderingContext2D & { letterSpacing: string }).letterSpacing = `${s.letterSpacing}px`;
      if (s.halo) {
        ctx.lineJoin = 'round';
        ctx.lineWidth = s.halo.width;
        ctx.strokeStyle = s.halo.colour;
        ctx.strokeText(t, cx, baseline);
      }
      ctx.fillStyle = s.colour;
      ctx.fillText(t, cx, baseline);
      ctx.restore();
    },
  };
}

function svgPainter(out: string[]): Painter {
  return {
    box(x, y, w, h, radius, fill, border, opacity) {
      const f = fill ? paint(fill) : null;
      const b = border ? paint(border.colour) : null;
      const attrs = [`x="${n(x)}"`, `y="${n(y)}"`, `width="${n(w)}"`, `height="${n(h)}"`, `rx="${n(radius)}"`];
      attrs.push(f ? `fill="${esc(f.hex)}"${f.alpha < 1 ? ` fill-opacity="${n(f.alpha)}"` : ''}` : 'fill="none"');
      if (b && border) attrs.push(`stroke="${esc(b.hex)}" stroke-width="${n(border.width)}"${b.alpha < 1 ? ` stroke-opacity="${n(b.alpha)}"` : ''}`);
      if (opacity < 1) attrs.push(`opacity="${n(opacity)}"`);
      out.push(`<rect ${attrs.join(' ')}/>`);
    },
    text(t, cx, baseline, s) {
      const c = paint(s.colour);
      const attrs = [`x="${n(cx)}"`, `y="${n(baseline)}"`, `font-family="${esc(s.family)}"`, `font-weight="${esc(s.weight)}"`, `font-size="${n(s.size)}"`, 'text-anchor="middle"', `fill="${esc(c.hex)}"`];
      if (c.alpha < 1) attrs.push(`fill-opacity="${n(c.alpha)}"`);
      if (s.dir === 'rtl') attrs.push('direction="rtl"');
      if (s.letterSpacing) attrs.push(`letter-spacing="${n(s.letterSpacing)}"`);
      if (s.halo) {
        const h = paint(s.halo.colour);
        attrs.push(`stroke="${esc(h.hex)}" stroke-width="${n(s.halo.width)}" stroke-linejoin="round" paint-order="stroke"${h.alpha < 1 ? ` stroke-opacity="${n(h.alpha)}"` : ''}`);
      }
      if (s.opacity < 1) attrs.push(`opacity="${n(s.opacity)}"`);
      attrs.push('style="font-variant-numeric: tabular-nums"');
      out.push(`<text ${attrs.join(' ')}>${esc(t)}</text>`);
    },
  };
}

/**
 * Paints what's on screen in some DOM, such as the labels over a pitch: boxes with their backgrounds and borders, and
 * each line of text with its halo, at the place and size the browser laid them out. `origin` is the picture's box.
 */
function paintDom(p: Painter, roots: readonly Element[], origin: DOMRect, k: number): void {
  const ctx = probeCtx();
  const walk = (el: Element, alpha: number) => {
    const cs = getComputedStyle(el);
    if (cs.display === 'none') return;
    const a = alpha * Number(cs.opacity || 1);
    if (a <= 0.01) return;
    const shown = cs.visibility !== 'hidden';
    if (shown) {
      const r = el.getBoundingClientRect();
      const bw = parseFloat(cs.borderTopWidth) || 0;
      const fill = transparent(cs.backgroundColor) ? null : cs.backgroundColor;
      const border = bw > 0 && cs.borderTopStyle !== 'none' && !transparent(cs.borderTopColor) ? { width: bw * k, colour: cs.borderTopColor } : null;
      if ((fill || border) && r.width > 0 && r.height > 0) {
        const inset = border ? border.width / 2 : 0;
        p.box((r.left - origin.left) * k + inset, (r.top - origin.top) * k + inset, r.width * k - inset * 2, r.height * k - inset * 2, (parseFloat(cs.borderTopLeftRadius) || 0) * k, fill, border, a);
      }
    }
    for (const node of Array.from(el.childNodes)) {
      if (node.nodeType === Node.ELEMENT_NODE) {
        walk(node as Element, a);
        continue;
      }
      const text = node.nodeType === Node.TEXT_NODE ? (node.textContent ?? '').trim() : '';
      if (!text || !shown) continue;
      const range = document.createRange();
      range.selectNodeContents(node);
      const box = range.getBoundingClientRect();
      if (!box.width) continue;
      const size = parseFloat(cs.fontSize);
      const font = `${cs.fontStyle} ${cs.fontWeight} ${size}px ${cs.fontFamily}`;
      let ascent = size * 0.8;
      if (ctx) {
        ctx.font = font;
        const m = ctx.measureText(text);
        ascent = m.fontBoundingBoxAscent || ascent;
        // The inline box is the font's ascent plus descent; centre that on the laid-out box.
        const content = (m.fontBoundingBoxAscent || 0) + (m.fontBoundingBoxDescent || 0);
        if (content) ascent += (box.height - content) / 2;
      }
      const strokeWidth = parseFloat(cs.getPropertyValue('-webkit-text-stroke-width')) || 0;
      const strokeColour = cs.getPropertyValue('-webkit-text-stroke-color');
      p.text(text, ((box.left + box.right) / 2 - origin.left) * k, (box.top - origin.top + ascent) * k, {
        font: `${cs.fontStyle} ${cs.fontWeight} ${size * k}px ${cs.fontFamily}`,
        family: cs.fontFamily,
        weight: cs.fontWeight,
        size: size * k,
        colour: cs.color,
        halo: strokeWidth > 0 && !transparent(strokeColour) ? { width: strokeWidth * k, colour: strokeColour } : null,
        letterSpacing: (parseFloat(cs.letterSpacing) || 0) * k,
        dir: cs.direction === 'rtl' ? 'rtl' : 'ltr',
        opacity: a,
      });
    }
  };
  for (const root of roots) walk(root, 1);
}

export const paintDomToCanvas = (ctx: CanvasRenderingContext2D, roots: readonly Element[], origin: DOMRect, k: number) => paintDom(canvasPainter(ctx), roots, origin, k);

export function paintDomToSvg(roots: readonly Element[], origin: DOMRect): string {
  const out: string[] = [];
  paintDom(svgPainter(out), roots, origin, 1);
  return out.join('');
}

/** An SVG on the page as standalone markup, its styles resolved, placed at `box` (CSS pixels) in the picture. */
export function svgCopy(svg: SVGSVGElement, box: { x: number; y: number; w: number; h: number }): string {
  const clone = svg.cloneNode(true) as SVGSVGElement;
  inlineStyles(svg, clone);
  clone.setAttribute('xmlns', NS);
  clone.setAttribute('x', n(box.x));
  clone.setAttribute('y', n(box.y));
  clone.setAttribute('width', n(box.w));
  clone.setAttribute('height', n(box.h));
  for (const a of ['role', 'aria-label', 'class']) clone.removeAttribute(a);
  return new XMLSerializer().serializeToString(clone);
}

/** Draws SVG markup into a canvas, at `box` in the canvas's current units. */
export async function drawSvgMarkup(ctx: CanvasRenderingContext2D, markup: string, box: { x: number; y: number; w: number; h: number }): Promise<void> {
  const url = URL.createObjectURL(new Blob([markup], { type: 'image/svg+xml' }));
  try {
    const img = new Image();
    img.src = url;
    await img.decode();
    ctx.drawImage(img, box.x, box.y, box.w, box.h);
  } finally {
    URL.revokeObjectURL(url);
  }
}

/** A small bitmap scaled up smoothly, as the browser shows it, so viewers that scale images blockily still see a surface. */
export function smoothCopy(source: CanvasImageSource, w: number, h: number): HTMLCanvasElement {
  const c = document.createElement('canvas');
  c.width = Math.max(1, Math.round(w));
  c.height = Math.max(1, Math.round(h));
  const ctx = c.getContext('2d');
  if (ctx) {
    ctx.imageSmoothingEnabled = true;
    ctx.imageSmoothingQuality = 'high';
    ctx.drawImage(source, 0, 0, c.width, c.height);
  }
  return c;
}

const TITLE_H = 34;
const FOOTER_H = 40;
const GAP = 16;

/**
 * One file from one or more stage pictures, side by side with their titles, and a footer: the export label, then
 * what the picture shows (the match clock, the mode). Theme colours come from the page.
 */
export async function composeSnapshot(parts: readonly { shot: StageShot; title?: string }[], format: SnapshotFormat, scale: number, caption: string): Promise<Blob> {
  const cs = getComputedStyle(document.documentElement);
  const v = (name: string, fallback: string) => cs.getPropertyValue(name).trim() || fallback;
  const bg = v('--bg', '#0b1110');
  const text = v('--text', '#ecf1ec');
  const muted = v('--muted', '#9eb0a6');
  const font = v('--font-body', 'system-ui, sans-serif');
  const titled = parts.some((p) => p.title);
  const top = titled ? TITLE_H : 0;
  const width = parts.reduce((w, p) => w + p.shot.width, 0) + GAP * (parts.length - 1);
  const height = top + Math.max(...parts.map((p) => p.shot.height)) + FOOTER_H;
  const footer = `${EXPORT_LABEL} · ${caption}`;

  if (format === 'svg') {
    const out: string[] = [`<svg xmlns="${NS}" width="${n(width)}" height="${n(height)}" viewBox="0 0 ${n(width)} ${n(height)}">`];
    out.push(`<title>${esc(footer)}</title>`);
    out.push(`<rect width="${n(width)}" height="${n(height)}" fill="${esc(paint(bg).hex)}"/>`);
    let x = 0;
    for (const { shot, title } of parts) {
      if (title) out.push(`<text x="${n(x + 4)}" y="${n(TITLE_H - 12)}" font-family="${esc(font)}" font-weight="700" font-size="15" fill="${esc(paint(text).hex)}">${esc(title)}</text>`);
      out.push(`<g transform="translate(${n(x)} ${n(top)})">${shot.svg ?? ''}</g>`);
      x += shot.width + GAP;
    }
    const m = paint(muted);
    out.push(`<text x="4" y="${n(height - 14)}" font-family="${esc(font)}" font-weight="600" font-size="14" fill="${esc(m.hex)}"${m.alpha < 1 ? ` fill-opacity="${n(m.alpha)}"` : ''}>${esc(footer)}</text>`);
    out.push('</svg>');
    return new Blob([out.join('')], { type: 'image/svg+xml' });
  }

  const canvas = document.createElement('canvas');
  canvas.width = Math.round(width * scale);
  canvas.height = Math.round(height * scale);
  const ctx = canvas.getContext('2d');
  if (!ctx) throw new Error('No canvas for the snapshot');
  ctx.fillStyle = bg;
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.scale(scale, scale);
  let x = 0;
  for (const { shot, title } of parts) {
    if (title) {
      ctx.fillStyle = text;
      ctx.font = `700 15px ${font}`;
      ctx.fillText(title, x + 4, TITLE_H - 12);
    }
    if (shot.canvas) ctx.drawImage(shot.canvas, x, top, shot.width, shot.height);
    x += shot.width + GAP;
  }
  ctx.fillStyle = muted;
  ctx.font = `600 14px ${font}`;
  ctx.fillText(footer, 4, height - 14);
  return new Promise((resolve, reject) => canvas.toBlob((b) => (b ? resolve(b) : reject(new Error('The snapshot could not be encoded'))), 'image/png'));
}
