// The client's view of one match feed: frames, rev-aware overlays, retractions, status and clock sync.
// Producer decisions travel as contract messages on a cross-tab bus, so they reach every open view (PRD 10.6).
import { LANG_IDS, type Mode } from '../prefs';
import { EVENT_PASS, MATCH_ID } from '../match';
import { showcaseFeed, tOf } from './emitter';
import { FieldCache } from './field-cache';
import { FrameBuffer } from './frames';
import type { Approval, ClientMessage, MatchStatus, Overlay, OverlayRetract, OverlayUpsert } from './types';

export interface Retraction {
  reason: OverlayRetract['reason'];
  corrects_event_id?: string | null;
  replacement_id?: string | null;
  /** performance.now() when it arrived: the Correction tag stays for 3 s (PRD 15.2). */
  at: number;
}

export interface LogLine {
  /** Wall-clock arrival, performance.now(). */
  at: number;
  t_ms: number;
  text: string;
}

export interface ActiveOverlay {
  overlay: Overlay;
  retraction?: Retraction;
}

export interface ActiveFilter {
  mode: Mode;
  /** The viewer turned on "What if no run?". */
  whatIf: boolean;
  /** Player focus: the followed player. */
  fav?: string;
}

const CORRECTION_HOLD_MS = 3000;
/** Live viewers watch 1.5 s behind the newest data, so network jitter never shows (PRD 16.2). */
export const LIVE_BUFFER_MS = 1500;
const DECISIONS_KEY = (match: string) => `offball.decisions.${match}`;

/** What travels between tabs: contract messages, plus a reset when the producer clears their decisions. */
type BusEnvelope = { kind: 'msg'; msg: ClientMessage } | { kind: 'reset' };
const now = () => performance.now();
const iso = () => new Date().toISOString();

export class FeedStore {
  readonly frames = new FrameBuffer();
  readonly fields = new FieldCache();
  readonly overlays = new Map<string, Overlay>();
  readonly retractions = new Map<string, Retraction>();
  status: MatchStatus | null = null;
  /** Every status message received, oldest first, so the score can be read at any moment time. */
  readonly statuses: MatchStatus[] = [];
  sync: { t_ms: number; speed: number; receivedAt: number } | null = null;
  /** performance.now() of the last message of any kind, for stall detection (VIS-9). */
  lastDataAt = now();
  /** Late overlays dropped rather than shown out of sync (VIS-9). */
  dropped = 0;
  /** Live mode: late overlays are dropped against where the display should be. */
  live = false;
  version = 0;
  readonly log: LogLine[] = [];
  readonly decisions: { at: string; overlay_id: string; action: string; by: string }[] = [];

  private listeners = new Set<() => void>();
  private bus: BroadcastChannel | null = null;
  /** Overlays grouped by mode, rebuilt after any change; views query it several times a frame. */
  private modeIndex: Map<Mode, Overlay[]> | null = null;

  private byMode(mode: Mode): Overlay[] {
    if (!this.modeIndex) {
      this.modeIndex = new Map();
      for (const o of this.overlays.values()) {
        const list = this.modeIndex.get(o.mode) ?? [];
        list.push(o);
        this.modeIndex.set(o.mode, list);
      }
      for (const list of this.modeIndex.values()) list.sort((a, b) => a.t_start_ms - b.t_start_ms);
    }
    return this.modeIndex.get(mode) ?? [];
  }

  constructor(readonly matchId: string = MATCH_ID) {
    try {
      this.bus = new BroadcastChannel(`offball:${matchId}`);
      this.bus.onmessage = (e: MessageEvent<BusEnvelope>) => {
        if (e.data.kind === 'reset') this.loadReplay();
        else this.ingest(e.data.msg, 'bus');
      };
    } catch {
      this.bus = null;
    }
  }

  subscribe = (fn: () => void): (() => void) => {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  };

  getVersion = () => this.version;

  private bump() {
    this.version++;
    this.modeIndex = null;
    this.listeners.forEach((l) => l());
  }

  /** Loads a whole replay at once: the default "replay mode" with precomputed agent outputs (PRD 21.2). */
  loadReplay(): void {
    const feed = showcaseFeed();
    this.reset();
    for (const f of feed.frames) this.frames.add(f);
    for (const m of feed.timeline) if (m.msg.type !== 'frame') this.ingest(m.msg, 'feed', false);
    this.applySavedDecisions();
    this.fields.prime(this.frames.all, 'real');
    this.bump();
  }

  /** Loads a set of messages as a replay: what this device kept of a live match, for the offline state (PRD 15.11). */
  loadMessages(messages: readonly ClientMessage[]): void {
    this.live = false;
    this.reset();
    for (const m of messages) this.ingest(m, 'feed', false);
    this.fields.prime(this.frames.all, 'real');
    this.bump();
  }

  reset(): void {
    this.frames.clear();
    this.overlays.clear();
    this.modeIndex = null;
    this.retractions.clear();
    this.status = null;
    this.statuses.length = 0;
    this.sync = null;
    this.dropped = 0;
    this.log.length = 0;
    this.lastDataAt = now();
  }

  /** Where a live display should be now: the server clock from clock.sync, less the jitter buffer. */
  liveTarget(): number | null {
    if (this.sync) return this.sync.t_ms + (now() - this.sync.receivedAt) * this.sync.speed - LIVE_BUFFER_MS;
    const latest = this.frames.latest;
    return latest ? latest.t_ms - LIVE_BUFFER_MS : null;
  }

  ingest(msg: ClientMessage, origin: 'feed' | 'bus' | 'local' = 'feed', notify = true): void {
    this.lastDataAt = now();
    switch (msg.type) {
      case 'frame':
        this.frames.add(msg.frame);
        return;
      case 'overlay.upsert': {
        const o = msg.overlay;
        const existing = this.overlays.get(o.overlay_id);
        if (existing && existing.rev >= o.rev) return;
        const target = this.live && origin === 'feed' ? this.liveTarget() : null;
        if (target !== null && o.t_end_ms < target) {
          this.dropped++;
          this.addLog(o.t_start_ms, `dropped late · ${o.kind} · ${o.overlay_id}`);
          break;
        }
        this.overlays.set(o.overlay_id, o);
        this.modeIndex = null;
        this.addLog(o.t_start_ms, `overlay.upsert · ${o.kind} · ${o.overlay_id} · ${o.approval}`);
        break;
      }
      case 'overlay.retract':
        this.retractions.set(msg.overlay_id, { reason: msg.reason, corrects_event_id: msg.corrects_event_id, replacement_id: msg.replacement_id, at: now() });
        this.addLog(this.overlays.get(msg.overlay_id)?.t_start_ms ?? 0, `overlay.retract · ${msg.overlay_id} · ${msg.reason}`);
        break;
      case 'clock.sync':
        this.sync = { t_ms: msg.t_ms, speed: msg.speed ?? 1, receivedAt: now() };
        return;
      case 'match.status':
        this.status = msg;
        this.statuses.push(msg);
        this.statuses.sort((a, b) => a.t_ms - b.t_ms);
        this.addLog(msg.t_ms, `match.status · ${msg.status} · ${Object.values(msg.score).join('–')}`);
        break;
    }
    if (notify) this.bump();
  }

  private addLog(t_ms: number, text: string) {
    this.log.push({ at: now(), t_ms, text });
    if (this.log.length > 80) this.log.shift();
  }

  /** The score at a moment time: the latest status message at or before it. */
  scoreAt(t_ms: number): { kes: number; ash: number } {
    let score = { kes: 0, ash: 0 };
    for (const s of this.statuses) {
      if (s.t_ms > t_ms) break;
      score = { kes: s.score.kes ?? score.kes, ash: s.score.ash ?? score.ash };
    }
    return score;
  }

  /** Overlays on screen at a moment time for one viewer, newest revision only (PRD 15.2). */
  active(t_ms: number, f: ActiveFilter): ActiveOverlay[] {
    const out: ActiveOverlay[] = [];
    const wall = now();
    for (const o of this.byMode(f.mode)) {
      if (o.t_start_ms > t_ms) break;
      if (t_ms >= o.t_end_ms) continue;
      if (o.approval !== 'auto' && o.approval !== 'approved') continue;
      const cf = !!o.counterfactual_id;
      if (cf !== f.whatIf && (cf || ['gap_ring', 'run_arrow', 'pass_line', 'caption'].includes(o.kind))) continue;
      if (f.mode === 'player' && (o.kind === 'caption' || o.kind === 'badge') && o.anchors.player_id && o.anchors.player_id !== f.fav) continue;
      const retraction = this.retractions.get(o.overlay_id);
      if (retraction && wall - retraction.at > CORRECTION_HOLD_MS) continue;
      out.push({ overlay: o, retraction });
    }
    return out.sort((a, b) => a.overlay.priority - b.overlay.priority || a.overlay.t_start_ms - b.overlay.t_start_ms);
  }

  /** Every overlay for one mode, for the producer's queue. */
  forMode(mode: Mode): Overlay[] {
    return [...this.byMode(mode)];
  }

  // ---------- Producer actions (PRD 10.6, 15.6) ----------

  private publish(msg: ClientMessage) {
    this.ingest(msg, 'local');
    try {
      this.bus?.postMessage({ kind: 'msg', msg } satisfies BusEnvelope);
    } catch {
      // Another tab can't hear us: this view still updates.
    }
    this.save(msg);
  }

  private save(msg: ClientMessage) {
    try {
      const key = DECISIONS_KEY(this.matchId);
      const list = JSON.parse(localStorage.getItem(key) ?? '[]') as ClientMessage[];
      list.push(msg);
      localStorage.setItem(key, JSON.stringify(list.slice(-200)));
    } catch {
      // Storage blocked: decisions last for this visit.
    }
  }

  private applySavedDecisions() {
    try {
      const list = JSON.parse(localStorage.getItem(DECISIONS_KEY(this.matchId)) ?? '[]') as ClientMessage[];
      for (const m of list) this.ingest(m, 'local', false);
    } catch {
      // Nothing saved, or unreadable.
    }
  }

  clearDecisions(): void {
    try {
      localStorage.removeItem(DECISIONS_KEY(this.matchId));
    } catch {
      // Ignore.
    }
    this.decisions.length = 0;
    this.loadReplay();
    try {
      this.bus?.postMessage({ kind: 'reset' } satisfies BusEnvelope);
    } catch {
      // Ignore.
    }
  }

  private record(overlay_id: string, action: string, by = 'producer') {
    this.decisions.unshift({ at: new Date().toLocaleTimeString(), overlay_id, action, by });
    if (this.decisions.length > 50) this.decisions.pop();
  }

  decide(overlay_id: string, approval: Approval): void {
    const o = this.overlays.get(overlay_id);
    if (!o) return;
    this.record(overlay_id, approval);
    this.publish({ type: 'overlay.upsert', match_id: this.matchId, overlay: { ...o, rev: o.rev + 1, approval }, sent_at: iso() } satisfies OverlayUpsert);
  }

  retract(overlay_id: string, reason: OverlayRetract['reason'] = 'producer', extra: Partial<OverlayRetract> = {}): void {
    this.record(overlay_id, `retract (${reason})`);
    this.publish({ type: 'overlay.retract', match_id: this.matchId, overlay_id, reason, sent_at: iso(), ...extra });
  }

  /** Adds a graphic to the queue, waiting for approval. */
  queue(overlay: Overlay): void {
    this.record(overlay.overlay_id, 'queued', 'Activator alert');
    this.publish({ type: 'overlay.upsert', match_id: this.matchId, overlay, sent_at: iso() });
  }

  /**
   * A feed correction moves where the pass started. The Fact-checker re-verifies every aired claim that cited the
   * pass, and the Producer retracts and patches them with a visible Correction tag, inside the 5 s target (PRD 10.6).
   * Returns the steps with their delays, for the console's trace.
   */
  correct(onStep?: (step: string) => void): void {
    const cited = [...this.overlays.values()].filter((o) => o.evidence_ids.includes(EVENT_PASS) && !this.retractions.has(o.overlay_id) && !o.labels.includes('correction'));
    onStep?.(`Feed correction for ${EVENT_PASS}: the pass started 0.6 m further forward.`);
    window.setTimeout(() => onStep?.(`Fact-checker re-verified ${cited.length} aired claims that cite ${EVENT_PASS}.`), 600);
    window.setTimeout(() => {
      for (const o of cited) {
        const patched = patchPass(o);
        const replacement: Overlay = { ...patched, overlay_id: `${o.overlay_id}-r1`, rev: 1, labels: [...o.labels, 'correction'], evidence_ids: [...o.evidence_ids, `${EVENT_PASS}-corr`] };
        this.publish({ type: 'overlay.upsert', match_id: this.matchId, overlay: replacement, sent_at: iso() });
        this.retract(o.overlay_id, 'correction', { corrects_event_id: EVENT_PASS, replacement_id: replacement.overlay_id });
      }
      onStep?.(`Producer retracted and patched ${cited.length} graphics with a Correction tag.`);
    }, 1600);
  }
}

/** Corrected numbers for the pass: 27.4 m and difficulty 5.9, in every locale's own decimal style. */
function patchPass(o: Overlay): Overlay {
  const fix = (s: string) => s.replace(/28([.,])0/g, '27$14').replace(/6([.,])1/g, '5$19');
  const text = Object.fromEntries(Object.entries(o.text).map(([l, s]) => [l, fix(s)]));
  const a11y = Object.fromEntries(Object.entries(o.a11y_text).map(([l, s]) => [l, fix(s)]));
  const data = o.data ? { ...o.data, ...(o.data.difficulty ? { difficulty: 5.9, distance_m: 27.4 } : {}) } : o.data;
  return { ...o, text, a11y_text: a11y, data, speech: {} };
}

let shared: FeedStore | null = null;

/** One store per tab for the showcase match, loaded with the replay by default. */
export function getStore(): FeedStore {
  if (!shared) {
    shared = new FeedStore(MATCH_ID);
    shared.loadReplay();
  }
  return shared;
}

/** Localised text from an overlay, falling back to English (PRD 15.3: English is always one tap away). */
export const textOf = (o: Overlay, lang: string): string => o.text[lang] ?? o.text.en ?? '';
export const a11yOf = (o: Overlay, lang: string): string => o.a11y_text[lang] ?? o.a11y_text.en ?? textOf(o, lang);
export const momentT = (o: Overlay) => tOf(o.t_start_ms);
export const ALL_LANGS = LANG_IDS;
