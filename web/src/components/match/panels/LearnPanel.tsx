import { CONCEPTS, CONCEPT_AT_STEP } from '../../../lib/glossary';
import { fill, useI18n, type Concept } from '../../../lib/i18n';
import { Button, Card, Chip, stagger } from '../../ui';

/**
 * Learn: a short definition the first time each idea appears, a pause-and-explain button, and a personal glossary
 * that grows as the viewer watches (PRD 8.1).
 */
export function LearnPanel({ step, seen, fresh, onExplain }: { step: number; seen: Record<Concept, number>; fresh: boolean; onExplain: () => void }) {
  const { pack, ui } = useI18n();
  const concept = CONCEPT_AT_STEP[step] ?? 'decoy';
  const idea = pack.glossary[concept];
  return (
    <>
      <Card key={concept}>
        <p className="card-label" style={{ marginBottom: 6, color: fresh ? 'var(--space-ink)' : undefined }}>
          {fresh ? ui.newIdea : fill(ui.seen, { n: seen[concept] })}
        </p>
        <h2 className="display" style={{ fontSize: 30, marginBottom: 8 }}>
          {idea.term}
        </h2>
        <p style={{ fontSize: 16, lineHeight: 1.5, marginBottom: 16 }}>{idea.def}</p>
        <Button onClick={onExplain}>{ui.pauseExplain}</Button>
      </Card>
      <Card order={2}>
        <h3 className="card-h3">{ui.glossary}</h3>
        <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexWrap: 'wrap', gap: 8 }}>
          {CONCEPTS.map((c, i) => (
            <li key={c} className="anim-pop" style={stagger(i + 3)}>
              <Chip tone={seen[c] > 0 ? 'space' : 'outline'} size="lg">
                {pack.glossary[c].term} · {seen[c] > 0 ? fill(ui.seen, { n: seen[c] }) : ui.next}
              </Chip>
            </li>
          ))}
        </ul>
      </Card>
    </>
  );
}
