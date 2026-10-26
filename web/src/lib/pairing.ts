// Second-screen pairing (PRD 15.5): a 6-character code or QR code, valid for 2 hours, that identifies nobody.
// Pairing runs between tabs on one device over BroadcastChannel; across devices it needs the relay's pairing group.
import { useEffect, useRef, useState } from 'react';
import type { Lang, Mode } from './prefs';

const ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789';
export const CODE_TTL_MS = 2 * 60 * 60 * 1000;
const HOST_KEY = 'offball.pairHost';

export function newCode(): string {
  const bytes = new Uint8Array(6);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (b) => ALPHABET[b % ALPHABET.length]).join('');
}

export const normaliseCode = (raw: string) =>
  raw
    .toUpperCase()
    .replace(/[^A-Z0-9]/g, '')
    .replace(/O/g, '0')
    .replace(/I/g, '1')
    .slice(0, 6);

export const isValidCode = (code: string) => code.length === 6 && [...code].every((c) => ALPHABET.includes(c));

export const pairUrl = (code: string) => `${window.location.origin}${window.location.pathname}#/phone?pair=${code}`;

export interface SharedState {
  t: number;
  playing: boolean;
  mode: Mode;
  lang: Lang;
  fav: string;
  /** Host wall-clock when sent, to estimate lag. */
  at: number;
}

type Message = { type: 'hello'; guest: string } | { type: 'state'; state: SharedState; expiresAt: number } | { type: 'bye'; guest: string };

/** The host's code for this tab session, renewed when it expires. */
export function useHostCode(): { code: string; expiresAt: number; renew: () => void } {
  const [session, setSession] = useState(() => {
    try {
      const saved = JSON.parse(sessionStorage.getItem(HOST_KEY) ?? 'null') as { code: string; expiresAt: number } | null;
      if (saved && saved.expiresAt > Date.now()) return saved;
    } catch {
      // Make a new one.
    }
    return { code: newCode(), expiresAt: Date.now() + CODE_TTL_MS };
  });
  useEffect(() => {
    try {
      sessionStorage.setItem(HOST_KEY, JSON.stringify(session));
    } catch {
      // The code lasts for this page only.
    }
  }, [session]);
  return { ...session, renew: () => setSession({ code: newCode(), expiresAt: Date.now() + CODE_TTL_MS }) };
}

/** The main screen: answers guests and keeps sending its clock and settings while anyone is paired. */
export function usePairHost(code: string, expiresAt: number, state: Omit<SharedState, 'at'>): number {
  const [guests, setGuests] = useState<Set<string>>(new Set());
  const latest = useRef(state);
  latest.current = state;
  const channel = useRef<BroadcastChannel | null>(null);

  useEffect(() => {
    let ch: BroadcastChannel;
    try {
      ch = new BroadcastChannel(`offball-pair-${code}`);
    } catch {
      return;
    }
    channel.current = ch;
    const send = () => ch.postMessage({ type: 'state', state: { ...latest.current, at: Date.now() }, expiresAt } satisfies Message);
    ch.onmessage = (e: MessageEvent<Message>) => {
      if (Date.now() > expiresAt) return;
      if (e.data.type === 'hello') {
        const id = e.data.guest;
        setGuests((g) => new Set(g).add(id));
        send();
      }
      if (e.data.type === 'bye') {
        const id = e.data.guest;
        setGuests((g) => {
          const next = new Set(g);
          next.delete(id);
          return next;
        });
      }
    };
    const timer = window.setInterval(send, 250);
    return () => {
      window.clearInterval(timer);
      ch.close();
      channel.current = null;
    };
  }, [code, expiresAt]);

  return guests.size;
}

export type GuestStatus = 'idle' | 'joining' | 'paired' | 'not-found' | 'expired';

/** The phone: joins with a code and follows the main screen's clock. */
export function usePairGuest(code: string | null): { status: GuestStatus; state: SharedState | null; leave: () => void } {
  const [status, setStatus] = useState<GuestStatus>(code ? 'joining' : 'idle');
  const [state, setState] = useState<SharedState | null>(null);
  const guest = useRef(newCode());
  const channel = useRef<BroadcastChannel | null>(null);

  useEffect(() => {
    if (!code) {
      setStatus('idle');
      return;
    }
    let ch: BroadcastChannel;
    try {
      ch = new BroadcastChannel(`offball-pair-${code}`);
    } catch {
      setStatus('not-found');
      return;
    }
    channel.current = ch;
    setStatus('joining');
    let heard = false;
    ch.onmessage = (e: MessageEvent<Message>) => {
      if (e.data.type !== 'state') return;
      heard = true;
      if (Date.now() > e.data.expiresAt) {
        setStatus('expired');
        return;
      }
      setStatus('paired');
      setState(e.data.state);
    };
    const hello = () => ch.postMessage({ type: 'hello', guest: guest.current } satisfies Message);
    hello();
    const timer = window.setInterval(hello, 1000);
    const giveUp = window.setTimeout(() => {
      if (!heard) setStatus('not-found');
    }, 4000);
    return () => {
      window.clearInterval(timer);
      window.clearTimeout(giveUp);
      ch.postMessage({ type: 'bye', guest: guest.current } satisfies Message);
      ch.close();
      channel.current = null;
    };
  }, [code]);

  return {
    status,
    state,
    leave: () => {
      channel.current?.postMessage({ type: 'bye', guest: guest.current } satisfies Message);
      setStatus('idle');
      setState(null);
    },
  };
}
