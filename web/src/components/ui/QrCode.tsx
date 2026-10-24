import { useMemo } from 'react';
import { encode } from 'uqr';

/** A QR code as SVG: dark modules on a light quiet zone in every theme, so any phone camera can read it. */
export function QrCode({ value, size = 168, label }: { value: string; size?: number; label: string }) {
  const qr = useMemo(() => encode(value, { ecc: 'M', border: 2 }), [value]);
  const n = qr.size;
  let d = '';
  qr.data.forEach((row, y) =>
    row.forEach((on, x) => {
      if (on) d += `M${x} ${y}h1v1h-1z`;
    }),
  );
  return (
    <svg className="qr" viewBox={`0 0 ${n} ${n}`} width={size} height={size} role="img" aria-label={label} shapeRendering="crispEdges">
      <rect width={n} height={n} className="qr-bg" />
      <path d={d} className="qr-fg" />
    </svg>
  );
}
