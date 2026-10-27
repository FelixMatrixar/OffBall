import { useEffect, useState } from 'react';
import { ApiError } from '../../lib/api';
import { fill, fmtNum } from '../../lib/i18n';
import type { Overlay } from '../../lib/feed/types';
import { explainMoment, fetchWhatIf, fetchWhatIfWords, type Alternative, type GraphicsStatus, type Moment, type WhatIf, type WhatIfWords } from '../../lib/player/api';
import { clockOf } from '../../lib/player/clock';
import type { PlayerWords } from '../../lib/player/words';
import type { Lang, Mode } from '../../lib/prefs';
import { Button, Chip, Spinner } from '../ui';

interface MomentPanelProps {
  matchId: string;
  moment: Moment;
  alternatives: readonly Alternative[];
  label: (id: string) => string;
  /** The club's name for a player. */
  clubOf: (id: string) => string;
  w: PlayerWords;
  lang: Lang;
  mode: Mode;
  /** The what-if on the pitch, if it's this moment's. */
  shown: WhatIf | null;
  onJump: () => void;
  onExplained: (status: GraphicsStatus, overlays: Overlay[], note: string) => void;
  onShow: (w: WhatIf | null) => void;
}

type Explain = { state: 'idle' } | { state: 'running' } | { state: 'error'; message: string };
type Words = { state: 'idle' | 'loading' | 'none' } | { state: 'ok'; words: WhatIfWords };

/** The moment chosen: who made it, what the crew made of it, and what would have happened otherwise (PRD 10.10). */
export function MomentPanel({ matchId, moment: m, alternatives, label, clubOf, w, lang, mode, shown, onJump, onExplained, onShow }: MomentPanelProps) {
  const [explain, setExplain] = useState<Explain>({ state: 'idle' });
  const [option, setOption] = useState<Alternative | null>(null);
  const [result, setResult] = useState<WhatIf | null>(null);
  const [failed, setFailed] = useState(false);
  const [words, setWords] = useState<Words>({ state: 'idle' });
  const explained = m.graphics === 'published' || m.graphics === 'corrected';
  const ordered = m.whatif ? [m.whatif, ...alternatives.filter((a) => a !== m.whatif)] : [];
  const wordLang: 'en' | 'es' | 'fr' = lang === 'es' || lang === 'fr' ? lang : 'en';

  const ask = () => {
    setExplain({ state: 'running' });
    explainMoment(matchId, m.candidate_id)
      .then((r) => {
        onExplained(r.status, r.overlays, r.note);
        setExplain({ state: 'idle' });
      })
      .catch((e: unknown) => setExplain({ state: 'error', message: e instanceof ApiError && e.status === 503 ? w.noModel : w.explainFailed }));
  };

  useEffect(() => {
    if (!option) return;
    const ctl = new AbortController();
    setResult(null);
    setFailed(false);
    setWords({ state: 'idle' });
    let got = false;
    fetchWhatIf(matchId, m.candidate_id, option, ctl.signal)
      .then((r) => {
        got = true;
        setResult(r);
        onShow(r);
        setWords({ state: 'loading' });
        return fetchWhatIfWords(matchId, m.candidate_id, option, ctl.signal).then((x) => setWords(x.words ? { state: 'ok', words: x.words } : { state: 'none' }));
      })
      .catch(() => {
        if (ctl.signal.aborted) return;
        // The numbers came back but the words didn't: the numbers stand alone.
        if (got) setWords({ state: 'none' });
        else setFailed(true);
      });
    return () => ctl.abort();
    // A new option starts its own replays; the callbacks are stable enough for this.
  }, [option, matchId, m.candidate_id]); // eslint-disable-line react-hooks/exhaustive-deps

  const n = result?.numbers ?? {};
  const shifts = Object.entries(n).filter(([k]) => k === 'creator_shift_m' || k.startsWith('defender_shift_m.'));
  const pid = (k: string) => (k === 'creator_shift_m' ? m.creator_id : k.slice('defender_shift_m.'.length));

  return (
    <section className="card moment-panel anim-rise" aria-label={w.types[m.type] ?? m.type}>
      <header className="stack" style={{ gap: 6 }}>
        <div className="cluster" style={{ justifyContent: 'space-between' }}>
          <h2 className="card-title" style={{ margin: 0, fontSize: 22 }}>
            {w.types[m.type] ?? m.type}
          </h2>
          <Button variant="ghost" className="btn-sm btn-wrap" onClick={onJump}>
            {fill(w.jumpTo, { clock: clockOf({ period: m.period, t_ms: m.t_start_ms }) })}
          </Button>
        </div>
        <p className="muted" style={{ margin: 0, fontSize: 14, lineHeight: 1.5 }}>
          {w.creator} {label(m.creator_id)}
          {m.dragged_ids.length > 0 && <> · {w.pulled} {m.dragged_ids.map(label).join(', ')}</>}
          {m.receiver_id && <> · {w.receiver} {label(m.receiver_id)}</>}
        </p>
      </header>

      <div className="moment-block">
        <div className="cluster" style={{ gap: 8 }}>
          <span className={`moment-dot${explained ? ' moment-dot-on' : ''}`} aria-hidden="true" />
          <span style={{ fontSize: 14 }}>{w.graphics[m.graphics]}</span>
        </div>
        {/* The Scout's one-sentence reason is for viewers; a failed step's error is for the team. */}
        {m.graphics_note && m.graphics === 'skipped' && (
          <p className="muted" lang="en" style={{ margin: 0, fontSize: 13, lineHeight: 1.45 }}>
            {m.graphics_note}
          </p>
        )}
        {!explained && explain.state !== 'running' && (
          <Button variant="secondary" className="btn-sm btn-wrap" onClick={ask}>
            {w.explain}
          </Button>
        )}
        {explain.state === 'running' && (
          <p className="cluster muted" role="status" style={{ margin: 0, fontSize: 14, gap: 8 }}>
            <Spinner /> {w.explaining}
          </p>
        )}
        {explain.state === 'error' && (
          <p role="alert" className="muted" style={{ margin: 0, fontSize: 14 }}>
            {explain.message}
          </p>
        )}
      </div>

      {m.whatif && (
        <div className="moment-block">
          <h3 className="card-h3" style={{ margin: 0 }}>
            {fill(w.whatIfQuestion, { player: label(m.creator_id) })}
          </h3>
          <div className="cluster" role="group" aria-label={w.whatIf} style={{ gap: 8 }}>
            {ordered.map((a) => (
              <Button key={a} variant={option === a ? 'primary' : 'secondary'} className="btn-sm btn-wrap" aria-pressed={option === a} onClick={() => setOption(a)}>
                {w.alternative[a]}
                {a === m.whatif && <span className="muted whatif-usual"> · {w.usual}</span>}
              </Button>
            ))}
          </div>
          {option && !result && !failed && (
            <p className="cluster muted" role="status" style={{ margin: 0, fontSize: 14, gap: 8 }}>
              <Spinner /> {w.replaying}
            </p>
          )}
          {failed && (
            <p role="alert" className="muted" style={{ margin: 0, fontSize: 14 }}>
              {w.whatIfFailed}
            </p>
          )}
          {result && (
            <div className="stack anim-rise" style={{ gap: 10 }}>
              <div className="whatif-numbers">
                <div>
                  <span className="card-label">{w.spaceCreated}</span>
                  <span className="display tabular whatif-big">
                    {fmtNum(lang, n.space_created_m2 ?? 0, 1)} m²
                  </span>
                  <span className="muted" style={{ fontSize: 13 }}>
                    {fill(w.interval, { lo: fmtNum(lang, n.space_lo_m2 ?? 0, 1), hi: fmtNum(lang, n.space_hi_m2 ?? 0, 1) })}
                  </span>
                </div>
                <ul className="whatif-list">
                  <li>{fill(w.gapOpened, { pct: fmtNum(lang, n.gap_open_pct_without ?? 0) })}</li>
                  {shifts.map(([k, v]) => (
                    <li key={k}>{fill(w.shift, { player: label(pid(k)), m: fmtNum(lang, v, 1) })}</li>
                  ))}
                </ul>
              </div>
              {words.state === 'loading' && (
                <p className="cluster muted" role="status" style={{ margin: 0, fontSize: 14, gap: 8 }}>
                  <Spinner /> {w.writing}
                </p>
              )}
              {words.state === 'ok' && (
                <div className="whatif-words" lang={wordLang}>
                  <p className="display" style={{ margin: 0, fontSize: 20 }}>
                    {words.words.headline[wordLang]}
                  </p>
                  <p style={{ margin: 0, lineHeight: 1.5 }}>{(mode === 'analyst' || mode === 'broadcaster' ? words.words.analyst : words.words.plain)[wordLang]}</p>
                  <Chip tone="muted">{w.aiGenerated}</Chip>
                </div>
              )}
              {words.state === 'none' && (
                <p className="muted" style={{ margin: 0, fontSize: 13 }}>
                  {w.noWords}
                </p>
              )}
              <div className="cluster" style={{ gap: 8 }}>
                {shown?.counterfactual_id === result.counterfactual_id ? (
                  <>
                    <Button variant="primary" className="btn-sm btn-wrap" onClick={onJump}>
                      {w.showGhosts}
                    </Button>
                    <Button variant="ghost" className="btn-sm btn-wrap" onClick={() => onShow(null)}>
                      {w.hideGhosts}
                    </Button>
                  </>
                ) : (
                  <Button
                    variant="primary"
                    className="btn-sm btn-wrap"
                    onClick={() => {
                      onShow(result);
                      onJump();
                    }}
                  >
                    {w.showGhosts}
                  </Button>
                )}
              </div>
              <p className="muted" style={{ margin: 0, fontSize: 12 }}>
                {w.ghostNote} {clubOf(m.creator_id)} · {result.counterfactual_id}
              </p>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
