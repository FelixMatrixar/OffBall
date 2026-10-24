import { useI18n } from '../../../lib/i18n';
import { Button, Card, Equalizer, Switch } from '../../ui';

interface Line {
  t: number;
  text: string;
}

interface Props {
  lines: readonly Line[];
  t: number;
  playing: boolean;
  /** Where the cue is panned: -1 left, 1 right. */
  pan: number;
  narration: boolean;
  onNarration: (on: boolean) => void;
  voiceName: string | null;
  onTestCue: () => void;
}

/**
 * Audio-described mode (PRD 10.5): a spoken description of shape and space, paced so it never talks over itself,
 * with a stereo cue placed where space is opening. The transcript mirrors what is spoken.
 */
export function AudioPanel({ lines, t, playing, pan, narration, onNarration, voiceName, onTestCue }: Props) {
  const { lang } = useI18n();
  let active = 0;
  lines.forEach((line, i) => {
    if (t >= line.t) active = i;
  });
  const left = `${(50 + pan * 50).toFixed(1)}%`;
  const cueLabel = pan > 0.55 ? 'Right' : pan > 0.15 ? 'Right of centre' : pan < -0.55 ? 'Left' : pan < -0.15 ? 'Left of centre' : 'Centre';
  return (
    <>
      <Card>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12 }}>
          <Equalizer active={playing && narration} bars={5} height={20} />
          <h2 className="display" style={{ fontSize: 24 }}>
            Describing the shape of play
          </h2>
        </div>
        <ol style={{ listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexDirection: 'column', gap: 8 }} lang={lang}>
          {lines.map((line, i) => (
            <li key={line.t} className="transcript-line" data-state={i === active ? 'active' : i < active ? 'done' : 'todo'} aria-current={i === active ? 'true' : undefined}>
              <span className="transcript-bar" aria-hidden="true" />
              <span className="mono" style={{ fontSize: 12, color: 'var(--muted)', flex: 'none', paddingTop: 3 }} dir="ltr">
                63:{line.t < 10 ? '0' : ''}
                {line.t.toFixed(1)}
              </span>
              <span>{line.text}</span>
            </li>
          ))}
        </ol>
      </Card>
      <Card order={2}>
        <Switch block checked={narration} onChange={onNarration} label="Narration" hint={voiceName ? `Device voice: ${voiceName}` : 'No device voice for this language: the transcript carries on'} />
      </Card>
      <Card order={3}>
        <h3 className="card-h3" style={{ marginBottom: 4 }}>
          Stereo cue
        </h3>
        <p style={{ marginBottom: 12, fontSize: 13, color: 'var(--muted)' }}>A soft tone, panned to where space is opening.</p>
        <div style={{ position: 'relative', height: 12, borderRadius: 6, background: 'var(--surface-2)' }} dir="ltr" aria-hidden="true">
          <span style={{ position: 'absolute', top: -4, left, transform: 'translateX(-50%)', transition: 'left var(--dur-base) var(--ease-standard)' }}>
            <span style={{ position: 'relative', display: 'block', width: 20, height: 20 }}>
              <span style={{ position: 'absolute', inset: 0, borderRadius: 10, background: 'var(--space)' }} />
              <span className="anim-ripple" style={{ position: 'absolute', inset: 0, borderRadius: 10, border: '2px solid var(--space)' }} />
            </span>
          </span>
        </div>
        {/* The scale's ends and middle stay put; where the cue is now is said once, apart from them. */}
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, color: 'var(--muted)', marginTop: 6 }} dir="ltr" aria-hidden="true">
          <span>Left</span>
          <span>Centre</span>
          <span>Right</span>
        </div>
        <p style={{ margin: '8px 0 0', fontSize: 14 }} role="status">
          Now: <strong>{cueLabel}</strong>
        </p>
        <Button variant="ghost" className="btn-sm" style={{ marginTop: 10 }} onClick={onTestCue}>
          Play a test cue
        </Button>
      </Card>
    </>
  );
}
