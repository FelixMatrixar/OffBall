// A whole match's frames, fetched 20 seconds at a time around wherever the viewer is (VIS-2). A 90-minute match is
// 135,000 frames, far too many to hold at once, so the player keeps the chunks it has used most recently and fetches
// the next one before playback reaches it.
import type { XY } from '../match';
import { FrameBuffer, type Sample } from '../feed/frames';
import type { TrackedFrame } from '../feed/types';
import { fetchFrames, type FrameWindow } from './api';

export const CHUNK_MS = 20_000;
/** A little either side of each chunk, so curves are smooth across the joins. */
const OVERLAP_MS = 120;
/** Ten minutes of play: about 25 MB of frames. */
const MAX_CHUNKS = 30;
/** Fetch the next chunk once playback is this close to the end of the current one. */
const PREFETCH_MS = 8_000;

const key = (period: number, index: number) => `${period}:${index}`;

function toFrames(w: FrameWindow): TrackedFrame[] {
  return w.t.map((t_ms, k) => {
    const row = w.xy[k];
    const players: Record<string, [number, number, number]> = {};
    w.ids.forEach((id, j) => {
      const x = row[2 * j];
      const y = row[2 * j + 1];
      if (x !== null && y !== null) players[id] = [x, y, 0];
    });
    return { period: w.period, frame_id: Math.round(t_ms / 40), t_ms, ball: w.ball[k], players };
  });
}

export class MatchFrames {
  private chunks = new Map<string, FrameBuffer>();
  private loading = new Map<string, Promise<void>>();
  private failed = new Set<string>();
  private listeners = new Set<() => void>();
  version = 0;

  constructor(
    readonly matchId: string,
    private readonly durations: Record<number, number>,
  ) {}

  subscribe = (fn: () => void): (() => void) => {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  };

  getVersion = () => this.version;

  private bump() {
    this.version++;
    this.listeners.forEach((l) => l());
  }

  private load(period: number, index: number): Promise<void> {
    const k = key(period, index);
    if (this.chunks.has(k)) {
      // Most recently used last, so the oldest is first to go.
      const buf = this.chunks.get(k)!;
      this.chunks.delete(k);
      this.chunks.set(k, buf);
      return Promise.resolve();
    }
    const pending = this.loading.get(k);
    if (pending) return pending;
    const end = this.durations[period] ?? 0;
    const from = Math.max(0, index * CHUNK_MS - OVERLAP_MS);
    const to = Math.min(end, (index + 1) * CHUNK_MS + OVERLAP_MS);
    const p = fetchFrames(this.matchId, period, from, to)
      .then((w) => {
        const buf = new FrameBuffer();
        for (const f of toFrames(w)) buf.add(f);
        this.chunks.set(k, buf);
        this.failed.delete(k);
        while (this.chunks.size > MAX_CHUNKS) this.chunks.delete(this.chunks.keys().next().value!);
      })
      .catch(() => {
        this.failed.add(k);
      })
      .finally(() => {
        this.loading.delete(k);
        this.bump();
      });
    this.loading.set(k, p);
    return p;
  }

  /** Makes sure the frames around a time are here or on their way, and the next chunk too when playback nears it. */
  ensure(period: number, t_ms: number): void {
    const index = Math.floor(t_ms / CHUNK_MS);
    void this.load(period, index);
    const end = this.durations[period] ?? 0;
    if (t_ms % CHUNK_MS > CHUNK_MS - PREFETCH_MS && (index + 1) * CHUNK_MS < end) void this.load(period, index + 1);
  }

  /** The frames at a time are on the device. */
  has(period: number, t_ms: number): boolean {
    return this.chunks.has(key(period, Math.floor(t_ms / CHUNK_MS)));
  }

  /** The frames at a time couldn't be fetched. */
  error(period: number, t_ms: number): boolean {
    return this.failed.has(key(period, Math.floor(t_ms / CHUNK_MS)));
  }

  /** Retries a window that failed. */
  retry(period: number, t_ms: number): void {
    this.failed.delete(key(period, Math.floor(t_ms / CHUNK_MS)));
    this.ensure(period, t_ms);
  }

  sample(period: number, t_ms: number): Sample | null {
    return this.chunks.get(key(period, Math.floor(t_ms / CHUNK_MS)))?.sample(t_ms) ?? null;
  }

  /** Where a player will be `lead` seconds on, for the head of a run arrow; where they are if that isn't here yet. */
  ahead(period: number, t_ms: number, id: string, lead: number): XY | null {
    const later = this.sample(period, t_ms + lead * 1000) ?? this.sample(period, t_ms);
    return later?.pos[id] ?? null;
  }

  /** The ball's recent positions, newest first, while it travels fast enough to leave a trail. */
  trail(period: number, t_ms: number): XY[] {
    const out: XY[] = [];
    const now = this.sample(period, t_ms);
    if (!now) return out;
    for (let k = 1; k <= 4; k++) {
      const s = this.sample(period, t_ms - k * 60);
      if (!s) break;
      out.push([s.ball[0], s.ball[1]]);
    }
    const last = out[out.length - 1];
    return last && Math.hypot(now.ball[0] - last[0], now.ball[1] - last[1]) > 2.5 ? out : [];
  }
}
