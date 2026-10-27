// The match player's calls (INTEGRATION.md 6.10): the matches, a match's timeline, frames a window at a time, the
// graphics the crew made, and what-ifs from the counterfactual workers. Unlike the showcase, the match player has no
// stand-in: it plays whole matches only from an OffBall API.
import { getJson, postJson } from '../api';
import type { Overlay } from '../feed/types';
import type { Pattern } from '../kits';

export interface MatchSummary {
  match_id: string;
  home: string;
  away: string;
  round: number | null;
  live: boolean;
  set: string;
  duration_ms: number;
  tracking: boolean;
}

export interface ClubInfo {
  club_id: string;
  name: string;
  short: string;
  kit: { primary: string; secondary: string; pattern: Pattern } | null;
}

export interface PeriodInfo {
  period: number;
  duration_ms: number;
  attacks_left_to_right: string;
}

export interface RosterPlayer {
  player_id: string;
  name: string;
  number: number;
  role: string;
  club_id: string;
  starter: boolean;
}

export interface Goal {
  event_id: string;
  period: number;
  t_ms: number;
  club_id: string;
  player_id: string | null;
}

export type Alternative = 'hold' | 'inside' | 'drop';
export type GraphicsStatus = 'not_built' | 'published' | 'skipped' | 'failed' | 'corrected';

export interface Moment {
  candidate_id: string;
  type: string;
  status: string;
  period: number;
  t_start_ms: number;
  t_end_ms: number;
  club_id: string;
  creator_id: string;
  dragged_ids: string[];
  receiver_id: string | null;
  strength: number;
  outcome: 'goal' | 'shot' | 'none';
  graphics: GraphicsStatus;
  graphics_note: string;
  /** The alternative this type of moment is usually measured against. */
  whatif: Alternative;
}

export interface Timeline {
  match_id: string;
  home: ClubInfo;
  away: ClubInfo;
  periods: PeriodInfo[];
  frame_rate: number;
  players: RosterPlayer[];
  goals: Goal[];
  moments: Moment[];
  alternatives: Alternative[];
}

/** A window of frames: `xy[k]` holds [x0, y0, x1, y1, …] in the order of `ids`, null for a player off the pitch. */
export interface FrameWindow {
  period: number;
  from_ms: number;
  to_ms: number;
  ids: string[];
  t: number[];
  ball: [number, number, number][];
  xy: (number | null)[][];
}

export interface MomentGraphics {
  status: GraphicsStatus;
  note: string;
  overlay_ids: string[];
}

export interface Graphics {
  overlays: Overlay[];
  moments: Record<string, MomentGraphics>;
}

export interface WhatIf {
  candidate_id: string;
  option_id: Alternative;
  counterfactual_id: string;
  period: number;
  t_start_ms: number;
  t_measure_ms: number;
  numbers: Record<string, number>;
  /** Median paths of the players free to react, as [t_ms, x, y]. */
  tracks: Record<string, [number, number, number][]>;
  ring: { at: [number, number]; rx_m: number; ry_m: number; open: boolean };
}

type Words3 = Record<'en' | 'es' | 'fr', string>;

export interface WhatIfWords {
  headline: Words3;
  plain: Words3;
  analyst: Words3;
  ai_generated: boolean;
}

const m = (id: string) => `/api/matches/${encodeURIComponent(id)}`;

/** A link within the player that keeps an `?api=` override, so a page pointed at another API stays on it. */
export function playerHref(route: string, params: Record<string, string> = {}): string {
  const api = new URLSearchParams(window.location.hash.split('?')[1] ?? '').get('api');
  const q = new URLSearchParams({ ...params, ...(api ? { api } : {}) }).toString();
  return `#/${route}${q ? `?${q}` : ''}`;
}

export const fetchMatches = (signal?: AbortSignal) => getJson<MatchSummary[]>('/api/matches', signal);
export const fetchTimeline = (id: string, signal?: AbortSignal) => getJson<Timeline>(`${m(id)}/timeline`, signal);
export const fetchGraphics = (id: string, signal?: AbortSignal) => getJson<Graphics>(`${m(id)}/graphics`, signal);
export const fetchFrames = (id: string, period: number, from: number, to: number, signal?: AbortSignal) =>
  getJson<FrameWindow>(`${m(id)}/frames?period=${period}&from_ms=${from}&to_ms=${to}`, signal);
export const explainMoment = (id: string, cid: string) => postJson<MomentGraphics & { overlays: Overlay[] }>(`${m(id)}/moments/${encodeURIComponent(cid)}/graphics`, {});
export const fetchWhatIf = (id: string, cid: string, option: Alternative, signal?: AbortSignal) =>
  getJson<WhatIf>(`${m(id)}/moments/${encodeURIComponent(cid)}/whatifs/${option}`, signal);
export const fetchWhatIfWords = (id: string, cid: string, option: Alternative, signal?: AbortSignal) =>
  getJson<{ words: WhatIfWords | null }>(`${m(id)}/moments/${encodeURIComponent(cid)}/whatifs/${option}/words`, signal);
