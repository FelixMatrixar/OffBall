import { useEffect, useState } from 'react';
import { ChartFrame, HeatMap, Leaderboard, ShotMap, heatTable, shotTable } from '../components/charts';
import { MomentDiagram } from '../components/recap';
import { Button, Card, Chip, LinkButton, Logo, Segmented, Switch } from '../components/ui';
import { cardBlob, cardText, drawPlayerCard, fontsSettled, shareFile } from '../lib/cards';
import { download, EXPORT_LABEL, toCsv } from '../lib/export';
import { useHashQuery } from '../lib/hooks';
import { useI18n } from '../lib/i18n';
import { CLUBS, PLAYERS, player, playerLabel } from '../lib/match';
import { usePrefs } from '../lib/prefs';
import { RECAP_LEADERS, RECAP_SCORE, RECAP_UNTIL, momentById, useRecapPackage, type RecapKind, type RecapMoment } from '../lib/recap';
import { SHOTS } from '../lib/stats';

const KINDS: readonly { value: RecapKind; label: string }[] = [
  { value: 'halftime', label: 'Halftime' },
  { value: 'fulltime', label: 'Full time' },
];

const OUTCOME: Record<RecapMoment['outcome'], string> = { goal: 'Goal', saved: 'Saved', 'off target': 'Off target', blocked: 'Blocked' };

const isKind = (v: string | null): v is RecapKind => v === 'halftime' || v === 'fulltime';

/**
 * The recap package (PRD 10.8): halftime and full-time recaps of the top space moments, the Space Created leaderboard
 * and the shot map, then a shareable player card and the vertical clip, all spoiler-safe on request. The producer
 * curates and publishes it (15.6); until then the recap is the period's moments, biggest space first.
 */
export function RecapView() {
  const { prefs, update } = usePrefs();
  const { num } = useI18n();
  const asked = useHashQuery('kind');
  const [kind, setKind] = useState<RecapKind>(isKind(asked) ? asked : 'fulltime');
  useEffect(() => {
    if (isKind(asked)) setKind(asked);
  }, [asked]);
  const pkg = useRecapPackage(kind);
  const [revealed, setRevealed] = useState(false);
  const safe = (prefs.spoilerSafe || pkg.spoilerSafe) && !revealed;
  const moments = pkg.moments.map(momentById).filter((m): m is RecapMoment => !!m);
  const score = RECAP_SCORE[kind];
  const leaders = RECAP_LEADERS[kind];
  const shots = SHOTS.filter((s) => s.minute <= RECAP_UNTIL[kind]).sort((a, b) => a.minute - b.minute);
  const full = kind === 'fulltime';
  const [cardId, setCardId] = useState(prefs.fav);
  const [cardUrl, setCardUrl] = useState<string | null>(null);
  const [shared, setShared] = useState<string | null>(null);
  const clip = safe ? 'share-vertical-safe' : 'share-vertical';
  const top = leaders[0];

  useEffect(() => setRevealed(false), [kind]);
  // The card preview is the exported image itself, drawn once fonts have loaded (or soon, if they're slow), and again
  // whenever more fonts arrive.
  useEffect(() => {
    if (!full) return;
    const urls: string[] = [];
    let live = true;
    const draw = () =>
      drawPlayerCard(cardId, safe).toBlob((b) => {
        if (!b || !live) return;
        const url = URL.createObjectURL(b);
        const previous = urls.pop();
        urls.push(url);
        setCardUrl(url);
        if (previous) setTimeout(() => URL.revokeObjectURL(previous), 1000);
      }, 'image/png');
    void fontsSettled().then(() => live && draw());
    document.fonts.addEventListener('loadingdone', draw);
    return () => {
      live = false;
      document.fonts.removeEventListener('loadingdone', draw);
      // Revoked once the next preview has replaced it.
      setTimeout(() => urls.forEach((u) => URL.revokeObjectURL(u)), 1000);
    };
  }, [cardId, safe, prefs.theme, full]);

  const card = cardText(cardId, safe);
  const shareCard = async () => {
    const how = await shareFile(await cardBlob(cardId, safe), `offball-card-${cardId}.png`, `${card.name} · OffBall`, card.alt);
    setShared(how === 'shared' ? 'Card shared.' : 'Card downloaded.');
  };
  const shareClip = async () => {
    const blob = await (await fetch(`clips/${clip}.mp4`)).blob();
    const how = await shareFile(blob, `offball-${clip}.mp4`, 'OffBall · the decoy run', `${safe ? 'The run that made the space' : 'The run that made the goal'}, with the space it opened. ${EXPORT_LABEL}.`);
    setShared(how === 'shared' ? 'Clip shared.' : 'Clip downloaded.');
  };
  const exportMoments = () =>
    download(
      toCsv(
        ['Minute', 'Moment', 'Made by', 'Space created (m²)', '90% low', '90% high', 'Threat created', 'Outcome'],
        moments.map((m) => [m.minute, safe ? m.safeTitle : m.title, playerLabel(m.creator), m.space[0], m.space[1], m.space[2], m.threat, safe ? 'hidden' : OUTCOME[m.outcome]]),
      ),
      `offball-recap-${kind}.csv`,
    );
  const shotTab = shotTable(shots, safe);
  const heatTab = heatTable(cardId);
  const order = pkg.publishedAt ? 'told in the order the producer chose' : 'biggest space first';

  return (
    <div className="screen">
      <div className="container stack-lg">
        <header className="cluster anim-rise" style={{ justifyContent: 'space-between', gap: 16 }}>
          <Logo suffix="Recap" />
          <div className="cluster" style={{ gap: 12 }}>
            <Segmented
              options={KINDS}
              value={kind}
              onChange={(k) => {
                setKind(k);
                // The address follows, so a shared link opens the same recap.
                history.replaceState(null, '', `#/recap?kind=${k}`);
              }}
              label="Recap"
            />
            <Switch checked={prefs.spoilerSafe} onChange={(spoilerSafe) => update({ spoilerSafe })} label="Spoiler-safe" />
            <LinkButton href="#/match">Match view</LinkButton>
          </div>
        </header>

        <section className="card recap-hero anim-rise" aria-labelledby="recap-title">
          <p className="card-label">
            {full ? 'Full time' : 'Halftime'} · synthetic match · {pkg.publishedAt ? `curated by the producer at ${new Date(pkg.publishedAt).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}` : 'automatic recap'}
          </p>
          <h1 id="recap-title" className="display recap-score">
            {safe ? (
              <>
                {CLUBS.kes.name} v {CLUBS.ash.name}
              </>
            ) : (
              <>
                {CLUBS.kes.name} <span className="tabular">{score.kes}–{score.ash}</span> {CLUBS.ash.name}
              </>
            )}
          </h1>
          {safe ? (
            <div className="cluster" style={{ gap: 10 }}>
              <Chip tone="muted">Result hidden</Chip>
              <span className="muted" style={{ fontSize: 14 }}>
                Scores and outcomes are hidden{pkg.spoilerSafe ? ' in this recap' : ' by your settings'}.
              </span>
              <Button className="btn-sm" onClick={() => setRevealed(true)}>
                Show the result
              </Button>
            </div>
          ) : (
            <p className="muted" style={{ fontSize: 15 }}>
              {moments.length} moments where a run off the ball made space, {order}. Every number is from the synthetic match, with its interval.
            </p>
          )}
        </section>

        <section aria-labelledby="moments-title" className="stack">
          <div className="cluster" style={{ justifyContent: 'space-between' }}>
            <h2 id="moments-title" className="display" style={{ fontSize: 30 }}>
              Top space moments
            </h2>
            <Button className="btn-sm" onClick={exportMoments}>
              Download as CSV
            </Button>
          </div>
          <ol className="recap-moments">
            {moments.map((m, i) => (
              <li key={m.id} className="card recap-moment anim-rise" style={{ animationDelay: `calc(var(--stagger) * ${i + 1})` }}>
                <MomentDiagram m={m} title={safe ? m.safeTitle : m.title} />
                <div className="stack" style={{ gap: 8 }}>
                  <div className="cluster" style={{ gap: 8 }}>
                    <Chip tone="outline">{m.minute}′</Chip>
                    <Chip tone="muted">{CLUBS[m.team].name}</Chip>
                    {!safe && <Chip tone={m.outcome === 'goal' ? 'space' : 'muted'}>{OUTCOME[m.outcome]}</Chip>}
                  </div>
                  <h3 className="card-h3" style={{ margin: 0 }}>
                    {safe ? m.safeTitle : m.title}
                  </h3>
                  <p style={{ fontSize: 15, lineHeight: 1.5 }}>{safe ? m.safeText : m.text}</p>
                  <dl className="recap-figures">
                    <div>
                      <dt>Space created</dt>
                      <dd>
                        <span className="tabular">{num(m.space[0])}</span> m² <span className="muted">· 90% interval {m.space[1]}–{m.space[2]}</span>
                      </dd>
                    </div>
                    <div>
                      <dt>Made by</dt>
                      <dd>{playerLabel(m.creator)}</dd>
                    </div>
                    <div>
                      <dt>Threat created</dt>
                      <dd className="tabular">+{num(m.threat, 2)}</dd>
                    </div>
                  </dl>
                  {m.replay ? (
                    <LinkButton href="#/match?t=0" className="btn-sm" style={{ alignSelf: 'flex-start' }}>
                      Watch the replay
                    </LinkButton>
                  ) : (
                    <p className="muted" style={{ fontSize: 12 }}>
                      Tracking replay: the 63′ moment in this build.
                    </p>
                  )}
                </div>
              </li>
            ))}
          </ol>
        </section>

        <div className="grid-2 recap-lower">
          <Card heading="Space Created leaderboard">
            <ChartFrame
              title={full ? 'Space Created, this match' : 'Space Created, first half'}
              name={`space-created-${kind}`}
              summary={`${playerLabel(top.id)} created the most space off the ball${full ? '' : ' in the first half'}: ${top.v} m², 90% interval ${top.lo} to ${top.hi}. Bars are estimates; whiskers are 90% intervals.`}
              columns={['Player', 'Space created (m²)', '90% low', '90% high']}
              rows={leaders.map((l) => [playerLabel(l.id), l.v, l.lo, l.hi])}
            >
              <Leaderboard rows={leaders} max={150} />
            </ChartFrame>
          </Card>

          <Card heading="Shots">
            <ChartFrame
              title={full ? 'Shot map, this match' : 'Shot map, first half'}
              name={`shots-${kind}`}
              summary={`${shots.length} shots, sized by expected goals: ${shots.filter((s) => s.team === 'kes').length} for Kestrel Bay, ${shots.filter((s) => s.team === 'ash').length} for Ashmoor. ${safe ? 'Outcomes are hidden.' : `${shots.filter((s) => s.outcome === 'goal').length} scored.`} Both teams are shown attacking the goal at the top.`}
              columns={shotTab.columns}
              rows={shotTab.rows}
            >
              <div className="recap-shots">
                <ShotMap shots={shots} hideOutcomes={safe} />
              </div>
            </ChartFrame>
          </Card>
        </div>

        {full ? (
          <div className="recap-share-row">
            <Card heading="Share the moment">
              <div className="recap-share">
                <video className="recap-clip" key={clip} src={`clips/${clip}.mp4`} poster={`clips/${clip}.jpg`} controls muted playsInline preload="metadata" aria-label={safe ? 'Vertical clip of the decoy run, stopping before the finish.' : 'Vertical clip of the decoy run and the goal, with the caption burned in.'} />
                <div className="stack" style={{ gap: 10 }}>
                  <p style={{ fontSize: 14, lineHeight: 1.5 }}>
                    A vertical clip from the 3D view, with the caption burned in and the synthetic-data label{safe ? '. Spoiler-safe: it stops before the finish.' : '.'}
                  </p>
                  <div className="cluster" style={{ gap: 8 }}>
                    <Button className="btn-sm" onClick={() => void shareClip()}>
                      Share the clip
                    </Button>
                    <a className="btn btn-ghost btn-sm press" href={`clips/${clip}.mp4`} download={`offball-${clip}.mp4`}>
                      Download
                    </a>
                  </div>
                </div>
              </div>
            </Card>

            <Card heading="Player card">
              <div className="recap-card">
                <div className="stack" style={{ gap: 12 }}>
                  <label htmlFor="card-player" className="field-label">
                    Player
                  </label>
                  <select id="card-player" className="select" value={cardId} onChange={(e) => setCardId(e.target.value)}>
                    {(['kes', 'ash'] as const).map((team) => (
                      <optgroup key={team} label={CLUBS[team].name}>
                        {PLAYERS.filter((p) => p.team === team).map((p) => (
                          <option key={p.id} value={p.id}>
                            No. {p.num} {p.name}
                          </option>
                        ))}
                      </optgroup>
                    ))}
                  </select>
                  <p className="muted" style={{ fontSize: 13, lineHeight: 1.5 }}>
                    A 1080 × 1350 card with the player’s off-ball numbers and run map. {safe ? 'Spoiler-safe: no result or season line.' : ''}
                  </p>
                  <div className="cluster" style={{ gap: 8 }}>
                    <Button variant="primary" onClick={() => void shareCard()}>
                      Share the card
                    </Button>
                    <Button onClick={async () => download(await cardBlob(cardId, safe), `offball-card-${cardId}.png`)}>Download PNG</Button>
                  </div>
                  <p role="status" className="muted" style={{ fontSize: 13, minHeight: 18 }}>
                    {shared}
                  </p>
                  <div className="recap-heat">
                    <ChartFrame
                      title={`Where No. ${player(cardId).num} played`}
                      name={`heat-${cardId}`}
                      summary={`Where ${playerLabel(cardId)} spent the match: ${heatTab.rows.map(([zone, share]) => `${share} in the ${String(zone).toLowerCase()}`).join(', ')}.`}
                      columns={heatTab.columns}
                      rows={heatTab.rows}
                    >
                      <HeatMap id={cardId} />
                    </ChartFrame>
                  </div>
                </div>
                {cardUrl ? <img className="recap-card-img" src={cardUrl} alt={card.alt} width={1080} height={1350} /> : <div className="recap-card-img skeleton" aria-hidden="true" />}
              </div>
            </Card>
          </div>
        ) : (
          <p className="tile" style={{ fontSize: 14, lineHeight: 1.5 }}>
            Player cards and the vertical clip come with the full-time recap, when the numbers cover the whole match.
          </p>
        )}

        <p className="muted" style={{ fontSize: 12 }}>
          {EXPORT_LABEL}. Every export from this page carries the same label.
        </p>
      </div>
    </div>
  );
}
