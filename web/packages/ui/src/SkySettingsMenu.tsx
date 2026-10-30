import { SKY_LAYERS } from '@roman-dvorak/caelum-sky'
import type { SkySettings } from '@roman-dvorak/caelum-sky/react'

const LABELS: Record<string, string> = {
  outline: 'Lens outline & centre',
  grid: 'Horizon & altitude rings',
  constellations: 'Constellation lines',
  stars: 'Stars',
  planets: 'Sun, Moon & planets',
  compass: 'Compass',
}

/**
 * The sky overlay's settings, folded into one small "Sky" control so they stay
 * out of the way: which parts are drawn and how faint a star. Saved in the
 * browser by `useSkySettings`.
 */
export function SkySettingsMenu({
  settings,
  onChange,
}: {
  settings: SkySettings
  onChange: (patch: { layer?: [string, boolean]; maxMagnitude?: number }) => void
}) {
  return (
    <details className="relative text-label-md text-ink-muted">
      <summary className="cursor-pointer list-none select-none rounded-md border border-border px-2 py-1 hover:text-ink">
        Sky ▾
      </summary>
      <div className="absolute right-0 z-20 mt-1 flex w-60 flex-col gap-2 rounded-md border border-border bg-panel p-3 shadow-md">
        {SKY_LAYERS.map((layer) => (
          <label key={layer} className="flex items-center gap-2 select-none">
            <input
              type="checkbox"
              checked={!settings.hidden.has(layer)}
              onChange={(e) => onChange({ layer: [layer, e.target.checked] })}
              className="accent-amber"
            />
            {LABELS[layer] ?? layer}
          </label>
        ))}
        <label className="flex flex-col gap-1 select-none">
          Faintest star: mag {settings.maxMagnitude.toFixed(1)}
          <input
            type="range"
            min={0}
            max={5}
            step={0.5}
            value={settings.maxMagnitude}
            onChange={(e) => onChange({ maxMagnitude: Number(e.target.value) })}
            className="accent-amber"
          />
        </label>
      </div>
    </details>
  )
}
