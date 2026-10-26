// The calls the frontend makes to the backend (INTEGRATION.md section 6). Every caller keeps its stand-in as the
// fallback, so the app works the same with no backend and with one that can't be reached (PRD 21.2, BE-2).
import { MATCH_ID } from './match';
import type { Answer } from './pundit';

/**
 * Where the API lives: `?api=` in the address, else the VITE_API_BASE build setting, else the server behind an
 * `sse:` feed that points at an OffBall API. Empty when there is no backend.
 */
export function apiBase(): string {
  if (typeof window === 'undefined') return '';
  const query = new URLSearchParams(window.location.hash.split('?')[1] ?? window.location.search.slice(1));
  const explicit = query.get('api') ?? (import.meta.env.VITE_API_BASE as string | undefined);
  if (explicit) return explicit.replace(/\/+$/, '');
  const feed = query.get('feed') ?? (import.meta.env.VITE_FEED_URL as string | undefined) ?? '';
  const at = feed.startsWith('sse:') ? feed.indexOf('/api/') : -1;
  return at > 0 ? feed.slice(4, at) : '';
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

async function check(res: Response): Promise<Response> {
  if (res.ok) return res;
  let detail = res.statusText;
  try {
    detail = ((await res.json()) as { detail?: string }).detail ?? detail;
  } catch {
    // Not JSON: keep the status text.
  }
  throw new ApiError(res.status, detail);
}

/** GET a JSON resource from the API. */
export async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const base = apiBase();
  if (!base) throw new ApiError(0, 'No backend is set');
  return (await check(await fetch(`${base}${path}`, { signal }))).json() as Promise<T>;
}

/** POST JSON to the API and read the JSON answer. */
export async function postJson<T>(path: string, body: unknown, headers: Record<string, string> = {}): Promise<T> {
  const base = apiBase();
  if (!base) throw new ApiError(0, 'No backend is set');
  const res = await fetch(`${base}${path}`, { method: 'POST', headers: { 'content-type': 'application/json', ...headers }, body: JSON.stringify(body) });
  return (await check(res)).json() as Promise<T>;
}

/** Reads a Server-Sent Events body, calling `on` with each event's name and data. */
async function readEvents(res: Response, on: (event: string, data: string) => void): Promise<void> {
  const reader = res.body?.getReader();
  if (!reader) return;
  const decoder = new TextDecoder();
  let buffer = '';
  for (;;) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value, { stream: !done }).replace(/\r\n?/g, '\n');
    let end: number;
    while ((end = buffer.indexOf('\n\n')) >= 0) {
      const block = buffer.slice(0, end);
      buffer = buffer.slice(end + 2);
      let event = 'message';
      const data: string[] = [];
      for (const line of block.split('\n')) {
        if (line.startsWith('event:')) event = line.slice(6).trim();
        else if (line.startsWith('data:')) data.push(line.slice(5).replace(/^ /, ''));
      }
      if (data.length) on(event, data.join('\n'));
    }
    if (done) return;
  }
}

export interface AskContext {
  matchId: string;
  period: number;
  t_ms: number;
  mode: string;
  lang: string;
  fav?: string;
}

/**
 * Ask the Pundit (INTEGRATION.md 6.1). `onTool` hears each tool as the Pundit calls it; the promise settles with
 * the fact-checked answer, or fails when there is no backend, no model, or no answer.
 */
export async function askPundit(question: string, ctx: AskContext, onTool: (name: string) => void, signal?: AbortSignal): Promise<Answer> {
  const base = apiBase();
  if (!base) throw new ApiError(0, 'No backend is set');
  const res = await check(
    await fetch(`${base}/api/matches/${ctx.matchId}/ask`, {
      method: 'POST',
      headers: { 'content-type': 'application/json', accept: 'text/event-stream' },
      body: JSON.stringify({ question, period: ctx.period, t_ms: ctx.t_ms, mode: ctx.mode, lang: ctx.lang, fav: ctx.fav }),
      signal,
    }),
  );
  let result: Answer | null = null;
  let failure = 'The Pundit sent no answer';
  await readEvents(res, (event, data) => {
    const payload = JSON.parse(data) as { name?: string; detail?: string };
    if (event === 'tool' && payload.name) onTool(payload.name);
    else if (event === 'answer') result = payload as unknown as Answer;
    else if (event === 'error') failure = payload.detail ?? failure;
  });
  if (!result) throw new ApiError(502, failure);
  return result;
}

export type ProducerDecision = 'approve' | 'hold' | 'skip' | 'retract';
/** Sends one producer decision about a graphic; the backend answers on the stream. */
export type ProducerRemote = (overlay_id: string, decision: ProducerDecision) => Promise<void>;

/** The live run's producer token from `?producer=`, or null. */
export function producerToken(): string | null {
  if (typeof window === 'undefined') return null;
  const query = new URLSearchParams(window.location.hash.split('?')[1] ?? window.location.search.slice(1));
  return query.get('producer');
}

/**
 * A stream URL that carries the producer token, so the stream includes the graphics waiting for approval (PRD 11.6).
 * Only for streams from this app's own API.
 */
export function producerStream(url: string): string {
  const token = producerToken();
  const base = apiBase();
  if (!token || !base || !url.startsWith(base)) return url;
  return `${url}${url.includes('?') ? '&' : '?'}producer=${encodeURIComponent(token)}`;
}

/** The producer's link to the backend (INTEGRATION.md 6.3), when there is an API and `?producer=` holds the run's token. */
export function producerRemote(): ProducerRemote | null {
  const base = apiBase();
  const token = producerToken();
  if (!base || !token) return null;
  return async (overlay_id, decision) => {
    await postJson(`/api/matches/${MATCH_ID}/approvals`, { overlay_id, decision, by: 'producer' }, { 'X-Producer-Token': token });
  };
}

/** Three questions about what just happened, from the backend (INTEGRATION.md 6.1). */
export function fetchSuggestions(matchId: string, period: number, t_ms: number, signal?: AbortSignal): Promise<string[]> {
  return getJson<string[]>(`/api/matches/${matchId}/suggestions?period=${period}&t_ms=${t_ms}`, signal);
}
