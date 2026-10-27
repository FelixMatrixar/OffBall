// Play it out's game state: the board a viewer sets up, the orders they give, the Coach's plans, the engine's
// playouts and the score. The match view draws it; this keeps it.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ApiError } from '../../lib/api';
import type { XY } from '../../lib/match';
import { askCoach, fetchBoard, playOut, type Board, type CoachPlan, type Order, type OrderAction, type PlayOut, type RunOutcome } from '../../lib/player/api';
import type { Playback, Tap } from './PlayBoard';

export type Side = 'attack' | 'defend';
const BALL_ORDERS: readonly OrderAction[] = ['pass', 'shoot'];
const ATTACK: readonly OrderAction[] = ['run', 'support', 'carry', 'pass', 'shoot'];
const SHOTS: readonly RunOutcome[] = ['goal', 'saved', 'blocked', 'off_target'];

/** Points for a playout: a goal is 3, any other shot 1 when attacking; each run without a goal is 1 when defending. */
export function pointsFor(result: PlayOut, side: Side): number {
  const runs = result.runs;
  if (side === 'attack') return runs.reduce((n, r) => n + (r.outcome === 'goal' ? 3 : SHOTS.includes(r.outcome) ? 1 : 0), 0);
  return runs.filter((r) => r.outcome !== 'goal').length;
}

/** The run to show first: a goal if there was one, else a shot, else the first. */
const showcaseRun = (r: PlayOut) => {
  const goal = r.runs.findIndex((x) => x.outcome === 'goal');
  if (goal >= 0) return goal;
  const shot = r.runs.findIndex((x) => SHOTS.includes(x.outcome));
  return shot >= 0 ? shot : 0;
};

/** When a run's result happens: its shot or the last event that decided it, else its end. */
export function decidedAt(r: PlayOut, k: number): number {
  const run = r.runs[k];
  const key = run.events.find((e) => (e.type === 'shot' && e.player_id === run.shooter) || e.type === 'offside');
  const end = (run.frames.length - 1) * r.step_ms;
  return key ? Math.min(end, key.t_ms + 700) : end;
}

interface Options {
  matchId: string;
  clubOf: (id: string) => string;
}

export function usePlayItOut({ matchId, clubOf }: Options) {
  const [board, setBoard] = useState<Board | null>(null);
  const [loading, setLoading] = useState(false);
  const [failed, setFailed] = useState<string | null>(null);
  const [positions, setPositions] = useState<Record<string, XY>>({});
  const [ballOwner, setBallOwner] = useState('');
  const [orders, setOrders] = useState<Order[]>([]);
  const [side, setSide] = useState<Side>('attack');
  const [selected, setSelected] = useState<string | null>(null);
  const [coach, setCoach] = useState<{ state: 'idle' | 'asking' | 'none'; plan?: CoachPlan; error?: string }>({ state: 'idle' });
  const [result, setResult] = useState<{ out: PlayOut; side: Side; withDefence: boolean } | null>(null);
  const [baseline, setBaseline] = useState<PlayOut | null>(null);
  const [running, setRunning] = useState(false);
  const [run, setRun] = useState(0);
  const [playback, setPlayback] = useState<Playback | null>(null);
  const [decided, setDecided] = useState(false);
  const [score, setScore] = useState({ attack: 0, defend: 0, plays: 0 });
  const timer = useRef<number>();

  const attacking = ballOwner ? clubOf(ballOwner) : (board?.attacking ?? '');
  const isAttacker = useCallback((id: string) => clubOf(id) === attacking, [clubOf, attacking]);
  const commandable = useCallback((id: string) => (side === 'attack' ? isAttacker(id) : !isAttacker(id)), [side, isAttacker]);
  const goalX = board?.attacks_towards_x[attacking] ?? 105;

  // The defence's offside line: its second-last player towards its own goal, the goal being attacked.
  const offsideX = useMemo(() => {
    const own = goalX;
    const xs = Object.entries(positions)
      .filter(([id]) => !isAttacker(id))
      .map(([, p]) => p[0])
      .sort((a, b) => Math.abs(a - own) - Math.abs(b - own));
    return xs.length > 1 ? xs[1] : null;
  }, [positions, goalX, isAttacker]);

  const start = useCallback(
    (period: number, t_ms: number) => {
      setLoading(true);
      setFailed(null);
      setResult(null);
      setBaseline(null);
      setPlayback(null);
      setOrders([]);
      setSelected(null);
      setCoach({ state: 'idle' });
      setSide('attack');
      fetchBoard(matchId, period, t_ms)
        .then((b) => {
          setBoard(b);
          setPositions(b.players);
          setBallOwner(b.ball_owner);
        })
        .catch(() => setFailed('The board couldn’t be set up from this moment.'))
        .finally(() => setLoading(false));
    },
    [matchId],
  );

  const exit = useCallback(() => {
    window.clearTimeout(timer.current);
    setBoard(null);
    setPlayback(null);
    setResult(null);
  }, []);

  /** Back to setting up: the board stops playing back. */
  const edit = useCallback(() => {
    window.clearTimeout(timer.current);
    setPlayback(null);
    setDecided(false);
  }, []);

  const move = useCallback(
    (id: string, xy: XY) => {
      edit();
      setPositions((p) => ({ ...p, [id]: xy }));
    },
    [edit],
  );

  /** One movement order and one on-the-ball order per player; a new one replaces the old. */
  const give = useCallback(
    (o: Order) => {
      edit();
      const ball = BALL_ORDERS.includes(o.action);
      setOrders((all) => [...all.filter((x) => x.player_id !== o.player_id || BALL_ORDERS.includes(x.action) !== ball), o]);
      setSelected(null);
    },
    [edit],
  );

  const giveBall = useCallback(
    (id: string) => {
      edit();
      const flips = clubOf(id) !== attacking;
      setBallOwner(id);
      // The ball changing sides turns attack into defence: every order belongs to the old picture.
      setOrders((all) => (flips ? [] : all.filter((o) => !(o.action === 'carry' && o.player_id !== id))));
      setSelected(null);
    },
    [edit, clubOf, attacking],
  );

  const tap = useCallback(
    (t: Tap) => {
      const sel = selected;
      if (!sel) {
        if (t.player && commandable(t.player)) setSelected(t.player);
        return;
      }
      if (t.player === sel) {
        setSelected(null);
        return;
      }
      const onBall = sel === ballOwner;
      if (isAttacker(sel)) {
        if (t.player && isAttacker(t.player)) {
          // A pass from whoever will have the ball; anyone else, the tap picks that player instead.
          if (onBall || orders.some((o) => o.action === 'pass' && o.target_id === sel)) give({ player_id: sel, action: 'pass', target_id: t.player, at_s: onBall ? 1 : 0 });
          else setSelected(t.player);
          return;
        }
        if (t.player) return;
        if (t.goal) give({ player_id: sel, action: 'shoot', at_s: onBall ? 1 : 0 });
        else give({ player_id: sel, action: onBall ? 'carry' : 'run', to_xy: [Math.round(t.xy[0] * 10) / 10, Math.round(t.xy[1] * 10) / 10], at_s: 0 });
        return;
      }
      if (t.player) {
        if (t.player === ballOwner) give({ player_id: sel, action: 'press', at_s: 0 });
        else if (isAttacker(t.player)) give({ player_id: sel, action: 'mark', target_id: t.player, at_s: 0 });
        else if (commandable(t.player) && !orders.some((o) => o.player_id === sel)) setSelected(t.player);
        else give({ player_id: sel, action: 'cover', target_id: t.player, at_s: 0 });
        return;
      }
      give({ player_id: sel, action: 'hold', to_xy: [Math.round(t.xy[0] * 10) / 10, Math.round(t.xy[1] * 10) / 10], at_s: 0 });
    },
    [selected, commandable, ballOwner, isAttacker, orders, give],
  );

  const removeOrder = useCallback(
    (k: number) => {
      edit();
      setOrders((all) => all.filter((_, i) => i !== k));
    },
    [edit],
  );
  const timeOrder = useCallback(
    (k: number, at_s: number) => {
      edit();
      setOrders((all) => all.map((o, i) => (i === k ? { ...o, at_s: Math.max(0, Math.min(6, Math.round(at_s * 2) / 2)) } : o)));
    },
    [edit],
  );
  const clearSide = useCallback(() => {
    edit();
    setOrders((all) => all.filter((o) => !commandable(o.player_id)));
  }, [edit, commandable]);

  const setup = useCallback(() => ({ period: board!.period, t_ms: board!.t_ms, positions, ball_owner: ballOwner, orders }), [board, positions, ballOwner, orders]);

  const ask = useCallback(
    (goal: string, forSide: Side = side) => {
      if (!board) return;
      setCoach({ state: 'asking' });
      // Asking for a defence sends the attack it should stop; asking for an attack starts it afresh.
      const attack = orders.filter((o) => ATTACK.includes(o.action));
      askCoach(matchId, { ...setup(), orders: forSide === 'defend' ? attack : [], side: forSide, goal })
        .then(({ plan }) => {
          if (!plan) {
            setCoach({ state: 'none' });
            return;
          }
          setCoach({ state: 'idle', plan });
          edit();
          setOrders((all) => [...all.filter((o) => (forSide === 'attack' ? !ATTACK.includes(o.action) : ATTACK.includes(o.action))), ...plan.orders]);
        })
        .catch((e: unknown) => setCoach({ state: 'none', error: e instanceof ApiError && e.status === 503 ? 'The Coach needs a model, and this API has none configured.' : undefined }));
    },
    [board, side, orders, matchId, setup, edit],
  );

  const watch = useCallback((out: PlayOut, k: number) => {
    window.clearTimeout(timer.current);
    setRun(k);
    setDecided(false);
    const startedAt = performance.now() + 250;
    setPlayback({ run: out.runs[k], ids: out.ids, stepMs: out.step_ms, startedAt });
    timer.current = window.setTimeout(() => setDecided(true), 250 + decidedAt(out, k));
  }, []);

  const play = useCallback(() => {
    if (!board || running) return;
    setRunning(true);
    setFailed(null);
    setSelected(null);
    const withDefence = orders.some((o) => !ATTACK.includes(o.action));
    playOut(matchId, setup())
      .then((out) => {
        setResult({ out, side, withDefence });
        if (!withDefence) setBaseline(out);
        setScore((s) => ({ ...s, [side]: s[side] + pointsFor(out, side), plays: s.plays + 1 }));
        watch(out, showcaseRun(out));
      })
      .catch((e: unknown) => setFailed(e instanceof ApiError && e.status === 422 ? `These orders can’t be played: ${e.message}` : 'The engine couldn’t play this out just now.'))
      .finally(() => setRunning(false));
  }, [board, running, orders, matchId, setup, side, watch]);

  /** The follow-up: defend the attack just played, with the Coach's defence to start from. */
  const defendIt = useCallback(() => {
    edit();
    setSide('defend');
    ask('Stop this attack: keep them from getting a shot away.', 'defend');
  }, [edit, ask]);

  useEffect(() => () => window.clearTimeout(timer.current), []);

  return {
    active: !!board || loading,
    loading,
    failed,
    board,
    positions,
    ballOwner,
    orders,
    side,
    setSide: (s: Side) => {
      setSide(s);
      setSelected(null);
    },
    selected,
    setSelected,
    attacking,
    isAttacker,
    commandable,
    goalX,
    offsideX,
    coach,
    result,
    baseline,
    running,
    run,
    playback,
    decided,
    score,
    start,
    exit,
    edit,
    move,
    tap,
    giveBall,
    removeOrder,
    timeOrder,
    clearSide,
    ask,
    play,
    watch,
    defendIt,
  };
}

export type PlayItOut = ReturnType<typeof usePlayItOut>;
