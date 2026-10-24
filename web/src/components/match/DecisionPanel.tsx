import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode, type RefObject } from 'react';
import { DECISIONS, RERUNS, AS_PLAYED, actualOf, alternatives, counterfactualId, decisionOf, rankOf, scenarioFor, wordsOf, type DecisionPoint, type Option, type Result, type Scenario } from '../../lib/decisions';
import type { MatchClock } from '../../lib/feed';
import { PACKS, fill, useI18n } from '../../lib/i18n';
import type { DecideStrings, DecisionOptionId } from '../../lib/i18n/types';
import { LABELS } from '../../lib/i18n/labels';
import { clockLabel, player } from '../../lib/match';
import type { Mode } from '../../lib/prefs';
import { cx } from '../../lib/cx';
import { Button, Chip, CountUp, Skeleton, Spinner, Stepper, Switch, VerifiedChip, stagger } from '../ui';

export type DecisionPhase = 'pick' | 'choose' | 'running' | 'result';

/** How long the replay's precomputed re-runs take to "run", so the step reads as a re-run rather than a jump (PRD 15.12). */
const RUN_MS = 1800;
/** A result replays from a moment before the decision, so the viewer sees the two worlds part. */
const LEAD_IN = 0.8;

const capitalise = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

/** A player as the panel names them in the viewer's language: "No. 9", or "Ashmoor’s No. 5". */
const whoIn = (D: DecideStrings, id: string) => {
  const p = player(id);
  return fill(p.team === 'kes' ? D.who : D.whoAway, { num: p.num });
};

/**
 * Change one decision (PRD 10.10, 15.12): pick a player, choose what they do instead, re-run the moment 32 times and
 * see the changed world. The state lives here; the match view draws the pitch from `scenario` and `pickable`, and its
 * caption from `verdict`.
 */
export function useDecisions(clock: MatchClock, mode: Mode, announce: (text: string) => void) {
  const { lang, pack } = useI18n();
  const D = pack.decide;
  const [open, setOpen] = useState(false);
  const [phase, setPhase] = useState<DecisionPhase>('pick');
  const [pointId, setPointId] = useState<string | null>(null);
  const [optionId, setOptionId] = useState<DecisionOptionId | null>(null);
  const [runs, setRuns] = useState(0);
  const [split, setSplit] = useState(false);
  const timer = useRef<number | null>(null);
  const clockRef = useRef(clock);
  clockRef.current = clock;
  // The words a callback reads when it fires, in the language on screen then.
  const wordsRef = useRef({ D, lang });
  wordsRef.current = { D, lang };

  const point = DECISIONS.find((d) => d.id === pointId) ?? null;
  const option = optionId ? (decisionOf(optionId)?.option ?? null) : null;
  const words = optionId ? wordsOf(D.choices, PACKS.en.decide.choices, optionId) : null;
  const analyst = mode === 'analyst' || mode === 'broadcaster';
  const stopTimer = () => {
    if (timer.current !== null) window.clearInterval(timer.current);
    timer.current = null;
  };
  useEffect(() => stopTimer, []);

  const start = useCallback(() => {
    stopTimer();
    clockRef.current.pause();
    setOpen(true);
    setPhase('pick');
    setPointId(null);
    setOptionId(null);
    setSplit(false);
  }, []);
  const close = useCallback(() => {
    stopTimer();
    setOpen(false);
    setPhase('pick');
    setPointId(null);
    setOptionId(null);
    setSplit(false);
  }, []);
  const pick = useCallback(
    (id: string) => {
      const { D } = wordsRef.current;
      const p = DECISIONS.find((d) => d.id === id || d.player === id);
      if (!p) {
        announce(capitalise(fill(D.noDecision, { who: whoIn(D, id) })));
        return;
      }
      stopTimer();
      setPointId(p.id);
      setOptionId(null);
      setPhase('choose');
      clockRef.current.scrub(p.t);
      announce(`${clockLabel(p.t)}. ${D.points[p.id].question}`);
    },
    [announce],
  );
  const choose = useCallback((id: DecisionOptionId) => setOptionId(id), []);
  const run = useCallback(() => {
    const found = optionId ? decisionOf(optionId) : null;
    if (!found) return;
    stopTimer();
    setPhase('running');
    setRuns(0);
    const begun = performance.now();
    timer.current = window.setInterval(() => {
      const n = Math.min(RERUNS, Math.round(((performance.now() - begun) / RUN_MS) * RERUNS));
      setRuns(n);
      if (n < RERUNS) return;
      stopTimer();
      setPhase('result');
      const c = clockRef.current;
      c.scrub(Math.max(0, found.point.t - LEAD_IN));
      c.play();
      const w = wordsOf(wordsRef.current.D.choices, PACKS.en.decide.choices, found.option.id);
      announce(`${capitalise(w.world)}: ${analyst ? found.option.analyst : w.plain}`);
    }, 60);
  }, [optionId, announce, analyst]);
  const cancel = useCallback(() => {
    stopTimer();
    setPhase('choose');
    announce(wordsRef.current.D.cancelled);
  }, [announce]);
  const replay = useCallback(() => {
    if (!point) return;
    clockRef.current.scrub(Math.max(0, point.t - LEAD_IN));
    clockRef.current.play();
  }, [point]);
  const otherOption = useCallback(() => {
    if (!point) return;
    setPhase('choose');
    setSplit(false);
    clockRef.current.scrub(point.t);
  }, [point]);

  // The pitch: a preview of the chosen path while choosing and re-running, the changed world once it's back.
  const scenario: Scenario | null = useMemo(() => {
    if (!open || !optionId || !point || !words || phase === 'pick') return null;
    const tag = `${fill(LABELS[lang].no, { num: player(point.player).num })} · ${words.label}`;
    return scenarioFor(optionId, mode, phase === 'result' ? 'result' : 'preview', { tag, ring: words.ring, plain: words.plain, world: words.world }, lang);
  }, [open, optionId, point, words?.label, words?.ring, words?.plain, words?.world, phase, mode, lang]);
  // Rings mark who can be picked, only while picking: once chosen, the dashed paths are the picture.
  const pickable = useMemo(() => (open && phase === 'pick' ? DECISIONS.map((d) => d.player) : []), [open, phase]);
  // What the caption says while the changed world plays.
  const verdict = phase === 'result' && option && words ? (analyst ? option.analyst : words.plain) : null;

  return { open, phase, point, option, words, verdict, runs, split, setSplit, scenario, pickable, start, close, pick, choose, run, cancel, replay, otherOption };
}

export type Decisions = ReturnType<typeof useDecisions>;

const STEP_OF: Record<DecisionPhase, number> = { pick: 0, choose: 1, running: 2, result: 3 };

/**
 * The decision panel: it takes the side panel's place (the bottom sheet on phones) while it's open. `titled` is false
 * where its container already says "Change one decision", as the bottom sheet does.
 */
export function DecisionPanel({ d, mode, canSplit, titled = true }: { d: Decisions; mode: Mode; canSplit: boolean; titled?: boolean }) {
  const { pack } = useI18n();
  const D = pack.decide;
  const analyst = mode === 'analyst' || mode === 'broadcaster';
  const heading = useRef<HTMLHeadingElement>(null);
  // Each step's heading takes focus, so a keyboard or screen-reader user lands where the new content starts.
  useEffect(() => {
    heading.current?.focus({ preventScroll: true });
  }, [d.phase, d.point?.id]);

  return (
    <section className="card decision anim-rise" aria-labelledby="decision-title">
      <div className="decision-head">
        <div className={titled ? undefined : 'sr-only'}>
          <p className="card-label" style={{ marginBottom: 2 }}>
            {D.kicker}
          </p>
          <h2 id="decision-title" className="card-title" style={{ margin: 0 }}>
            {D.title}
          </h2>
        </div>
        <Button variant="ghost" className="btn-sm" onClick={d.close}>
          {D.back}
        </Button>
      </div>
      <Stepper steps={D.steps} current={STEP_OF[d.phase]} />

      <div key={`${d.phase}:${d.point?.id ?? ''}`} className="decision-body anim-rise">
        {d.phase === 'pick' && <PickStep d={d} D={D} headingRef={heading} />}
        {d.phase === 'choose' && d.point && <ChooseStep d={d} D={D} point={d.point} analyst={analyst} headingRef={heading} />}
        {d.phase === 'running' && d.point && d.words && <RunningStep d={d} D={D} point={d.point} world={d.words.world} headingRef={heading} />}
        {d.phase === 'result' && d.point && d.option && d.words && <ResultStep d={d} D={D} point={d.point} option={d.option} world={d.words.world} verdict={d.verdict ?? ''} analyst={analyst} canSplit={canSplit} headingRef={heading} />}
      </div>

      <p className="decision-note">{D.note}</p>
    </section>
  );
}

type HeadingRef = RefObject<HTMLHeadingElement>;

function StepHeading({ headingRef, children }: { headingRef: HeadingRef; children: ReactNode }) {
  return (
    <h3 ref={headingRef} tabIndex={-1} className="decision-step-title">
      {children}
    </h3>
  );
}

function PickStep({ d, D, headingRef }: { d: Decisions; D: DecideStrings; headingRef: HeadingRef }) {
  return (
    <>
      <StepHeading headingRef={headingRef}>{D.whose}</StepHeading>
      <p className="decision-hint">{D.pickHint}</p>
      <ul className="decision-list">
        {DECISIONS.map((p, i) => {
          const pl = player(p.player);
          return (
            <li key={p.id} className="anim-rise" style={stagger(i)}>
              <button type="button" className="choice press decision-player" onClick={() => d.pick(p.id)}>
                <span className="decision-shirt" data-team={pl.team} aria-hidden="true">
                  {pl.num}
                </span>
                <span className="decision-player-text">
                  <span className="decision-player-name">
                    {capitalise(whoIn(D, p.player))} · {pl.name}
                  </span>
                  <span className="decision-player-what">
                    {D.points[p.id].what} · <span className="tabular">{clockLabel(p.t)}</span>
                  </span>
                </span>
                <span className="chip chip-muted">{fill(D.optionCount, { n: p.options.length })}</span>
              </button>
            </li>
          );
        })}
      </ul>
    </>
  );
}

function ChooseStep({ d, D, point, analyst, headingRef }: { d: Decisions; D: DecideStrings; point: DecisionPoint; analyst: boolean; headingRef: HeadingRef }) {
  const actual = actualOf(point);
  const options = alternatives(point);
  const said = D.choices[actual.id];
  return (
    <>
      <StepHeading headingRef={headingRef}>
        {D.points[point.id].question} <span className="decision-time tabular">{clockLabel(point.t)}</span>
      </StepHeading>
      <div className="decision-actual">
        <Chip tone="outline">{D.happened}</Chip>
        <span>
          <strong>{said.label}</strong>
          <span className="decision-sub">{said.detail}</span>
        </span>
        {analyst && <ValueBar option={actual} point={point} />}
      </div>
      <fieldset className="decision-options">
        <legend className="decision-legend">{fill(D.instead, { who: whoIn(D, point.player) })}</legend>
        {options.map((o, i) => {
          const on = d.option?.id === o.id;
          const w = D.choices[o.id];
          return (
            <label key={o.id} className={cx('choice', 'press', 'decision-option', 'anim-rise')} data-checked={on} style={stagger(i)}>
              <input type="radio" name="decision-option" value={o.id} checked={on} onChange={() => d.choose(o.id)} />
              <span className="decision-radio" aria-hidden="true" />
              <span className="decision-option-text">
                <span className="decision-option-label">{w.label}</span>
                <span className="decision-sub">{w.detail}</span>
                {analyst && <ValueBar option={o} point={point} />}
                {!analyst && Math.abs(o.value - actual.value) <= 0.02 && <span className="decision-close">{D.nearly}</span>}
              </span>
            </label>
          );
        })}
      </fieldset>
      <div className="decision-actions">
        <Button variant="primary" onClick={d.run} disabled={!d.option}>
          {fill(D.rerun, { n: RERUNS })}
        </Button>
        <Button variant="ghost" onClick={d.start}>
          {D.anotherPlayer}
        </Button>
      </div>
      {d.option ? (
        <p className="decision-legend-key">
          <span className="decision-key decision-key-real" aria-hidden="true" /> {D.keyReal}
          <span className="decision-key decision-key-changed" aria-hidden="true" /> {D.keyChanged}
          <span className="decision-key decision-key-hold" aria-hidden="true" /> {D.keyHold}
        </p>
      ) : (
        <p className="decision-hint">{D.chooseHint}</p>
      )}
    </>
  );
}

/** Modelled value with its rank, for Analyst: a bar on a 0–1 scale. English, like the rest of the Analyst panel. */
function ValueBar({ option, point }: { option: Option; point: DecisionPoint }) {
  const rank = rankOf(point, option);
  return (
    <span className="decision-value">
      <span className="decision-value-track" aria-hidden="true">
        <span className="decision-value-fill" style={{ transform: `scaleX(${option.value})` }} />
      </span>
      <span className="tabular">
        Value {option.value.toFixed(2)} · ranked {rank} of {point.options.length}
      </span>
    </span>
  );
}

function RunningStep({ d, D, point, world, headingRef }: { d: Decisions; D: DecideStrings; point: DecisionPoint; world: string; headingRef: HeadingRef }) {
  return (
    <>
      <StepHeading headingRef={headingRef}>{fill(D.running, { clock: clockLabel(point.t), world })}</StepHeading>
      <div role="status" className="decision-running">
        <Spinner />
        <span>{fill(D.runningLine, { n: RERUNS })}</span>
      </div>
      <div className="decision-progress" aria-hidden="true">
        <span className="decision-progress-fill" style={{ transform: `scaleX(${d.runs / RERUNS})` }} />
      </div>
      <p className="decision-count tabular" aria-hidden="true">
        {fill(D.reRuns, { n: d.runs, total: RERUNS })}
      </p>
      <Skeleton height={96} radius={10} />
      <div className="decision-actions">
        <Button variant="ghost" onClick={d.cancel}>
          {D.cancel}
        </Button>
      </div>
    </>
  );
}

interface Row {
  label: string;
  played: number;
  changed: number;
  /** Out of 32 re-runs: drawn as bars. Otherwise a number with a unit. */
  of?: number;
  unit?: string;
  decimals?: number;
  note?: string;
}

function rowsFor(D: DecideStrings, r: Result, analyst: boolean): Row[] {
  const rows: Row[] = [
    { label: D.gap, played: AS_PLAYED.gapOpens, changed: r.gapOpens, of: RERUNS },
    { label: D.shots, played: AS_PLAYED.shots, changed: r.shots, of: RERUNS },
    { label: D.goals, played: AS_PLAYED.goals, changed: r.goals, of: RERUNS },
    { label: D.space, played: AS_PLAYED.space[0], changed: r.space[0], unit: 'm²', note: analyst ? `90% interval ${r.space[1]}–${r.space[2]} m²` : undefined },
  ];
  if (analyst) rows.push({ label: 'Best chance xG', played: AS_PLAYED.xg, changed: r.xg, decimals: 2 });
  if (r.offside) rows.push({ label: D.offside, played: 0, changed: r.offside, of: RERUNS });
  return rows;
}

function ResultStep({ d, D, point, option, world, verdict, analyst, canSplit, headingRef }: { d: Decisions; D: DecideStrings; point: DecisionPoint; option: Option; world: string; verdict: string; analyst: boolean; canSplit: boolean; headingRef: HeadingRef }) {
  const { ui } = useI18n();
  const rows = rowsFor(D, option.result, analyst);
  return (
    <>
      <StepHeading headingRef={headingRef}>{capitalise(world)}</StepHeading>
      <p className="decision-verdict">{verdict}</p>
      <table className="decision-compare">
        <caption className="sr-only">{fill(D.compare, { n: RERUNS, world })}</caption>
        <thead>
          <tr>
            <th scope="col">
              <span className="sr-only">{D.measure}</span>
            </th>
            <th scope="col">{D.asPlayed}</th>
            <th scope="col">{D.changed}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={r.label} className="anim-rise" style={stagger(i + 1)}>
              <th scope="row">
                {r.label}
                {r.note && <span className="decision-sub">{r.note}</span>}
              </th>
              <td>
                <Figure D={D} row={r} value={r.played} tone="played" />
              </td>
              <td>
                <Figure D={D} row={r} value={r.changed} tone="changed" animate />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="cluster decision-chips">
        <VerifiedChip label={ui.factChecked} />
        <Chip tone="muted">{fill(D.from, { n: RERUNS, clock: clockLabel(point.t) })}</Chip>
        {analyst && <Chip tone="outline">{counterfactualId(option.id)}</Chip>}
      </div>
      <div className="decision-actions">
        <Button variant="primary" onClick={d.replay}>
          {D.again}
        </Button>
        {canSplit && <Switch checked={d.split} onChange={d.setSplit} label={D.sideBySide} />}
      </div>
      <div className="decision-actions">
        <Button variant="ghost" onClick={d.otherOption}>
          {D.otherOption}
        </Button>
        <Button variant="ghost" onClick={d.start}>
          {D.anotherPlayer}
        </Button>
      </div>
    </>
  );
}

/** One figure in the comparison: a count out of 32 with its bar, or a number with its unit, in the viewer's digits. */
function Figure({ D, row, value, tone, animate = false }: { D: DecideStrings; row: Row; value: number; tone: 'played' | 'changed'; animate?: boolean }) {
  const { num } = useI18n();
  const shown = (n: number) => num(n, row.decimals ?? 0);
  const text = row.of ? fill(D.outOf, { n: value, total: row.of }) : `${shown(value)}${row.unit ? ` ${row.unit}` : ''}`;
  return (
    <span className="decision-figure" data-tone={tone}>
      <span className="decision-figure-value tabular">
        <span className="sr-only">{text}</span>
        <span aria-hidden="true">
          {animate ? <CountUp value={value} format={shown} /> : shown(value)}
          {row.of ? <span className="decision-figure-of"> /{row.of}</span> : row.unit ? <span className="decision-figure-of"> {row.unit}</span> : null}
        </span>
      </span>
      {row.of !== undefined && (
        <span className="decision-bar" aria-hidden="true">
          <span className="decision-bar-fill" style={{ transform: `scaleX(${value / row.of})` }} />
        </span>
      )}
    </span>
  );
}
