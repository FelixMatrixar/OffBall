import { useEffect, useState } from 'react';
import { LinkButton, Logo, Spinner } from '../components/ui';
import { apiBase } from '../lib/api';
import { fill, isRtl, useI18n } from '../lib/i18n';
import { fetchMatches, playerHref, type MatchSummary } from '../lib/player/api';
import { playerWords } from '../lib/player/words';

/** A match counts as whole when it runs past an hour. */
const WHOLE_MS = 60 * 60_000;

type Load = { state: 'loading' } | { state: 'error' } | { state: 'ok'; matches: MatchSummary[] };

function MatchCard({ m, order }: { m: MatchSummary; order: number }) {
  const { lang } = useI18n();
  const w = playerWords(lang);
  return (
    <a href={playerHref('play', { m: m.match_id })} className="screen-card match-card anim-rise" style={{ animationDelay: `calc(var(--stagger) * ${order})` }}>
      <span className="display" style={{ fontSize: 24 }}>
        {m.home} <span className="muted">v</span> {m.away}
      </span>
      <span className="cluster muted" style={{ fontSize: 13, gap: 12 }}>
        {m.round !== null && <span>{fill(w.round, { n: m.round })}</span>}
        <span>{fill(w.minutes, { n: Math.round(m.duration_ms / 60_000) })}</span>
        <span className="mono">{m.match_id}</span>
      </span>
    </a>
  );
}

/** Every match the API can play from tracking: whole matches first, then the short ones (PRD 15.10). */
export function MatchPicker() {
  const { lang } = useI18n();
  const w = playerWords(lang);
  const [load, setLoad] = useState<Load>({ state: 'loading' });
  const [attempt, setAttempt] = useState(0);
  const backend = !!apiBase();

  useEffect(() => {
    if (!backend) return;
    const ctl = new AbortController();
    setLoad({ state: 'loading' });
    fetchMatches(ctl.signal)
      .then((matches) => setLoad({ state: 'ok', matches: matches.filter((m) => m.tracking).sort((a, b) => b.duration_ms - a.duration_ms || a.match_id.localeCompare(b.match_id)) }))
      .catch(() => !ctl.signal.aborted && setLoad({ state: 'error' }));
    return () => ctl.abort();
  }, [backend, attempt]);

  const whole = load.state === 'ok' ? load.matches.filter((m) => m.duration_ms >= WHOLE_MS) : [];
  const short = load.state === 'ok' ? load.matches.filter((m) => m.duration_ms < WHOLE_MS) : [];

  return (
    <div className="screen" lang={lang} dir={isRtl(lang) ? 'rtl' : 'ltr'}>
      <div className="container stack-lg">
        <header className="cluster anim-rise">
          <Logo />
        </header>
        <div className="anim-rise">
          <h1 className="display" style={{ fontSize: 'clamp(40px, 7vw, 58px)', lineHeight: 0.95 }}>
            {w.title}
          </h1>
          <p className="muted" style={{ fontSize: 17, marginTop: 12, maxWidth: 760, lineHeight: 1.5 }}>
            {w.intro}
          </p>
        </div>
        {!backend && <p className="card">{w.noBackend}</p>}
        {backend && load.state === 'loading' && (
          <p className="cluster muted" role="status">
            <Spinner /> {w.loadingMatches}
          </p>
        )}
        {load.state === 'error' && (
          <div className="card cluster" role="alert">
            <span>{w.matchesFailed}</span>
            <LinkButton variant="secondary" className="btn-sm" href={playerHref('matches')} onClick={() => setAttempt((n) => n + 1)}>
              {w.retry}
            </LinkButton>
          </div>
        )}
        {load.state === 'ok' && !load.matches.length && <p className="card">{w.noMatches}</p>}
        {whole.length > 0 && (
          <section className="stack" aria-label={w.fullMatches}>
            <h2 className="card-h3">{w.fullMatches}</h2>
            <nav className="match-grid">
              {whole.map((m, i) => (
                <MatchCard key={m.match_id} m={m} order={i + 2} />
              ))}
            </nav>
          </section>
        )}
        {short.length > 0 && (
          <section className="stack" aria-label={w.shortMatches}>
            <h2 className="card-h3">{w.shortMatches}</h2>
            <nav className="match-grid">
              {short.map((m, i) => (
                <MatchCard key={m.match_id} m={m} order={i + 2 + whole.length} />
              ))}
            </nav>
          </section>
        )}
      </div>
    </div>
  );
}
