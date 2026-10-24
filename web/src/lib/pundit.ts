// Ask OffBall, answered on the device from the match data until the Pundit agent is connected (PRD 10.4).
// Every claim cites evidence; anything it can't verify is said plainly and left out; out-of-scope requests are
// declined with the nearest useful alternative (PRD 15.11).
import { barSpec, controlIndexSpec, type VegaLiteSpec } from '../components/charts';
import { LEADERS, focusStats, leaderName } from './content';
import { CF_ID, EVENT_PASS, EVENT_SHOT, MATCH_ID, PLAYERS, frameRef, hasPlayer, pid, player, stepAt, type Team } from './match';
import { CONTROL_INDEX } from './stats';

export type AnswerState = 'ok' | 'partial' | 'declined' | 'unknown';

export interface Claim {
  text: string;
  verified: boolean;
  evidence: string[];
}

export interface AnswerChart {
  title: string;
  spec: VegaLiteSpec;
  summary: string;
  columns: string[];
  rows: (string | number)[][];
}

export interface Answer {
  question: string;
  state: AnswerState;
  claims: Claim[];
  chart?: AnswerChart;
  /** The MCP tools the Pundit would call, shown while it works. */
  tools: string[];
  /** For a declined or unknown question: the nearest thing OffBall can do. */
  alternative?: { label: string; question: string };
  /** Shown when a corrected event changed the answer. */
  corrected?: boolean;
}

interface Context {
  /** Moment time, seconds after 63:00. */
  t: number;
  fav: string;
  /** The feed has corrected the pass (PRD 10.6). */
  passCorrected: boolean;
}

const ok = (text: string, evidence: string[]): Claim => ({ text, verified: true, evidence });
const unverified = (text: string): Claim => ({ text, verified: false, evidence: [] });

/** Three questions drawn from what just happened in the match (PRD 15.11: never a blank box). */
export function suggestions(t: number): string[] {
  const step = stepAt(t);
  if (step <= 1) return ['Why is No. 9 running there?', 'Who has created the most space today?', 'Who is in control right now?'];
  if (step <= 3) return ['Why did No. 5 follow the run?', 'What if No. 9 hadn’t run?', 'Why does Ashmoor’s left side keep getting overloaded?'];
  return ['How was the goal made?', 'How hard was that pass?', 'What if No. 9 hadn’t run?'];
}

const has = (q: string, ...patterns: RegExp[]) => patterns.some((p) => p.test(q));

function playerFrom(q: string): string | null {
  const m = q.match(/(?:no\.?|number|#|nº|n°)\s*(\d{1,2})\b/);
  if (!m) return null;
  const team: Team = /ashmoor|ash\b/.test(q) ? 'ash' : 'kes';
  const id = pid(team, Number(m[1]));
  return hasPlayer(id) ? id : null;
}

export function answer(question: string, ctx: Context): Answer {
  const q = question.toLowerCase().trim();
  const base = { question, tools: [] as string[] };

  // Safety first: no odds, betting, personal data or attempts to change the rules (PRD 14.7, 18.7).
  if (has(q, /ignore (all|previous|your)|system prompt|jailbreak|pretend (you|to be)|developer mode/)) {
    return { ...base, state: 'declined', claims: [unverified('I can only answer questions about this match, from its data.')], alternative: { label: 'How was the goal made?', question: 'How was the goal made?' } };
  }
  if (has(q, /\b(odds|bet|bets|betting|gambl|wager|bookie|bookmaker|accumulator|parlay|tip me)\b/)) {
    return { ...base, state: 'declined', claims: [unverified('OffBall doesn’t do odds or betting.')], alternative: { label: 'Show who’s controlling space', question: 'Who is in control right now?' } };
  }
  if (has(q, /\b(address|salary|wages?|girlfriend|wife|husband|phone number|where does .* live|religion|medical|injur)/)) {
    return { ...base, state: 'declined', claims: [unverified('OffBall only covers what happens on the pitch, and every player here is fictional.')], alternative: { label: 'See their off-ball work', question: `What has No. ${player(ctx.fav).num} done off the ball?` } };
  }

  if (has(q, /what if|without (the|his) run|hadn.?t run|had not run|counterfactual|didn.?t run/)) {
    return {
      ...base,
      tools: ['run_counterfactual · 64 re-runs'],
      state: 'ok',
      claims: [
        ok('Without the run, No. 5 stays central and the gap stays shut in 29 of 32 re-runs.', [CF_ID]),
        ok('With the run, the gap opens in 30 of 32.', [CF_ID]),
        ok('Space created by No. 9’s run: 41 m², with a 90% interval of 33–48 m².', [CF_ID, frameRef(3.8)]),
      ],
      chart: {
        title: 'Re-runs where the gap opened',
        spec: barSpec([{ label: 'Without the run', value: 3, team: 'no run' }, { label: 'With the run', value: 30, team: 'run' }], 'Re-runs out of 32', 32),
        summary: 'The gap opened in 3 of 32 re-runs without the run, and 30 of 32 with it.',
        columns: ['Scenario', 'Gap opened (of 32)'],
        rows: [['Without the run', 3], ['With the run', 30]],
      },
    };
  }

  if (has(q, /(follow|track|chase|mark).*(run|9|nine)|why.*(5|five|hendricx)|(5|five|hendricx).*(follow|track)/)) {
    return {
      ...base,
      tools: ['run_kql · follow_rates', 'query_match_state · ash-05'],
      state: 'ok',
      claims: [
        ok('Ashmoor’s No. 5 follows diagonal runs more than most centre-backs: 71% of the time this season, against a league average of 52%.', [`${MATCH_ID}-kql-follow-rates`]),
        ok('Following No. 9 pulled him 10.8 m out of the centre.', [frameRef(2.5), frameRef(4.6)]),
      ],
      chart: {
        title: 'How often centre-backs follow diagonal runs',
        spec: barSpec([{ label: 'Ashmoor No. 5', value: 71, team: 'ash' }, { label: 'League average', value: 52, team: 'league' }], 'Runs followed (%)', 100),
        summary: 'Ashmoor’s No. 5 follows 71% of diagonal runs; the league average is 52%.',
        columns: ['Player', 'Diagonal runs followed (%)'],
        rows: [['Ashmoor No. 5', 71], ['League average', 52]],
      },
    };
  }

  if (has(q, /(most|who).*(space|created)|leaderboard|credit|off.?ball work.*(most|top)/)) {
    return {
      ...base,
      tools: ['query_match_state · credit'],
      state: 'ok',
      claims: [ok(`No. 9 Velmar has created the most space: 118 m² from 7 off-ball runs. Next is No. 7 Quillan with 64 m².`, [`${MATCH_ID}-credit`])],
      chart: {
        title: 'Space Created this match',
        spec: barSpec(LEADERS.map((l) => ({ label: leaderName(l.id), value: l.v, team: player(l.id).team })), 'Space created (m²)'),
        summary: `${LEADERS.map((l) => `${leaderName(l.id)} ${l.v} m²`).join('; ')}.`,
        columns: ['Player', 'Space created (m²)', '90% interval'],
        rows: LEADERS.map((l) => [leaderName(l.id), l.v, `${l.lo}–${l.hi}`]),
      },
    };
  }

  if (has(q, /(overload|left side|left flank|weak side|their left)/)) {
    return {
      ...base,
      tools: ['run_kql · zone_entries', 'query_match_state · ash-03'],
      state: 'partial',
      claims: [
        ok('Kestrel’s No. 7 holds the width on that side, so Ashmoor’s left-back, No. 3, can’t tuck in to help the centre.', [frameRef(0), frameRef(3.8)]),
        ok('Kestrel have entered Ashmoor’s left third 14 times, more than any other zone.', [`${MATCH_ID}-kql-zone-entries`]),
        unverified('Whether No. 3 is tiring, as fans suggest: there isn’t enough tracking yet to say, so I’ve left that out.'),
      ],
      chart: {
        title: 'Kestrel entries by Ashmoor zone',
        spec: barSpec([{ label: 'Ashmoor left', value: 14, team: 'kes' }, { label: 'Centre', value: 9, team: 'kes' }, { label: 'Ashmoor right', value: 7, team: 'kes' }], 'Entries'),
        summary: 'Kestrel entered Ashmoor’s left third 14 times, the centre 9 times and the right 7 times.',
        columns: ['Zone', 'Entries'],
        rows: [['Ashmoor left', 14], ['Centre', 9], ['Ashmoor right', 7]],
      },
    };
  }

  if (has(q, /pass.*(hard|difficult|tough)|difficulty|how hard/)) {
    const [dist, diff] = ctx.passCorrected ? ['27.4', '5.9'] : ['28.0', '6.1'];
    return {
      ...base,
      tools: ['query_match_state · pass_difficulty'],
      state: 'ok',
      corrected: ctx.passCorrected,
      claims: [
        ok(`No. 8’s pass to No. 10 travelled ${dist} m, with a difficulty of ${diff} out of 10.`, [EVENT_PASS]),
        ok('It had to beat Ashmoor’s No. 6, who had stepped up to press.', [frameRef(4.2)]),
      ],
    };
  }

  if (has(q, /\bxg\b|expected goal/)) {
    return {
      ...base,
      tools: ['query_match_state · shots'],
      state: 'ok',
      claims: [ok('No. 10’s shot was worth 0.31 xG: about one goal in three from that spot and situation.', [EVENT_SHOT]), ok('Kestrel’s total this match is 0.74 xG from 5 shots; Ashmoor’s is 0.47 from 3.', [`${MATCH_ID}-shots`])],
    };
  }

  if (has(q, /(season|record|ever|all.?time|history|career)/)) {
    return {
      ...base,
      tools: ['query_match_state · credit', 'search_season · drag_records'],
      state: 'partial',
      claims: [ok('No. 9 has dragged 3 defenders in this match, which ties his season high for one match.', [frameRef(2.5)]), unverified('Whether it’s a league record: I couldn’t check the full league history, so I’ve left that out.')],
    };
  }

  if (has(q, /(fast|quick|speed|sprint|pace)/)) {
    const top = PLAYERS.filter((p) => p.role !== 'GK')
      .map((p) => ({ id: p.id, v: focusStats(p.id).topSpeed }))
      .sort((a, b) => b.v - a.v)
      .slice(0, 5);
    return {
      ...base,
      tools: ['query_match_state · physical'],
      state: 'ok',
      claims: [ok(`The fastest so far is No. ${player(top[0].id).num} ${player(top[0].id).name}, at ${top[0].v.toFixed(1)} km/h.`, [`${MATCH_ID}-physical`])],
      chart: {
        title: 'Top speeds this match',
        spec: barSpec(top.map((r) => ({ label: `No. ${player(r.id).num} ${player(r.id).team.toUpperCase()}`, value: r.v, team: player(r.id).team })), 'Top speed (km/h)'),
        summary: top.map((r) => `No. ${player(r.id).num} ${r.v.toFixed(1)} km/h`).join('; '),
        columns: ['Player', 'Top speed (km/h)'],
        rows: top.map((r) => [`${player(r.id).team.toUpperCase()} No. ${player(r.id).num}`, r.v.toFixed(1)]),
      },
    };
  }

  if (has(q, /(control|on top|dominat|momentum|who.*(better|winning))/)) {
    const now = CONTROL_INDEX[63];
    return {
      ...base,
      tools: ['run_kql · control_index'],
      state: 'ok',
      claims: [ok(`Kestrel are in control: a control index of ${now.kes} against Ashmoor’s ${now.ash}, rising since the 55th minute.`, [`${MATCH_ID}-control-index`])],
      chart: {
        title: 'Control index',
        spec: controlIndexSpec(63),
        summary: `Kestrel’s control index is ${now.kes} and Ashmoor’s is ${now.ash} at 63 minutes.`,
        columns: ['Minute', 'Kestrel Bay', 'Ashmoor'],
        rows: CONTROL_INDEX.filter((d) => d.minute % 5 === 0).map((d) => [d.minute, d.kes, d.ash]),
      },
    };
  }

  if (has(q, /(goal|score|scored|how.*(made|happen)|assist)/)) {
    return {
      ...base,
      tools: ['query_match_state · moment m07-d0031'],
      state: 'ok',
      claims: [
        ok('No. 9 ran diagonally to pull Ashmoor’s No. 5 out of the centre.', [frameRef(1), frameRef(2.5)]),
        ok('That opened a gap just outside the box; No. 10 timed his run into it.', [frameRef(3.8)]),
        ok(ctx.passCorrected ? 'No. 8’s pass (27.4 m, corrected) found him, and he shot low for 1–0.' : 'No. 8’s 28 m pass found him, and he shot low for 1–0.', [EVENT_PASS, EVENT_SHOT]),
      ],
      corrected: ctx.passCorrected,
    };
  }

  const who = playerFrom(q) ?? (has(q, /my player|favourite|favorite/) ? ctx.fav : null);
  if (who || has(q, /off.?ball|why is .* running|running there/)) {
    const id = who ?? 'kes-09';
    const s = focusStats(id);
    const p = player(id);
    return {
      ...base,
      tools: [`query_match_state · ${id}`],
      state: 'ok',
      claims: [ok(`No. ${p.num} ${p.name} has made ${s.runs[1]} off-ball runs, dragged ${s.dragged[1]} defenders and created ${s.space[1]} m² of space.`, [`${MATCH_ID}-credit`, frameRef(ctx.t)]), ok(s.season, [`${MATCH_ID}-season`])],
      chart: {
        title: `No. ${p.num}’s runs by type`,
        spec: barSpec(s.runsByType.map((r) => ({ label: r.type, value: r.n, team: p.team })), 'Runs'),
        summary: s.runsByType.map((r) => `${r.type}: ${r.n}`).join('; '),
        columns: ['Run type', 'Runs'],
        rows: s.runsByType.map((r) => [r.type, r.n]),
      },
    };
  }

  return { ...base, state: 'unknown', claims: [unverified('I can only answer questions about this match’s play, from its data. Try one of these.')] };
}
