// Where the feed comes from (PRD 15.7, 21.2). Replay is the default: the showcase with precomputed agent output.
// A live feed arrives over Server-Sent Events or WebSocket; JSONL files replay a recorded feed.
import { producerRemote, producerStream } from '../api';
import { loadBuffer, saveBuffer } from './offline';
import { T_LOOP, showcaseFeed } from './emitter';
import type { FeedStore } from './store';
import { isClientMessage, type ClientMessage } from './types';

export type SourceKind = 'replay' | 'live-sim' | 'sse' | 'ws' | 'jsonl';
export type SourceState = 'connecting' | 'open' | 'error' | 'closed' | 'buffered';

export interface SourceHandle {
  kind: SourceKind;
  live: boolean;
  label: string;
  /** Offline: when the minutes being replayed were saved on this device (PRD 15.11), else null. */
  buffered?: number | null;
  state: () => SourceState;
  stop: () => void;
}

export interface SourceSpec {
  kind: SourceKind;
  url?: string;
  /** For the live simulation: seconds into the moment when the network drops, and for how long. */
  stall?: { at: number; for: number };
}

/** Reads ?feed=sse:URL, ?feed=ws://…, ?feed=jsonl:/path or the VITE_FEED_URL build setting. */
export function sourceFromLocation(): SourceSpec {
  const query = new URLSearchParams(window.location.hash.split('?')[1] ?? window.location.search.slice(1));
  const raw = query.get('feed') ?? (import.meta.env.VITE_FEED_URL as string | undefined) ?? '';
  if (raw.startsWith('sse:')) return { kind: 'sse', url: raw.slice(4) };
  if (raw.startsWith('ws://') || raw.startsWith('wss://')) return { kind: 'ws', url: raw };
  if (raw.startsWith('jsonl:')) return { kind: 'jsonl', url: raw.slice(6) };
  return { kind: 'replay' };
}

/**
 * On a live feed from an OffBall API with the run's producer token (`?producer=`), the producer's approve, hold, skip
 * and retract go to the backend, which sends the result to every screen on the stream (INTEGRATION.md 6.3).
 */
function withProducer(store: FeedStore, handle: SourceHandle): SourceHandle {
  store.remote = producerRemote();
  return {
    ...handle,
    get live() {
      return handle.live;
    },
    get buffered() {
      return handle.buffered;
    },
    stop: () => {
      store.remote = null;
      handle.stop();
    },
  };
}

function ingestText(store: FeedStore, text: string) {
  for (const line of text.split('\n')) {
    if (!line.trim()) continue;
    try {
      const msg = JSON.parse(line) as unknown;
      if (isClientMessage(msg)) store.ingest(msg);
    } catch {
      // A malformed line is skipped, never fatal.
    }
  }
}

/** Keeps the last 10 minutes of a live feed on the device, for the offline state (PRD 15.11). */
function bufferer(store: FeedStore) {
  const recent: ClientMessage[] = [];
  const keep = (m: ClientMessage) => {
    recent.push(m);
    const newest = 'frame' in m ? m.frame.t_ms : 't_ms' in m ? m.t_ms : 0;
    while (recent.length > 2 && newest - ('frame' in recent[0] ? recent[0].frame.t_ms : 't_ms' in recent[0] ? recent[0].t_ms : newest) > 600_000) recent.shift();
  };
  const timer = window.setInterval(() => void saveBuffer(store.matchId, recent), 5000);
  return { keep, stop: () => window.clearInterval(timer) };
}

/**
 * The offline state for a live feed (PRD 15.11): with the device offline and nothing received yet, replay what this
 * device kept of the match. When data arrives again, the feed goes back to live from that moment.
 */
function offlineFallback(store: FeedStore) {
  let savedAt: number | null = null;
  let gotData = false;
  const tryBuffer = () => {
    if (gotData || savedAt !== null || navigator.onLine) return;
    void loadBuffer(store.matchId).then((saved) => {
      if (!saved?.messages.length || gotData || savedAt !== null) return;
      savedAt = saved.savedAt;
      store.loadMessages(saved.messages);
    });
  };
  return {
    tryBuffer,
    /** Call before ingesting live data: leaves the saved replay for the live feed. */
    onData: () => {
      gotData = true;
      if (savedAt === null) return;
      savedAt = null;
      store.live = true;
      store.reset();
    },
    savedAt: () => savedAt,
  };
}

export function startSource(store: FeedStore, spec: SourceSpec): SourceHandle {
  switch (spec.kind) {
    case 'live-sim':
      return startLiveSim(store, spec.stall);
    case 'sse':
      return withProducer(store, startSse(store, producerStream(spec.url ?? '')));
    case 'ws':
      return withProducer(store, startWs(store, spec.url ?? ''));
    case 'jsonl':
      return startJsonl(store, spec.url ?? '');
    default:
      store.live = false;
      store.loadReplay();
      return { kind: 'replay', live: false, label: 'Replay · precomputed agent output', state: () => 'open', stop: () => {} };
  }
}

/** Deterministic network jitter, 0–150 ms per message. */
const jitter = (i: number) => {
  const v = Math.sin(i * 12.9898) * 43758.5453;
  return (v - Math.floor(v)) * 0.15;
};

/**
 * Streams the showcase as a live feed would: frames and graphics in real time with network jitter. With a stall,
 * nothing arrives for a while, then everything queued arrives at once, so the client's stall handling, catch-up and
 * late-graphic dropping run for real (VIS-9).
 */
function startLiveSim(store: FeedStore, stall?: { at: number; for: number }): SourceHandle {
  const feed = showcaseFeed();
  store.live = true;
  store.reset();
  let start = performance.now();
  let i = 0;
  let queued: ClientMessage[] = [];
  const timer = window.setInterval(() => {
    const elapsed = (performance.now() - start) / 1000;
    const stalled = !!stall && elapsed >= stall.at && elapsed < stall.at + stall.for;
    while (i < feed.timeline.length && feed.timeline[i].at + jitter(i) <= elapsed) {
      const msg = feed.timeline[i++].msg;
      if (stalled) queued.push(msg);
      else store.ingest(msg);
    }
    if (!stalled && queued.length) {
      for (const msg of queued) store.ingest(msg);
      queued = [];
    }
    if (elapsed > T_LOOP + 1.5 + (stall?.for ?? 0)) {
      // The moment is over: start the next live session.
      start = performance.now();
      i = 0;
      store.reset();
    }
  }, 20);
  return {
    kind: 'live-sim',
    live: true,
    label: stall ? 'Live · simulated network with a stall' : 'Live · simulated network',
    state: () => 'open',
    stop: () => {
      window.clearInterval(timer);
      store.live = false;
    },
  };
}

function startSse(store: FeedStore, url: string): SourceHandle {
  store.live = true;
  store.reset();
  let state: SourceState = 'connecting';
  const buf = bufferer(store);
  const offline = offlineFallback(store);
  offline.tryBuffer();
  const es = new EventSource(url);
  const onData = (e: MessageEvent<string>) => {
    offline.onData();
    state = 'open';
    ingestText(store, e.data);
    try {
      for (const line of e.data.split('\n')) if (line.trim()) buf.keep(JSON.parse(line) as ClientMessage);
    } catch {
      // Already skipped by ingestText.
    }
  };
  es.onopen = () => (state = 'open');
  es.onerror = () => {
    state = 'error';
    offline.tryBuffer();
  };
  es.onmessage = onData;
  for (const type of ['overlay.upsert', 'overlay.retract', 'clock.sync', 'match.status', 'frame']) es.addEventListener(type, onData as EventListener);
  return {
    kind: 'sse',
    get live() {
      return offline.savedAt() === null;
    },
    get buffered() {
      return offline.savedAt();
    },
    get label() {
      return offline.savedAt() !== null ? 'Offline · saved on this device' : `Live · Server-Sent Events · ${url}`;
    },
    state: () => (offline.savedAt() !== null ? 'buffered' : state),
    stop: () => {
      es.close();
      buf.stop();
      store.live = false;
    },
  };
}

function startWs(store: FeedStore, url: string): SourceHandle {
  store.live = true;
  store.reset();
  let state: SourceState = 'connecting';
  let ws: WebSocket | null = null;
  let stopped = false;
  let retry = 500;
  const buf = bufferer(store);
  const offline = offlineFallback(store);
  offline.tryBuffer();
  const connect = () => {
    ws = new WebSocket(url);
    ws.onopen = () => {
      state = 'open';
      retry = 500;
    };
    ws.onmessage = (e: MessageEvent) => {
      if (typeof e.data !== 'string') return;
      offline.onData();
      ingestText(store, e.data);
      for (const line of e.data.split('\n')) {
        try {
          if (line.trim()) buf.keep(JSON.parse(line) as ClientMessage);
        } catch {
          // Skipped.
        }
      }
    };
    ws.onerror = () => {
      state = 'error';
      offline.tryBuffer();
    };
    ws.onclose = () => {
      if (stopped) return;
      state = 'connecting';
      window.setTimeout(connect, retry);
      retry = Math.min(retry * 2, 8000);
    };
  };
  connect();
  return {
    kind: 'ws',
    get live() {
      return offline.savedAt() === null;
    },
    get buffered() {
      return offline.savedAt();
    },
    get label() {
      return offline.savedAt() !== null ? 'Offline · saved on this device' : `Live · WebSocket · ${url}`;
    },
    state: () => (offline.savedAt() !== null ? 'buffered' : state),
    stop: () => {
      stopped = true;
      ws?.close();
      buf.stop();
      store.live = false;
    },
  };
}

function startJsonl(store: FeedStore, url: string): SourceHandle {
  let state: SourceState = 'connecting';
  store.live = false;
  store.reset();
  fetch(url)
    .then((r) => (r.ok ? r.text() : Promise.reject(new Error(String(r.status)))))
    .then((text) => {
      ingestText(store, text);
      store.fields.prime(store.frames.all, 'real');
      state = 'open';
    })
    .catch(() => {
      state = 'error';
      store.loadReplay();
    });
  return { kind: 'jsonl', live: false, label: `Replay · JSONL · ${url}`, state: () => state, stop: () => {} };
}
