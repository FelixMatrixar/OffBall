import { useState } from 'react';
import { clockOf } from '../../lib/player/clock';
import type { ClubInfo, Order, RunOutcome } from '../../lib/player/api';
import { Button, Chip, Segmented, Spinner } from '../ui';
import { pointsFor, type PlayItOut } from './usePlayItOut';

export const OUTCOME_LABEL: Record<RunOutcome, string> = {
  goal: 'GOAL!',
  saved: 'Saved',
  blocked: 'Blocked',
  off_target: 'Wide',
  offside: 'Offside',
  out: 'Out of play',
  lost: 'Ball lost',
  kept: 'Kept the ball',
};

interface Props {
  game: PlayItOut;
  home: ClubInfo;
  away: ClubInfo;
  label: (id: string) => string;
  onExit: () => void;
}

const fmt = (n: number) => n.toFixed(1);

/** One order in words, as the board draws it. */
function orderText(o: Order, label: (id: string) => string): string {
  const to = o.to_xy ? `(${Math.round(o.to_xy[0])}, ${Math.round(o.to_xy[1])})` : '';
  const who = o.target_id ? label(o.target_id) : '';
  const verb: Record<Order['action'], string> = {
    run: `runs to ${to}`,
    support: `supports at ${to}`,
    carry: `carries the ball to ${to}`,
    pass: `passes to ${who}`,
    shoot: 'shoots',
    press: 'presses the ball',
    mark: `marks ${who}`,
    track: `tracks ${who}`,
    cover: `covers ${who}`,
    hold: `holds ${to}`,
  };
  return `${label(o.player_id)} ${verb[o.action]}`;
}

/**
 * Play it out (PRD 10.10): the controls beside the board. Set the scene, give orders or ask the Coach, play it
 * out in the match engine, watch every run, and then defend what just worked.
 */
export function PlayItOutPanel({ game: g, home, away, label, onExit }: Props) {
  const [goal, setGoal] = useState('');
  const club = (id: string) => (id === home.club_id ? home : away);
  const attackClub = club(g.attacking);
  const defendClub = g.attacking === home.club_id ? away : home;
  const mine = g.orders.map((o, k) => ({ o, k })).filter(({ o }) => g.commandable(o.player_id));
  const theirs = g.orders.filter((o) => !g.commandable(o.player_id));
  const res = g.result;
  const shown = res ? res.out.runs[g.run] : null;

  if (!g.board) {
    return (
      <section className="card stack play-panel" style={{ gap: 12 }}>
        <h2 className="card-title" style={{ margin: 0, fontSize: 22 }}>
          Play it out
        </h2>
        {g.failed ? (
          <p role="alert" className="muted">
            {g.failed}
          </p>
        ) : (
          <p className="cluster muted" role="status" style={{ gap: 8 }}>
            <Spinner /> Setting up the board from this moment…
          </p>
        )}
        <Button variant="ghost" className="btn-sm" onClick={onExit}>
          Back to the match
        </Button>
      </section>
    );
  }

  return (
    <section className="card stack play-panel anim-rise" style={{ gap: 14 }} aria-label="Play it out">
      <header className="cluster" style={{ justifyContent: 'space-between' }}>
        <div>
          <h2 className="card-title" style={{ margin: 0, fontSize: 22 }}>
            Play it out
          </h2>
          <p className="muted" style={{ margin: 0, fontSize: 13 }}>
            From {clockOf({ period: g.board.period, t_ms: g.board.t_ms })} · the match engine plays your plan 8 times
          </p>
        </div>
        <Button variant="ghost" className="btn-sm" onClick={onExit}>
          Back to the match
        </Button>
      </header>

      <div className="play-score" aria-label="Your score">
        <span>
          <span className="card-label">Attack</span>
          <span key={`a${g.score.attack}`} className="display tabular anim-pop">
            {g.score.attack}
          </span>
        </span>
        <span>
          <span className="card-label">Defence</span>
          <span key={`d${g.score.defend}`} className="display tabular anim-pop">
            {g.score.defend}
          </span>
        </span>
        <span className="muted" style={{ fontSize: 12, alignSelf: 'end' }}>
          {g.score.plays} {g.score.plays === 1 ? 'play' : 'plays'} · goal 3, other shot 1 · every stop 1
        </span>
      </div>

      <Segmented
        options={[
          { value: 'attack', label: `Attack · ${attackClub.short}` },
          { value: 'defend', label: `Defend · ${defendClub.short}` },
        ]}
        value={g.side}
        onChange={g.setSide}
        label="Your side"
      />
      <p className="muted" style={{ margin: 0, fontSize: 13, lineHeight: 1.5 }}>
        {g.side === 'attack'
          ? 'Tap one of your players (dashed ring), then tap where he runs, a teammate to pass to, or the goal to shoot. Drag anyone to move them. The dashed line is the offside line.'
          : 'Tap a defender (dashed ring), then tap the player on the ball to press him, an attacker to mark, a teammate to cover, or a spot to hold.'}
      </p>

      {g.selected && (
        <div className="cluster play-selected" style={{ gap: 8 }}>
          <Chip tone="space">{label(g.selected)}</Chip>
          {g.selected !== g.ballOwner && (
            <Button variant="ghost" className="btn-sm" onClick={() => g.giveBall(g.selected!)}>
              Give him the ball
            </Button>
          )}
          <Button variant="ghost" className="btn-sm" onClick={() => g.setSelected(null)}>
            Done
          </Button>
        </div>
      )}

      <div className="stack" style={{ gap: 6 }}>
        <div className="cluster" style={{ justifyContent: 'space-between' }}>
          <h3 className="card-h3" style={{ margin: 0 }}>
            Your orders
          </h3>
          {mine.length > 0 && (
            <Button variant="ghost" className="btn-sm" onClick={g.clearSide}>
              Clear
            </Button>
          )}
        </div>
        {mine.length === 0 && <p className="muted" style={{ margin: 0, fontSize: 13 }}>None yet: everyone plays as the engine’s players would.</p>}
        <ul className="play-orders">
          {mine.map(({ o, k }) => (
            <li key={k}>
              <span>{orderText(o, label)}</span>
              {(o.action === 'pass' || o.action === 'shoot') && o.player_id === g.ballOwner && (
                <span className="cluster" style={{ gap: 4 }}>
                  <button type="button" className="chip-x press" aria-label="Sooner" onClick={() => g.timeOrder(k, o.at_s - 0.5)}>
                    −
                  </button>
                  <span className="mono" style={{ fontSize: 12 }}>
                    {fmt(o.at_s)}s
                  </span>
                  <button type="button" className="chip-x press" aria-label="Later" onClick={() => g.timeOrder(k, o.at_s + 0.5)}>
                    +
                  </button>
                </span>
              )}
              <button type="button" className="chip-x press" aria-label={`Remove: ${orderText(o, label)}`} onClick={() => g.removeOrder(k)}>
                ×
              </button>
            </li>
          ))}
        </ul>
        {theirs.length > 0 && (
          <p className="muted" style={{ margin: 0, fontSize: 12 }}>
            The other side has {theirs.length} {theirs.length === 1 ? 'order' : 'orders'} on the board.
          </p>
        )}
      </div>

      <form
        className="stack play-coach"
        style={{ gap: 8 }}
        onSubmit={(e) => {
          e.preventDefault();
          g.ask(goal);
        }}
      >
        <label htmlFor="coach-goal" className="card-h3" style={{ margin: 0 }}>
          Ask the Coach
        </label>
        <div className="cluster" style={{ gap: 8 }}>
          <input
            id="coach-goal"
            className="input"
            style={{ flex: 1, minWidth: 0 }}
            value={goal}
            onChange={(e) => setGoal(e.target.value)}
            placeholder={g.side === 'attack' ? 'A shot from the edge of the box' : 'Stop the shot'}
          />
          <Button type="submit" variant="secondary" className="btn-sm" disabled={g.coach.state === 'asking'}>
            {g.side === 'attack' ? 'Plan my attack' : 'Plan my defence'}
          </Button>
        </div>
        {g.coach.state === 'asking' && (
          <p className="cluster muted" role="status" style={{ margin: 0, fontSize: 13, gap: 8 }}>
            <Spinner /> The Coach is drawing it up and trying it in the engine…
          </p>
        )}
        {g.coach.state === 'none' && (
          <p role="alert" className="muted" style={{ margin: 0, fontSize: 13 }}>
            {g.coach.error ?? 'The Coach couldn’t find a plan the engine can play here. Move a player, or try asking another way.'}
          </p>
        )}
        {g.coach.plan && g.coach.state === 'idle' && (
          <div className="whatif-words">
            <p className="display" style={{ margin: 0, fontSize: 19 }}>
              {g.coach.plan.headline}
            </p>
            <p style={{ margin: 0, lineHeight: 1.5, fontSize: 14 }}>{g.coach.plan.explanation}</p>
            <span className="cluster" style={{ gap: 6 }}>
              {g.coach.plan.tested && (
                <Chip tone="outline">
                  Tried {g.coach.plan.tested.runs} times: {g.coach.plan.tested.shots} {g.coach.plan.tested.shots === 1 ? 'shot' : 'shots'}, {g.coach.plan.tested.goals} {g.coach.plan.tested.goals === 1 ? 'goal' : 'goals'}
                </Chip>
              )}
              <Chip tone="muted">AI-generated</Chip>
            </span>
          </div>
        )}
      </form>

      <Button variant="primary" size="lg" onClick={g.play} disabled={g.running}>
        {g.running ? (
          <>
            <Spinner /> Playing it out 8 times…
          </>
        ) : (
          '▶ Play it out'
        )}
      </Button>
      {g.failed && (
        <p role="alert" className="muted" style={{ margin: 0, fontSize: 13 }}>
          {g.failed}
        </p>
      )}

      {res && shown && (
        <div className="stack play-result anim-rise" style={{ gap: 10 }}>
          <div className="cluster" style={{ justifyContent: 'space-between' }}>
            <span className="display play-outcome" data-outcome={shown.outcome}>
              {g.decided || !g.playback ? OUTCOME_LABEL[shown.outcome] : '…'}
            </span>
            <Chip tone="space">+{pointsFor(res.out, res.side)} pts</Chip>
          </div>
          <p style={{ margin: 0, fontSize: 14 }}>
            {res.out.summary.runs} runs: {res.out.summary.shots} {res.out.summary.shots === 1 ? 'shot' : 'shots'}, {res.out.summary.goals} {res.out.summary.goals === 1 ? 'goal' : 'goals'}
            {res.out.summary.shots > 0 && <>, chances worth {fmt(res.out.summary.xg * res.out.summary.runs)} goals</>}
            {shown.xg > 0 && <> · this shot {Math.round(shown.xg * 100)}% to score</>}
          </p>
          <div className="play-runs" role="group" aria-label="Watch each run">
            {res.out.runs.map((r, k) => (
              <button key={k} type="button" className="play-run press" data-outcome={r.outcome} aria-pressed={k === g.run} title={`Run ${k + 1}: ${OUTCOME_LABEL[r.outcome]}`} onClick={() => g.watch(res.out, k)}>
                {k + 1}
              </button>
            ))}
            <Button variant="ghost" className="btn-sm" onClick={() => g.watch(res.out, g.run)}>
              ↻ Watch again
            </Button>
          </div>
          {res.side === 'attack' && !res.withDefence && (
            <Button variant="secondary" onClick={g.defendIt}>
              Now defend it →
            </Button>
          )}
          {res.withDefence && g.baseline && (
            <p className="whatif-words" style={{ margin: 0, fontSize: 14 }}>
              Without the defence’s orders: {g.baseline.summary.shots} shots, {g.baseline.summary.goals} goals. With them: {res.out.summary.shots} shots, {res.out.summary.goals} goals.
            </p>
          )}
          <Button variant="ghost" className="btn-sm" onClick={g.edit}>
            Change the plan
          </Button>
        </div>
      )}
    </section>
  );
}
