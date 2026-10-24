import { useEffect, useId, useRef, useState, type FormEvent } from 'react';
import { useFeedStore } from '../../lib/feed';
import { LANGS, useI18n } from '../../lib/i18n';
import { answer, suggestions, type Answer } from '../../lib/pundit';
import { usePrefs } from '../../lib/prefs';
import { ChartFrame, VegaChart } from '../charts';
import { CheckIcon, Chip, Dialog, TypingDots } from '../ui';

interface SpeechRecognitionLike {
  lang: string;
  interimResults: boolean;
  onresult: ((e: { results: ArrayLike<ArrayLike<{ transcript: string }>> }) => void) | null;
  onend: (() => void) | null;
  onerror: (() => void) | null;
  start: () => void;
  stop: () => void;
}

const Recognition = (): (new () => SpeechRecognitionLike) | null => {
  const w = window as unknown as { SpeechRecognition?: new () => SpeechRecognitionLike; webkitSpeechRecognition?: new () => SpeechRecognitionLike };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
};

const CONSENT_KEY = 'offball.voiceInputOk';

function AnswerView({ a, onAsk }: { a: Answer; onAsk: (q: string) => void }) {
  const verified = a.claims.filter((c) => c.verified);
  const unverified = a.claims.filter((c) => !c.verified);
  const evidence = [...new Set(verified.flatMap((c) => c.evidence))];
  return (
    <div className="ask-answer anim-rise">
      {a.state === 'declined' || a.state === 'unknown' ? (
        <p style={{ fontSize: 14, lineHeight: 1.5 }}>{unverified[0]?.text}</p>
      ) : (
        verified.map((c) => (
          <p key={c.text} style={{ fontSize: 14, lineHeight: 1.5 }}>
            {c.text}
          </p>
        ))
      )}
      {a.state === 'partial' &&
        unverified.map((c) => (
          <p key={c.text} className="ask-unverified">
            {c.text}
          </p>
        ))}
      {a.chart && (
        <ChartFrame title={a.chart.title} summary={a.chart.summary} columns={a.chart.columns} rows={a.chart.rows} name="answer">
          <VegaChart spec={a.chart.spec} label={a.chart.summary} height={Math.max(90, a.chart.rows.length * 34)} />
        </ChartFrame>
      )}
      <div className="cluster" style={{ gap: 6 }}>
        {(a.state === 'ok' || a.state === 'partial') && (
          <Chip tone="space">
            <CheckIcon size={10} /> Fact-checked
          </Chip>
        )}
        {a.state === 'partial' && <Chip tone="muted">{unverified.length} claim unverified</Chip>}
        {a.corrected && <Chip tone="danger">Uses the corrected pass data</Chip>}
        {evidence.slice(0, 3).map((e) => (
          <Chip key={e} tone="muted" className="mono" style={{ fontWeight: 400 }}>
            {e}
          </Chip>
        ))}
      </div>
      {a.alternative && (
        <button type="button" className="pill press" onClick={() => onAsk(a.alternative!.question)}>
          {a.alternative.label}
        </button>
      )}
    </div>
  );
}

/**
 * Ask OffBall (PRD 10.4): questions by text or voice, answered with cited claims and, often, a chart rendered in the
 * viewer's theme. Answers come from the match data on the device until the Pundit agent is connected.
 */
export function AskPanel({ t }: { t: number }) {
  const { prefs } = usePrefs();
  const { lang } = useI18n();
  const store = useFeedStore();
  const [log, setLog] = useState<Answer[]>([]);
  const [pending, setPending] = useState<{ q: string; tools: string[] } | null>(null);
  const [input, setInput] = useState('');
  const [listening, setListening] = useState(false);
  const [consentOpen, setConsentOpen] = useState(false);
  const recog = useRef<SpeechRecognitionLike | null>(null);
  const timer = useRef<number>();
  const endRef = useRef<HTMLDivElement>(null);
  const inputId = useId();
  const passCorrected = [...store.overlays.values()].some((o) => o.labels.includes('correction'));
  const canListen = !!Recognition();

  useEffect(() => () => window.clearTimeout(timer.current), []);
  useEffect(() => {
    // Block body: scrollIntoView can return a promise, which must not become the effect's clean-up.
    endRef.current?.scrollIntoView({ block: 'nearest' });
  }, [log, pending]);

  const ask = (q: string) => {
    const question = q.trim();
    if (!question || pending) return;
    const a = answer(question, { t, fav: prefs.fav, passCorrected });
    setPending({ q: question, tools: a.tools });
    setInput('');
    // The Pundit's tool calls take a moment; the typing indicator names them as they run.
    timer.current = window.setTimeout(() => {
      setLog((l) => [...l.slice(-5), a]);
      setPending(null);
    }, 700 + a.tools.length * 350);
  };

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    ask(input);
  };

  const listen = () => {
    if (listening) {
      recog.current?.stop();
      return;
    }
    let consented = false;
    try {
      consented = localStorage.getItem(CONSENT_KEY) === 'yes';
    } catch {
      consented = false;
    }
    if (!consented) {
      setConsentOpen(true);
      return;
    }
    const R = Recognition();
    if (!R) return;
    const r = new R();
    r.lang = LANGS.find((l) => l.code === lang)?.code ?? 'en';
    r.interimResults = false;
    r.onresult = (e) => {
      const said = e.results[0]?.[0]?.transcript ?? '';
      setInput(said);
      ask(said);
    };
    r.onend = r.onerror = () => setListening(false);
    recog.current = r;
    setListening(true);
    r.start();
  };

  const confirmVoice = () => {
    try {
      localStorage.setItem(CONSENT_KEY, 'yes');
    } catch {
      // Ask again next time.
    }
    setConsentOpen(false);
    window.setTimeout(listen, 0);
  };

  const chips = suggestions(t);
  return (
    <section aria-label="Ask OffBall" className="ask">
      <div className="ask-log" aria-live="polite">
        {log.length === 0 && !pending && (
          <div className="ask-empty">
            <p className="display" style={{ fontSize: 22 }}>
              Ask about this match
            </p>
            <p className="muted" style={{ fontSize: 13 }}>
              Questions drawn from what just happened:
            </p>
          </div>
        )}
        {log.map((a, i) => (
          <div key={i} className="stack" style={{ gap: 8 }}>
            <p className="ask-question">{a.question}</p>
            <AnswerView a={a} onAsk={ask} />
          </div>
        ))}
        {pending && (
          <div className="stack" style={{ gap: 8 }}>
            <p className="ask-question">{pending.q}</p>
            <TypingDots label="OffBall is checking the data" />
            <span className="mono muted anim-fade" style={{ fontSize: 12 }}>
              {pending.tools.join(' · ') || 'reading the question'}
            </span>
          </div>
        )}
        <div ref={endRef} />
      </div>
      <div className="ask-chips">
        {chips.map((c) => (
          <button key={c} type="button" className="pill press" onClick={() => ask(c)} disabled={!!pending}>
            {c}
          </button>
        ))}
      </div>
      {lang !== 'en' && <p className="muted" style={{ fontSize: 12 }}>Answers are in English until the Pundit agent answers in your language.</p>}
      <form className="ask-form" onSubmit={onSubmit}>
        <label htmlFor={inputId} className="sr-only">
          Ask about this match
        </label>
        <input id={inputId} className="input" type="text" placeholder="Ask about this match" value={input} onChange={(e) => setInput(e.target.value)} autoComplete="off" enterKeyHint="send" style={{ flex: 1 }} />
        <button type="submit" className="btn btn-primary press" disabled={!input.trim() || !!pending}>
          Ask
        </button>
        {canListen && (
          <button type="button" aria-label={listening ? 'Stop listening' : 'Ask by voice'} aria-pressed={listening} onClick={listen} className="btn btn-ghost btn-icon btn-round press" style={{ position: 'relative' }}>
            {listening && <span className="anim-ripple" style={{ position: 'absolute', inset: 0, borderRadius: 22, border: '2px solid var(--space)' }} />}
            <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true">
              <rect x="6" y="2" width="6" height="10" rx="3" style={{ fill: 'none', stroke: 'currentColor', strokeWidth: 1.8 }} />
              <path d="M3.5 9 Q3.5 14 9 14 Q14.5 14 14.5 9 M9 14 V16.5" style={{ fill: 'none', stroke: 'currentColor', strokeWidth: 1.8, strokeLinecap: 'round' }} />
            </svg>
          </button>
        )}
      </form>
      {listening && (
        <p className="anim-fade" role="status" style={{ fontSize: 13, color: 'var(--space-ink)' }}>
          Listening…
        </p>
      )}
      <Dialog open={consentOpen} onClose={() => setConsentOpen(false)} title="Ask by voice">
        <p style={{ fontSize: 15, lineHeight: 1.5 }}>
          Voice questions use your browser’s speech recognition, which may send the audio to the browser’s speech provider. OffBall doesn’t store it. You can always type instead.
        </p>
        <div className="cluster">
          <button type="button" className="btn btn-primary press" onClick={confirmVoice}>
            Use voice
          </button>
          <button type="button" className="btn btn-ghost press" onClick={() => setConsentOpen(false)}>
            Type instead
          </button>
        </div>
      </Dialog>
    </section>
  );
}
