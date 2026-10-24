// Types for the client feed, mirroring contracts/*.schema.json (PRD 12.8, 15.7). Schema version 2.0.
import type { Mode } from '../prefs';
import type { XY } from '../match';

export const SCHEMA_VERSION = '2.0';

export type OverlayKind =
  | 'control_field'
  | 'gap_ring'
  | 'run_arrow'
  | 'pass_line'
  | 'ghost'
  | 'offside_line'
  | 'shape_lines'
  | 'player_tag'
  | 'badge'
  | 'caption'
  | 'stat_card'
  | 'chart'
  | 'correction';

export type Approval = 'auto' | 'pending' | 'approved' | 'held' | 'skipped' | 'rejected';

/** contracts/overlay.schema.json $defs/Anchors */
export interface Anchors {
  player_id?: string | null;
  player_ids?: string[] | null;
  from_xy?: XY | null;
  to_xy?: XY | null;
  centre_xy?: XY | null;
  radius_m?: number | null;
  polygon?: XY[] | null;
  ghost_track_id?: string | null;
}

/** contracts/overlay.schema.json $defs/Speech */
export interface Speech {
  ssml_ref: string;
  voice?: string;
  ssml?: string | null;
  /** Stereo pan for audio cues: -1 left, 1 right. */
  pan?: number | null;
}

/** contracts/overlay.schema.json */
export interface Overlay {
  schema_version?: string;
  overlay_id: string;
  rev: number;
  match_id: string;
  period: number;
  t_start_ms: number;
  t_end_ms: number;
  kind: OverlayKind;
  layer: string;
  /** 0 is most important. */
  priority: number;
  mode: Mode;
  anchors: Anchors;
  /** Text per locale. */
  text: Record<string, string>;
  speech?: Record<string, Speech>;
  a11y_text: Record<string, string>;
  /** A Vega-Lite spec, themed by the client (VIS-7). */
  chart?: Record<string, unknown> | null;
  /** Numbers for stat cards, with units, and renderer hints. */
  data?: Record<string, unknown> | null;
  evidence_ids: string[];
  confidence: number;
  approval: Approval;
  counterfactual_id?: string | null;
  detected_moment_id?: string | null;
  ai_generated: boolean;
  labels: string[];
}

/** contracts/overlay-upsert.schema.json */
export interface OverlayUpsert {
  type: 'overlay.upsert';
  match_id: string;
  overlay: Overlay;
  sent_at: string;
}

/** contracts/overlay-retract.schema.json */
export interface OverlayRetract {
  type: 'overlay.retract';
  match_id: string;
  overlay_id: string;
  reason: 'correction' | 'producer' | 'superseded' | 'expired';
  corrects_event_id?: string | null;
  replacement_id?: string | null;
  sent_at: string;
}

/** contracts/clock-sync.schema.json */
export interface ClockSync {
  type: 'clock.sync';
  match_id: string;
  period: number;
  t_ms: number;
  /** Playback speed, 0.25x to 60x. */
  speed?: number;
  server_time: string;
}

/** contracts/match-status.schema.json */
export interface MatchStatus {
  type: 'match.status';
  match_id: string;
  status: 'pre_match' | 'in_play' | 'half_time' | 'full_time' | 'interrupted';
  period: number;
  t_ms: number;
  score: Record<string, number>;
  sent_at: string;
}

/** contracts/tracked-frame.schema.json: player_id -> [x, y, orientation in radians]. */
export interface TrackedFrame {
  period: number;
  frame_id: number;
  t_ms: number;
  ball: [number, number, number];
  players: Record<string, [number, number, number]>;
}

/** Frames travel to viewers next to the partner messages (PRD 16.2: "Web PubSub: frames + overlays"). */
export interface FrameMessage {
  type: 'frame';
  match_id: string;
  frame: TrackedFrame;
}

/** The partner protocol (PRD 15.7). */
export type PartnerMessage = OverlayUpsert | OverlayRetract | ClockSync | MatchStatus;
export type ClientMessage = PartnerMessage | FrameMessage;

export const LAYER_OF: Record<OverlayKind, string> = {
  control_field: 'field',
  gap_ring: 'pitch',
  run_arrow: 'pitch',
  pass_line: 'pitch',
  ghost: 'pitch',
  offside_line: 'shape',
  shape_lines: 'shape',
  player_tag: 'labels',
  badge: 'labels',
  caption: 'dom',
  stat_card: 'dom',
  chart: 'dom',
  correction: 'dom',
};

export const isClientMessage = (m: unknown): m is ClientMessage =>
  typeof m === 'object' && m !== null && ['overlay.upsert', 'overlay.retract', 'clock.sync', 'match.status', 'frame'].includes((m as { type?: string }).type ?? '');
