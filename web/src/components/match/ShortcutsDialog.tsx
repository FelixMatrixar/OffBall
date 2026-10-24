import { Dialog } from '../ui';

export const SHORTCUTS: readonly { keys: string[]; action: string }[] = [
  { keys: ['Space', 'K'], action: 'Play or pause' },
  { keys: [',', '.'], action: 'Back or forward one frame' },
  { keys: ['J', 'L'], action: 'Previous or next moment' },
  { keys: ['[', ']'], action: 'Slower or faster' },
  { keys: ['Home', 'End'], action: 'Start or end of the moment' },
  { keys: ['1', '–', '6'], action: 'Viewing mode: Casual, Learn, Analyst, Player focus, Audio-described, Broadcaster' },
  { keys: ['W'], action: 'What if no run?' },
  { keys: ['D'], action: 'Change one decision; Escape closes it' },
  { keys: ['V'], action: 'Next view: 2D, 3D broadcast, 3D tactical, player cam, behind the goal' },
  { keys: ['S'], action: 'Save a snapshot of the pitch as PNG' },
  { keys: ['A'], action: 'Ask OffBall' },
  { keys: ['P'], action: 'Personalize' },
  { keys: ['?'], action: 'This list' },
  { keys: ['Tab'], action: 'Into the pitch, then arrow keys move between players, up and down switch teams, Enter follows a player' },
];

/** Full keyboard control (PRD 15.4), listed. */
export function ShortcutsDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  return (
    <Dialog open={open} onClose={onClose} title="Keyboard shortcuts">
      <table className="chart-table">
        <caption className="sr-only">Keyboard shortcuts for the match view</caption>
        <thead>
          <tr>
            <th scope="col">Keys</th>
            <th scope="col">Does</th>
          </tr>
        </thead>
        <tbody>
          {SHORTCUTS.map((s) => (
            <tr key={s.action}>
              <td style={{ whiteSpace: 'nowrap' }}>
                {s.keys.map((k, i) => (k === '–' ? <span key={i}> to </span> : <kbd key={i} className="kbd">{k}</kbd>))}
              </td>
              <td>{s.action}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Dialog>
  );
}
