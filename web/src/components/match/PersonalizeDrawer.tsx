import { learnedDensity, listOf } from '../../lib/density';
import { PACKS } from '../../lib/i18n';
import { CLUBS, PLAYERS, type Team } from '../../lib/match';
import { MODE_IDS, THEMES, usePrefs, type Club, type Density, type Metric, type Theme, type TierChoice, type View } from '../../lib/prefs';
import { TIERS } from '../../lib/tiers';
import { Button, CheckIcon, Drawer, Segmented, Switch } from '../ui';
import { METRIC_LABEL } from './panels';

const DENSITIES: readonly { value: Density; label: string }[] = [
  { value: 'minimal', label: 'Minimal' },
  { value: 'standard', label: 'Standard' },
  { value: 'rich', label: 'Rich' },
];

const THEME_LABEL: Record<Theme, string> = { dark: 'Dark', light: 'Light', contrast: 'High contrast' };

const TIER_OPTIONS: readonly { value: TierChoice; label: string }[] = [
  { value: 'auto', label: 'Automatic' },
  { value: 'A', label: `Tier A · ${TIERS.A.name} 3D` },
  { value: 'B', label: `Tier B · ${TIERS.B.name} 3D` },
  { value: 'C', label: `Tier C · ${TIERS.C.name}` },
  { value: 'D', label: `Tier D · ${TIERS.D.name} (replays)` },
];

export const VIEW_OPTIONS: readonly { value: View; label: string }[] = [
  { value: '2d', label: '2D tactical' },
  { value: 'broadcast', label: '3D broadcast' },
  { value: 'tactical', label: '3D tactical' },
  { value: 'player', label: 'Player cam' },
  { value: 'goal', label: 'Behind the goal' },
];

/** Every personalization control in one drawer (PRD 8.2, 15.9). Settings stay on the device. */
export function PersonalizeDrawer({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { prefs, update } = usePrefs();
  const clubs: readonly Exclude<Club, 'none'>[] = ['kes', 'ash'];
  // What adaptive density has learned, mode by mode (PRD 8.2).
  const learned = MODE_IDS.flatMap((m) => {
    const groups = prefs.hidden[m] ?? [];
    if (!groups.length) return [];
    const fewer = learnedDensity(prefs.density, groups, true) !== prefs.density;
    return [{ mode: m, text: `${listOf(groups)} hidden${fewer ? ' · fewer overlays' : ''}` }];
  });
  return (
    <Drawer open={open} onClose={onClose} title="Personalize">
      <section className="anim-rise">
        <h3 className="field-label">Your club</h3>
        <div className="grid-2">
          {clubs.map((c) => {
            const on = prefs.club === c;
            return (
              <button
                key={c}
                type="button"
                aria-pressed={on}
                onClick={() => update({ club: on ? 'none' : c })}
                className="press"
                style={{ display: 'flex', alignItems: 'center', gap: 10, minHeight: 56, padding: '0 14px', borderRadius: 12, border: 0, background: 'var(--surface-2)', textAlign: 'start', fontWeight: 600, boxShadow: `inset 0 0 0 ${on ? '2px var(--space)' : '1px var(--line)'}` }}
              >
                <span style={{ width: 22, height: 26, flex: 'none', borderRadius: '4px 4px 11px 11px', background: `var(--${c})` }} />
                {CLUBS[c].name}
                {on && (
                  <span className="anim-pop" style={{ marginInlineStart: 'auto', width: 20, height: 20, borderRadius: 10, background: 'var(--space)', color: 'var(--on-space)', display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}>
                    <CheckIcon size={12} />
                  </span>
                )}
              </button>
            );
          })}
        </div>
      </section>

      <section className="anim-rise">
        <label htmlFor="pz-fav" className="field-label">
          Favourite player
        </label>
        <select id="pz-fav" className="select" value={prefs.fav} onChange={(e) => update({ fav: e.target.value })}>
          {(['kes', 'ash'] as Team[]).map((team) => (
            <optgroup key={team} label={CLUBS[team].name}>
              {PLAYERS.filter((p) => p.team === team).map((p) => (
                <option key={p.id} value={p.id}>
                  No. {p.num} · {p.name}
                </option>
              ))}
            </optgroup>
          ))}
        </select>
      </section>

      <section className="anim-rise">
        <h3 className="field-label">The number you care about</h3>
        <div className="cluster" style={{ gap: 8 }}>
          {(Object.keys(METRIC_LABEL) as Metric[]).map((m) => (
            <button key={m} type="button" className="pill press" aria-pressed={prefs.metric === m} onClick={() => update({ metric: m })}>
              {METRIC_LABEL[m]}
            </button>
          ))}
        </div>
      </section>

      <section className="anim-rise">
        <h3 className="field-label">Overlay density</h3>
        <Segmented options={DENSITIES} value={prefs.density} onChange={(density) => update({ density })} label="Overlay density" />
      </section>

      <section className="anim-rise stack" style={{ gap: 10 }}>
        <Switch
          block
          checked={prefs.adapt}
          onChange={(adapt) => update({ adapt })}
          label="Adapt to what I hide or show"
          hint="Remembers the pitch graphics you hide with Overlays, for each mode, and shows fewer once you hide two. On this device only."
        />
        {learned.length > 0 ? (
          <div className="learned" data-paused={!prefs.adapt}>
            <ul className="learned-list">
              {learned.map((l) => (
                <li key={l.mode} className="anim-fade">
                  <strong>{PACKS.en.modes[l.mode].label}</strong> · {l.text}
                </li>
              ))}
            </ul>
            {!prefs.adapt && <p className="muted" style={{ fontSize: 12 }}>Paused while Adapt is off.</p>}
            <Button variant="ghost" className="btn-sm" onClick={() => update({ hidden: {} })}>
              Forget what it learned
            </Button>
          </div>
        ) : (
          <p className="muted" style={{ fontSize: 12 }}>
            Nothing learned yet. Hide something with Overlays on the pitch.
          </p>
        )}
      </section>

      <section className="anim-rise">
        <h3 className="field-label">Theme</h3>
        <Segmented options={THEMES.map((t) => ({ value: t, label: THEME_LABEL[t] }))} value={prefs.theme} onChange={(theme) => update({ theme })} label="Theme" />
      </section>

      <section className="anim-rise stack">
        <Switch block checked={prefs.voice} onChange={(voice) => update({ voice })} label="Voice commentary" hint="Spoken lines in your language, with your device’s voice" />
        <Switch block checked={prefs.sonify} onChange={(sonify) => update({ sonify })} label="Space sonification" hint="A stereo tone where space is opening" />
        <Switch block checked={prefs.reducedMotion} onChange={(reducedMotion) => update({ reducedMotion })} label="Reduced motion" hint="Fades instead of movement; no pulses" />
        <Switch block checked={prefs.layout === 'tv'} onChange={(tv) => update({ layout: tv ? 'tv' : 'auto' })} label="TV layout" hint="Larger type and focus for watching from the sofa" />
        <Switch block checked={prefs.spoilerSafe} onChange={(spoilerSafe) => update({ spoilerSafe })} label="Spoiler-safe recaps" hint="Recaps hide scores and results until you ask for them" />
      </section>

      <section className="anim-rise">
        <label htmlFor="pz-cap" className="field-label" style={{ display: 'flex', justifyContent: 'space-between' }}>
          <span>Caption size</span>
          <span className="tabular" style={{ color: 'var(--text)' }}>
            {prefs.capSize} px
          </span>
        </label>
        <input id="pz-cap" className="range" type="range" min={16} max={28} step={1} value={prefs.capSize} onChange={(e) => update({ capSize: Number(e.target.value) })} />
      </section>

      <section className="anim-rise">
        <label htmlFor="pz-view" className="field-label">
          Pitch view
        </label>
        <select id="pz-view" className="select" value={prefs.view} onChange={(e) => update({ view: e.target.value as View })}>
          {VIEW_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
        <p className="muted" style={{ fontSize: 12, marginTop: 6 }}>
          The 3D views load when you pick one. On a device that can’t draw them, the 2D view stays.
        </p>
      </section>

      <section className="anim-rise">
        <label htmlFor="pz-tier" className="field-label">
          Rendering tier
        </label>
        <select id="pz-tier" className="select" value={prefs.tier} onChange={(e) => update({ tier: e.target.value as TierChoice })}>
          {TIER_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
        <p className="muted" style={{ fontSize: 12, marginTop: 6 }}>
          Automatic picks the best your device can hold and steps down when it can’t.
        </p>
      </section>

      <p style={{ marginTop: 'auto', fontSize: 12, color: 'var(--muted)' }}>Saved on this device only. No account needed.</p>
    </Drawer>
  );
}
