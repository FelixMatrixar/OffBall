import { useRef, useState, type KeyboardEvent } from 'react';
import type { Pattern } from '../../lib/kits';
import type { Team, XY } from '../../lib/match';
import { PlayerDot } from './overlays';

export interface PlayerView {
  id: string;
  at: XY;
  team: Team;
  num: number;
  /** Accessible name. Kept steady (no live numbers), so it never changes under a screen reader. */
  label: string;
  /** Shown on hover and focus: the name and a live number. */
  hint: string;
  dim?: boolean;
  focus?: boolean;
  pattern?: Pattern;
}

/**
 * Every player as one tab stop (roving focus): arrow keys move between players, Home and End jump to the ends,
 * Enter follows the focused player. Focus or hover shows that player's name and speed (PRD 15.4, 16.6). Only that
 * one hint is in the DOM, so the other players' live numbers cost nothing per frame.
 */
export function PlayerLayer({ players, onFollow, label }: { players: readonly PlayerView[]; onFollow?: (id: string) => void; label: string }) {
  const [active, setActive] = useState(0);
  const [focused, setFocused] = useState<string | null>(null);
  const [hovered, setHovered] = useState<string | null>(null);
  const refs = useRef<(SVGGElement | null)[]>([]);

  const move = (to: number) => {
    const n = players.length;
    const i = ((to % n) + n) % n;
    setActive(i);
    refs.current[i]?.focus();
  };

  const onKeyDown = (i: number) => (e: KeyboardEvent<SVGGElement>) => {
    const half = players.length / 2;
    const handled = ['ArrowRight', 'ArrowLeft', 'ArrowUp', 'ArrowDown', 'Home', 'End', 'Enter', ' '];
    if (!handled.includes(e.key)) return;
    e.preventDefault();
    e.stopPropagation();
    if (e.key === 'ArrowRight') move(i + 1);
    if (e.key === 'ArrowLeft') move(i - 1);
    // Up and down switch teams, keeping the shirt number.
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') move(i < half ? i + half : i - half);
    if (e.key === 'Home') move(0);
    if (e.key === 'End') move(players.length - 1);
    if (e.key === 'Enter' || e.key === ' ') onFollow?.(players[i].id);
  };

  return (
    <g role="group" aria-label={label} onPointerLeave={() => setHovered(null)}>
      {players.map((p, i) => (
        <PlayerDot
          key={p.id}
          at={p.at}
          team={p.team}
          num={p.num}
          label={p.label}
          hint={focused === p.id || hovered === p.id ? p.hint : undefined}
          dim={p.dim}
          focus={p.focus}
          pattern={p.pattern}
          tabIndex={i === active ? 0 : -1}
          playerRef={(el) => {
            refs.current[i] = el;
          }}
          onFocus={() => {
            setActive(i);
            setFocused(p.id);
          }}
          onBlur={() => setFocused((f) => (f === p.id ? null : f))}
          onPointerEnter={() => setHovered(p.id)}
          onKeyDown={onKeyDown(i)}
        />
      ))}
    </g>
  );
}
