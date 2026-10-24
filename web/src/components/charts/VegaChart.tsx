import { useEffect, useRef, useState } from 'react';
import { usePrefs } from '../../lib/prefs';
import { Skeleton } from '../ui';

export type VegaLiteSpec = Record<string, unknown>;

const token = (el: Element, name: string, fallback: string) => getComputedStyle(el).getPropertyValue(name).trim() || fallback;

/**
 * Which colours a chart's series take: the two clubs' first, for match charts, or the accent and a neutral first, for
 * measures that aren't about a club (evaluation charts), so a club's colour never stands for something else.
 */
export type Palette = 'teams' | 'measures';

/** The client themes every declarative spec (VIS-7): colours, type and gridlines come from the viewer's tokens. */
function themeConfig(el: Element, palette: Palette) {
  const text = token(el, '--text', '#ecf1ec');
  const muted = token(el, '--muted', '#9eb0a6');
  const line = token(el, '--line', '#27362f');
  const font = 'Inter, system-ui, sans-serif';
  return {
    background: null,
    font,
    view: { stroke: null },
    padding: 4,
    axis: { labelColor: muted, titleColor: muted, gridColor: line, domainColor: line, tickColor: line, labelFont: font, titleFont: font, labelFontSize: 11, titleFontSize: 11, titleFontWeight: 600 },
    legend: { labelColor: text, titleColor: muted, labelFont: font, titleFont: font, labelFontSize: 11, titleFontSize: 11, orient: 'bottom', symbolStrokeWidth: 2 },
    title: { color: text, font },
    header: { labelColor: text, titleColor: muted },
    text: { color: text, font },
    range: { category: palette === 'teams' ? [token(el, '--kes', '#7cc0ff'), token(el, '--ash', '#e2733a'), token(el, '--space', '#d7f25c'), muted] : [token(el, '--space', '#d7f25c'), muted, token(el, '--kes', '#7cc0ff'), token(el, '--ash', '#e2733a')] },
    line: { strokeWidth: 2.5 },
    point: { filled: true, size: 60 },
    bar: { cornerRadiusEnd: 3 },
    mark: { color: palette === 'teams' ? token(el, '--kes', '#7cc0ff') : token(el, '--space', '#d7f25c') },
    rule: { color: muted },
  };
}

/**
 * Renders a Vega-Lite spec (PRD 16.4). Vega loads on demand, so it never weighs on the first frame (PRD 16.7);
 * a skeleton holds the space meanwhile. The chart's text summary and table live in ChartFrame.
 */
export function VegaChart({ spec, label, height = 180, palette = 'teams' }: { spec: VegaLiteSpec; label: string; height?: number; palette?: Palette }) {
  const host = useRef<HTMLDivElement>(null);
  const { prefs } = usePrefs();
  const [state, setState] = useState<'loading' | 'ready' | 'error'>('loading');
  const key = JSON.stringify(spec);

  useEffect(() => {
    let alive = true;
    let finalize: (() => void) | null = null;
    const el = host.current;
    if (!el) return;
    setState('loading');
    import('vega-embed')
      .then(async ({ default: embed }) => {
        if (!alive) return;
        const full = { ...(JSON.parse(key) as VegaLiteSpec), width: 'container', height, autosize: { type: 'fit', contains: 'padding' }, config: themeConfig(el, palette) };
        const result = await embed(el, full as never, { actions: false, renderer: 'svg' });
        if (!alive) {
          result.finalize();
          return;
        }
        // The host carries the chart's name; its summary and table live in ChartFrame, so Vega's own SVG roles stay out of
        // the way. Vega labels its container "Vega visualization", so the host's own name goes back on (see below).
        el.querySelector('svg')?.setAttribute('aria-hidden', 'true');
        finalize = () => result.finalize();
        setState('ready');
      })
      .catch(() => alive && setState('error'));
    return () => {
      alive = false;
      finalize?.();
    };
  }, [key, height, prefs.theme, palette]);

  // Vega names the element it draws into; this chart's own name is the one screen readers should hear.
  useEffect(() => {
    const el = host.current;
    if (!el) return;
    el.setAttribute('role', 'img');
    el.setAttribute('aria-label', label);
    el.removeAttribute('aria-roledescription');
  }, [label, state]);

  return (
    <div className="vega-wrap" style={{ position: 'relative' }}>
      <div ref={host} className="vega-host" role="img" aria-label={label} style={{ minHeight: height }} />
      {state === 'loading' && (
        <div style={{ position: 'absolute', inset: 0 }}>
          <Skeleton height={height} radius={8} />
        </div>
      )}
      {state === 'error' && <p className="muted" style={{ fontSize: 13 }}>The chart couldn’t load. Its data is in the table view.</p>}
    </div>
  );
}
