// Voice and audio cues. Voice uses the device's speech engine, standing in for Azure AI Speech until the backend
// exists: no voice imitates a real person. Lines never overlap and are dropped rather than spoken more than 4 s
// behind the play (PRD 10.5). Cues are stereo-panned to where space is opening (PRD 10.5, 16.6).
import { useEffect, useState } from 'react';

let ctx: AudioContext | null = null;

/** Browsers start audio only after a user gesture; call this from any click or key press. */
export function unlockAudio(): void {
  try {
    ctx ??= new AudioContext();
    void ctx.resume();
  } catch {
    ctx = null;
  }
}

/** A soft tone panned from -1 (left touchline end) to 1 (right). */
export function cue(pan: number, { freq = 660, gain = 0.07, dur = 0.5 }: { freq?: number; gain?: number; dur?: number } = {}): void {
  if (!ctx || ctx.state !== 'running') return;
  const t = ctx.currentTime;
  const osc = ctx.createOscillator();
  const amp = ctx.createGain();
  const panner = ctx.createStereoPanner();
  osc.type = 'sine';
  osc.frequency.setValueAtTime(freq, t);
  osc.frequency.exponentialRampToValueAtTime(freq * 1.5, t + dur * 0.6);
  amp.gain.setValueAtTime(0.0001, t);
  amp.gain.exponentialRampToValueAtTime(gain, t + 0.03);
  amp.gain.exponentialRampToValueAtTime(0.0001, t + dur);
  panner.pan.setValueAtTime(Math.max(-1, Math.min(1, pan)), t);
  osc.connect(amp).connect(panner).connect(ctx.destination);
  osc.start(t);
  osc.stop(t + dur + 0.05);
}

const synth = () => (typeof window !== 'undefined' && 'speechSynthesis' in window ? window.speechSynthesis : null);

function voices(): SpeechSynthesisVoice[] {
  return synth()?.getVoices() ?? [];
}

/** The device voice for a language, preferring natural-sounding ones. */
export function voiceFor(lang: string): SpeechSynthesisVoice | null {
  const all = voices().filter((v) => v.lang.toLowerCase().startsWith(lang.toLowerCase()));
  return all.find((v) => /natural|neural|online/i.test(v.name)) ?? all[0] ?? null;
}

/** Voices load asynchronously in some browsers; this re-renders once they arrive. */
export function useVoices(): number {
  const [n, setN] = useState(() => voices().length);
  useEffect(() => {
    const s = synth();
    if (!s) return;
    const onChange = () => setN(s.getVoices().length);
    s.addEventListener('voiceschanged', onChange);
    onChange();
    return () => s.removeEventListener('voiceschanged', onChange);
  }, []);
  return n;
}

export interface Line {
  id: string;
  text: string;
  lang: string;
  /** Moment time the line describes, in seconds. */
  t: number;
}

const MAX_LAG_S = 4;

class Speaker {
  private queue: Line[] = [];
  private current: Line | null = null;
  private nowT: () => number = () => 0;
  private rate = 1;
  /** Lines dropped because they would have lagged the play by more than 4 s. */
  dropped = 0;

  say(line: Line, nowT: () => number, rate = 1): void {
    const s = synth();
    if (!s || !voiceFor(line.lang)) return;
    this.nowT = nowT;
    this.rate = rate;
    if (this.current?.id === line.id || this.queue.some((q) => q.id === line.id)) return;
    // Only the newest pending line matters: older ones would talk over the play.
    this.queue = [line];
    if (!this.current) this.next();
  }

  private next(): void {
    const s = synth();
    const line = this.queue.shift();
    if (!s || !line) {
      this.current = null;
      return;
    }
    if (this.nowT() - line.t > MAX_LAG_S) {
      this.dropped++;
      this.next();
      return;
    }
    const u = new SpeechSynthesisUtterance(line.text);
    u.lang = line.lang;
    u.voice = voiceFor(line.lang);
    u.rate = this.rate;
    u.onend = u.onerror = () => {
      this.current = null;
      this.next();
    };
    this.current = line;
    s.speak(u);
  }

  cancel(): void {
    this.queue = [];
    this.current = null;
    synth()?.cancel();
  }
}

export const speaker = new Speaker();
export const canSpeak = () => !!synth();
