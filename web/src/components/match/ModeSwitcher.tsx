import { useI18n } from '../../lib/i18n';
import { MODE_IDS, type Mode } from '../../lib/prefs';
import { Segmented } from '../ui';

/** The six viewing modes (PRD 8.1), labelled in the viewer's language. */
export function ModeSwitcher({ value, onChange }: { value: Mode; onChange: (mode: Mode) => void }) {
  const { pack, ui, lang } = useI18n();
  const options = MODE_IDS.map((m) => ({ value: m, label: pack.modes[m].label }));
  return <Segmented options={options} value={value} onChange={onChange} label={ui.viewingMode} minWidth={132} maxWidth={980} dots lang={lang} />;
}
