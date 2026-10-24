// Snapshots and data exports (PRD 16.8). Every export carries a "synthetic data" and "AI-generated" label.
export const EXPORT_LABEL = 'OffBall · synthetic data · AI-generated';

export function download(blob: Blob, name: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

const csvCell = (v: unknown) => {
  const s = String(v ?? '');
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
};

export function toCsv(columns: readonly string[], rows: readonly (readonly unknown[])[]): Blob {
  const lines = [`# ${EXPORT_LABEL}`, columns.map(csvCell).join(','), ...rows.map((r) => r.map(csvCell).join(','))];
  return new Blob([lines.join('\n') + '\n'], { type: 'text/csv;charset=utf-8' });
}

const STYLE_PROPS = [
  'fill',
  'fill-opacity',
  'stroke',
  'stroke-width',
  'stroke-dasharray',
  'stroke-linecap',
  'stroke-linejoin',
  'stroke-opacity',
  'opacity',
  'font-family',
  'font-size',
  'font-weight',
  'text-anchor',
  'dominant-baseline',
  'letter-spacing',
  'paint-order',
  'transform',
  'transform-origin',
  'visibility',
  'display',
];

/** Copies resolved styles onto a clone, so tokens and classes survive outside the app. */
export function inlineStyles(source: Element, target: Element): void {
  const cs = getComputedStyle(source);
  const style = STYLE_PROPS.map((p) => `${p}:${cs.getPropertyValue(p)}`).join(';');
  target.setAttribute('style', style);
  target.removeAttribute('class');
  const s = source.children;
  const t = target.children;
  for (let i = 0; i < s.length; i++) inlineStyles(s[i], t[i]);
}

/** A standalone copy of any SVG chart, with the export label underneath. */
export function snapshotSvg(svg: SVGSVGElement): SVGSVGElement {
  const clone = svg.cloneNode(true) as SVGSVGElement;
  inlineStyles(svg, clone);
  const ns = 'http://www.w3.org/2000/svg';
  clone.setAttribute('xmlns', ns);
  const box = svg.viewBox.baseVal;
  const vb = box && box.width ? box : { x: 0, y: 0, width: svg.clientWidth || 600, height: svg.clientHeight || 300 };
  clone.setAttribute('viewBox', `${vb.x} ${vb.y} ${vb.width} ${vb.height + 24}`);
  clone.setAttribute('width', String(vb.width));
  clone.setAttribute('height', String(vb.height + 24));
  const label = document.createElementNS(ns, 'text');
  label.setAttribute('x', String(vb.x + 4));
  label.setAttribute('y', String(vb.y + vb.height + 17));
  label.setAttribute('font-family', 'Inter, sans-serif');
  label.setAttribute('font-size', '11');
  label.setAttribute('fill', getComputedStyle(svg).getPropertyValue('--muted').trim() || 'gray');
  label.textContent = EXPORT_LABEL;
  clone.append(label);
  return clone;
}

export const svgBlob = (svg: SVGSVGElement) => new Blob([new XMLSerializer().serializeToString(svg)], { type: 'image/svg+xml' });

export function pngBlob(svg: SVGSVGElement, scale = 2): Promise<Blob> {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(svgBlob(svg));
    const img = new Image();
    img.onload = () => {
      const w = Number(svg.getAttribute('width')) || img.width;
      const h = Number(svg.getAttribute('height')) || img.height;
      const canvas = document.createElement('canvas');
      canvas.width = Math.round(w * scale);
      canvas.height = Math.round(h * scale);
      const ctx = canvas.getContext('2d');
      if (!ctx) return reject(new Error('No canvas'));
      ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
      URL.revokeObjectURL(url);
      canvas.toBlob((b) => (b ? resolve(b) : reject(new Error('PNG failed'))), 'image/png');
    };
    img.onerror = () => reject(new Error('Image failed'));
    img.src = url;
  });
}

/** Shares a file where the browser can (phones), otherwise downloads it. */
export async function shareOrDownload(blob: Blob, name: string, text: string): Promise<'shared' | 'downloaded'> {
  const file = new File([blob], name, { type: blob.type });
  const nav = navigator as Navigator & { canShare?: (d: ShareData) => boolean };
  if (nav.share && nav.canShare?.({ files: [file] })) {
    try {
      await nav.share({ files: [file], text });
      return 'shared';
    } catch {
      // Cancelled: fall through to a download.
    }
  }
  download(blob, name);
  return 'downloaded';
}
