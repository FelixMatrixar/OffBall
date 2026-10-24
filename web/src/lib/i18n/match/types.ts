import type { OverlayGroup } from '../../density';
import type { Density, Metric, Theme, TierChoice, View } from '../../prefs';

/**
 * Every word around the pitch in the match view: the header and chips, the side panels, the Personalize drawer, the
 * dialogs and Ask OffBall's frame (PRD 15.3). Templates take the {placeholders} named beside them. Club and player
 * names, agent tool names and overlay kinds stay as they are.
 */
export interface MatchStrings {
  /** {home}, {away}. */
  h1: string;
  stage: string;
  /** {panel}: the mode's name. */
  panel: string;
  showPanel: string;
  hidePanel: string;
  offline: string;
  units: { m: string; km: string; kmh: string; pts: string; ofTen: string; fromGoal: string };

  // The pitch and its chips
  pitchView: string;
  views: Record<View, string>;
  notHere: string;
  /** {tier}, {name}. */
  tierChip: string;
  videoTier: string;
  fieldLive: string;
  fieldWithout: string;
  /** {dir}: one of `towards`. */
  scene2d: string;
  scene3d: string;
  towards: { right: string; up: string; camera: string };
  withoutRun: string;
  onPitch: string;
  players: string;
  /** {club}, {num}, {name}. */
  playerName: string;
  followed: string;
  overlay: string;
  sideBySide: string;
  whatIfView: string;
  no3d: string;
  /** The video stage (tier D). */
  videoLabel: string;
  videoWhatIf: string;
  /** Quality steps (PRD 16.6). {tier}, {name}. */
  tierBack: string;
  tierToB: string;
  tierToC: string;
  tierToD: string;

  // Tools under the pitch
  snapshot: string;
  snapshotAria: string;
  snapshotTitle: string;
  svgAria: string;
  svgTitle: string;
  decideTitle: string;
  /** {kind}. */
  saved: string;
  /** {why}. */
  snapFailed: string;
  /** {name}. */
  following: string;
  /** {lang}. */
  noVoice: string;
  feedMeta: string;
  /** {ids}. */
  evidenceMeta: string;
  momentum: { title: string; summary: string; column: string; minute: string; label: string };
  replay: { prev: string; next: string; back: string; fwd: string; speed: string; time: string; live: string; goLive: string; jump: string };

  // Adaptive density: the overlays menu on the pitch (PRD 8.2)
  overlays: {
    button: string;
    /** {n}. */
    hidden: string;
    hint: string;
    hintSession: string;
    showAll: string;
    groups: Record<OverlayGroup, string>;
    /** {what}, {mode}. */
    hid: string;
    fewer: string;
    shown: string;
    undo: string;
  };

  // The number a viewer cares about
  metrics: Record<Metric, string>;
  /** {label}. */
  yourNumber: string;

  // The Personalize drawer (PRD 15.9)
  personalize: {
    club: string;
    fav: string;
    metric: string;
    density: string;
    densities: Record<Density, string>;
    adapt: string;
    adaptHint: string;
    /** {mode}, {what}. */
    learned: string;
    /** {mode}. */
    learnedFewer: string;
    learnedNone: string;
    forget: string;
    forgotten: string;
    theme: string;
    themes: Record<Theme, string>;
    voice: string;
    voiceHint: string;
    sonify: string;
    sonifyHint: string;
    reduced: string;
    reducedHint: string;
    tv: string;
    tvHint: string;
    spoiler: string;
    spoilerHint: string;
    capSize: string;
    viewNote: string;
    tier: string;
    tiers: Record<TierChoice, string>;
    tierNote: string;
    saved: string;
  };

  // Keyboard shortcuts (PRD 15.4), in the order of SHORTCUTS
  keys: { caption: string; keys: string; does: string; to: string; rows: readonly string[] };

  // Pair a phone (PRD 15.5)
  pair: {
    /** {code}. */
    qr: string;
    code: string;
    scan: string;
    /** {h}, {m}. */
    expires: string;
    one: string;
    /** {n}. */
    many: string;
    none: string;
    renew: string;
    openHere: string;
    note: string;
  };

  // Ask OffBall's frame. The answers themselves come from the Pundit.
  ask: {
    empty: string;
    emptyHint: string;
    checking: string;
    reading: string;
    englishNote: string;
    placeholder: string;
    send: string;
    voice: string;
    stop: string;
    listening: string;
    consent: string;
    useVoice: string;
    type: string;
    corrected: string;
  };

  // Chart frames
  chart: { table: string; chart: string; export: string; sample: string };

  // Casual and Learn need nothing beyond the packs; the other four panels:
  analyst: {
    heading: string;
    tiles: { run: string; speed: string; disp: string; gap: string; pdist: string; pdiff: string; xg: string; line: string };
    afterPass: string;
    afterShot: string;
    spaceBy: string;
    reruns: string;
    rerunning: string;
    /** {lo}, {hi}. */
    interval: string;
    evidence: string;
    buildUp: string;
    corrected: string;
    chart: string;
    charts: { control: string; network: string; shots: string; shape: string; heat: string };
    controlTitle: string;
    /** {kes}, {ash}. */
    controlSummary: string;
    controlLabel: string;
    networkTitle: string;
    networkSummary: string;
    shotsTitle: string;
    shotsSummary: string;
    shapeTitle: string;
    /** {from}, {to}, {press}. */
    shapeSummary: string;
    higher: string;
    lower: string;
    shapeLabel: string;
    player: string;
    heatTitle: string;
    heatSummary: string;
    leadersTitle: string;
    /** {name}, {v}, {lo}, {hi}. */
    leadersSummary: string;
    columns: {
      minute: string;
      player: string;
      from: string;
      to: string;
      passes: string;
      team: string;
      xg: string;
      outcome: string;
      zone: string;
      share: string;
      space: string;
      low: string;
      high: string;
      line: string;
      width: string;
      compact: string;
      press: string;
      type: string;
      length: string;
    };
  };
  player: {
    roles: Record<'GK' | 'RB' | 'LB' | 'CB' | 'DM' | 'CM' | 'AM' | 'RM' | 'LM' | 'RW' | 'LW' | 'ST', string>;
    following: string;
    change: string;
    tiles: { runs: string; dragged: string; created: string; protected: string; sprints: string; distance: string; top: string };
    speed: string;
    /** {num}, {speed}. */
    speedLabel: string;
    sprint: string;
    distance: string;
    /** {lo}, {hi}. */
    distanceLabel: string;
    /** The distance chart's scale: {n} metres. */
    metres: string;
    early: string;
    late: string;
    runMap: string;
    heatMap: string;
    chart: string;
    /** {num}. */
    runsTitle: string;
    heatTitle: string;
    noRuns: string;
    heatSummary: string;
    runTypes: Record<'Decoy' | 'In behind' | 'Overlap' | 'Check to ball', string>;
  };
  audio: {
    heading: string;
    narration: string;
    /** {name}. */
    voice: string;
    noVoice: string;
    cue: string;
    cueHint: string;
    left: string;
    leftOfCentre: string;
    centre: string;
    rightOfCentre: string;
    right: string;
    now: string;
    test: string;
  };
  broadcaster: {
    queue: string;
    states: Record<'Queued' | 'Waiting' | 'On air' | 'Held' | 'Skipped' | 'Retracted' | 'Done', string>;
    /** {c}, {approval}, {id}. */
    meta: string;
    approve: string;
    hold: string;
    skip: string;
    retract: string;
    engineer: string;
    engineerNote: string;
    console: string;
  };
}
