// Shareable player cards (PRD 10.8, 16.8): a 1080 × 1350 PNG drawn on a canvas in the brand's dark theme, carrying
// the synthetic-data and AI-generated label like every export.
import { focusStats, LEADERS } from './content';
import { EXPORT_LABEL } from './export';
import { CLUBS, player, type XY } from './match';
import { runMap } from './stats';

export const CARD_SIZE = { width: 1080, height: 1350 } as const;

/** The dark theme's tokens, read from a probe so the card looks the same in any theme the viewer uses. */
function darkTokens(): (name: string, fallback: string) => string {
  const probe = document.createElement('div');
  probe.dataset.theme = 'dark';
  probe.hidden = true;
  document.body.append(probe);
  const cs = getComputedStyle(probe);
  const values = new Map<string, string>();
  for (const name of ['--bg', '--surface', '--surface-2', '--line', '--text', '--muted', '--kes', '--ash', '--on-kes', '--on-ash', '--space', '--pitch', '--stripe', '--chalk', '--font-body', '--font-display']) values.set(name, cs.getPropertyValue(name).trim());
  probe.remove();
  return (name, fallback) => values.get(name) || fallback;
}

export interface CardText {
  name: string;
  /** Read aloud in place of the image, and used as its alt text. */
  alt: string;
}

/** What the card says, as text: its alt text, so the image is never the only way to read it. */
export function cardText(id: string, spoilerSafe: boolean): CardText {
  const p = player(id);
  const s = focusStats(id);
  const lead = LEADERS.find((l) => l.id === id);
  const space = lead ? `${lead.v} m² of space created (90% interval ${lead.lo}–${lead.hi})` : `${s.space[1]} m² of space created`;
  const decoys = s.runsByType.find((r) => r.type === 'Decoy')?.n ?? 0;
  const name = `No. ${p.num} ${p.name}`;
  const alt = `Player card: ${name}, ${CLUBS[p.team].name}. ${space}; ${s.runs[1]} off-ball runs, ${decoys} of them decoys; ${s.dragged[1]} defenders dragged; top speed ${s.topSpeed} km/h; ${s.distanceKm} km covered.${spoilerSafe ? '' : ` ${s.season}`} ${EXPORT_LABEL}.`;
  return { name, alt };
}

/**
 * Waits for the page's web fonts, but not for ever: a slow font network shouldn't hold up a card. Anything drawn
 * before they arrive is drawn again when they do (see RecapView).
 */
export function fontsSettled(timeout = 2500): Promise<void> {
  return Promise.race([document.fonts.ready.then(() => undefined), new Promise<void>((resolve) => setTimeout(resolve, timeout))]);
}

/** Draws a player's card, in whatever fonts have loaded: call `fontsSettled` first. */
export function drawPlayerCard(id: string, spoilerSafe: boolean): HTMLCanvasElement {
  const { width: W, height: H } = CARD_SIZE;
  const canvas = document.createElement('canvas');
  canvas.width = W;
  canvas.height = H;
  const ctx = canvas.getContext('2d')!;
  const t = darkTokens();
  const p = player(id);
  const s = focusStats(id);
  const lead = LEADERS.find((l) => l.id === id);
  const team = p.team === 'kes' ? t('--kes', '#7cc0ff') : t('--ash', '#e2733a');
  const onTeam = p.team === 'kes' ? t('--on-kes', '#06121f') : t('--on-ash', '#1e0c02');
  const body = t('--font-body', 'system-ui, sans-serif');
  const display = t('--font-display', body);
  const text = t('--text', '#ecf1ec');
  const muted = t('--muted', '#9eb0a6');

  ctx.fillStyle = t('--bg', '#0b1110');
  ctx.fillRect(0, 0, W, H);
  ctx.fillStyle = team;
  ctx.fillRect(0, 0, W, 14);

  // Header: what this is, and whose.
  ctx.fillStyle = muted;
  ctx.font = `700 26px ${body}`;
  ctx.fillText('OFFBALL · PLAYER CARD', 72, 92);
  ctx.textAlign = 'right';
  ctx.fillText(`${CLUBS.kes.name.toUpperCase()} v ${CLUBS.ash.name.toUpperCase()}`, W - 72, 92);
  ctx.textAlign = 'left';

  // The shirt number and name.
  ctx.fillStyle = team;
  ctx.beginPath();
  ctx.arc(142, 214, 70, 0, Math.PI * 2);
  ctx.fill();
  ctx.fillStyle = onTeam;
  ctx.font = `700 76px ${display}`;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText(String(p.num), 142, 220);
  ctx.textAlign = 'left';
  ctx.textBaseline = 'alphabetic';
  ctx.fillStyle = text;
  ctx.font = `700 72px ${display}`;
  ctx.fillText(p.name, 244, 218, W - 244 - 72);
  ctx.fillStyle = muted;
  ctx.font = `500 28px ${body}`;
  ctx.fillText(`${CLUBS[p.team].name} · ${p.role}`, 246, 264);

  // The numbers that matter off the ball.
  const decoys = s.runsByType.find((r) => r.type === 'Decoy')?.n ?? 0;
  const stats: [string, string, string?][] = [
    ['Space created', `${lead?.v ?? s.space[1]} m²`, lead ? `90% interval ${lead.lo}–${lead.hi}` : undefined],
    ['Defenders dragged', String(s.dragged[1])],
    ['Off-ball runs', String(s.runs[1]), `${decoys} decoy`],
    ['Top speed', `${s.topSpeed} km/h`],
    ['Distance', `${s.distanceKm} km`],
    ['Rank for space', lead ? `${LEADERS.indexOf(lead) + 1} of ${LEADERS.length}` : '—', lead ? 'in this match' : undefined],
  ];
  // Three rows of two: 318 to 686.
  stats.forEach(([label, value, note], i) => {
    const x = 72 + (i % 2) * 480;
    const y = 318 + Math.floor(i / 2) * 128;
    ctx.fillStyle = t('--surface', '#121b18');
    ctx.beginPath();
    ctx.roundRect(x, y, 456, 112, 18);
    ctx.fill();
    ctx.fillStyle = muted;
    ctx.font = `600 24px ${body}`;
    ctx.fillText(label, x + 26, y + 38);
    ctx.fillStyle = i === 0 ? t('--space', '#d7f25c') : text;
    ctx.font = `700 52px ${display}`;
    ctx.fillText(value, x + 26, y + 92);
    if (note) {
      ctx.fillStyle = muted;
      ctx.font = `500 21px ${body}`;
      ctx.textAlign = 'right';
      ctx.fillText(note, x + 430, y + 92);
      ctx.textAlign = 'left';
    }
  });

  // The run map, where this player ran without the ball: centred, 772 to 1251, above its legend and the label.
  const mapW = 740;
  const mapH = (mapW * 68) / 105;
  const mapX = (W - mapW) / 2;
  const mapY = 772;
  const M = ([x, y]: XY): XY => [mapX + (x / 105) * mapW, mapY + ((68 - y) / 68) * mapH];
  for (let i = 0; i < 10; i++) {
    ctx.fillStyle = i % 2 ? t('--stripe', '#173624') : t('--pitch', '#14301f');
    ctx.fillRect(mapX + (i * mapW) / 10, mapY, mapW / 10 + 1, mapH);
  }
  ctx.strokeStyle = t('--chalk', 'rgb(236 241 236 / 0.45)');
  ctx.lineWidth = 2;
  ctx.strokeRect(mapX, mapY, mapW, mapH);
  ctx.beginPath();
  ctx.moveTo(mapX + mapW / 2, mapY);
  ctx.lineTo(mapX + mapW / 2, mapY + mapH);
  ctx.stroke();
  ctx.strokeStyle = team;
  ctx.fillStyle = team;
  ctx.lineWidth = 6;
  ctx.lineCap = 'round';
  for (const run of runMap(id)) {
    const [ax, ay] = M(run.from);
    const [bx, by] = M(run.to);
    ctx.setLineDash(run.type === 'Decoy' ? [] : [14, 10]);
    ctx.beginPath();
    ctx.moveTo(ax, ay);
    ctx.lineTo(bx, by);
    ctx.stroke();
    ctx.setLineDash([]);
    const a = Math.atan2(by - ay, bx - ax);
    ctx.beginPath();
    ctx.moveTo(bx + Math.cos(a) * 14, by + Math.sin(a) * 14);
    ctx.lineTo(bx + Math.cos(a + 2.5) * 16, by + Math.sin(a + 2.5) * 16);
    ctx.lineTo(bx + Math.cos(a - 2.5) * 16, by + Math.sin(a - 2.5) * 16);
    ctx.fill();
  }
  ctx.fillStyle = muted;
  ctx.font = `500 22px ${body}`;
  ctx.fillText('Runs this match: solid for decoy runs, dashed for the rest', mapX, mapY + mapH + 30);

  // The season line, unless the recap is spoiler-safe; then the label every export carries.
  ctx.fillStyle = text;
  ctx.font = `500 28px ${body}`;
  if (!spoilerSafe) ctx.fillText(s.season, 72, 738, W - 144);
  ctx.fillStyle = muted;
  ctx.font = `600 24px ${body}`;
  ctx.fillText(EXPORT_LABEL, 72, H - 26);
  return canvas;
}

export async function cardBlob(id: string, spoilerSafe: boolean): Promise<Blob> {
  await fontsSettled();
  return new Promise((resolve, reject) => drawPlayerCard(id, spoilerSafe).toBlob((b) => (b ? resolve(b) : reject(new Error('The card could not be drawn'))), 'image/png'));
}

/** Shares a file where the device can (the Web Share API), else downloads it. Returns what happened. */
export async function shareFile(blob: Blob, fileName: string, title: string, text: string): Promise<'shared' | 'downloaded'> {
  const file = new File([blob], fileName, { type: blob.type });
  const nav = navigator as Navigator & { canShare?: (data: ShareData) => boolean };
  if (nav.share && nav.canShare?.({ files: [file] })) {
    try {
      await nav.share({ files: [file], title, text });
      return 'shared';
    } catch {
      // Cancelled, or sharing failed: fall through to a download.
    }
  }
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = fileName;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  return 'downloaded';
}
