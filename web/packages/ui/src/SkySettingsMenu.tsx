import { useEffect, useRef, useState } from 'react'
import { SKY_LAYERS } from '@roman-dvorak/caelum-sky'
import type { SkySettings, SkySettingsPatch } from '@roman-dvorak/caelum-sky/react'

const LABELS: Record<string, string> = {
  outline: 'Lens outline & centre',
  grid: 'Horizon & altitude rings',
  ecliptic: 'Ecliptic',
  constellations: 'Constellation lines',
  stars: 'Stars',
  planets: 'Sun, Moon & planets',
  compass: 'Compass',
}

/**
 * The sky overlay's controls: a "Sky" checkbox switches it on and off, and the
 * small arrow next to it folds out which parts are drawn and how faint a star.
 * The values live in `useSkySettings` (saved in the browser).
 */
export function SkySettingsMenu({
  settings,
  onChange,
}: {
  settings: SkySettings
  onChange: (patch: SkySettingsPatch) => void
}) {
  const [open, setOpen] = useState(false)
  const root = useRef<HTMLSpanElement>(null)

  // Closes on a click elsewhere or Escape.
  useEffect(() => {
    if (!open) return
    const onDown = (e: PointerEvent) => {
      if (root.current && !root.current.contains(e.target as Node)) setOpen(false)
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('pointerdown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('pointerdown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  return (
    <span ref={root} className="relative inline-flex items-center gap-1 text-label-md text-ink-muted">
      <label className="flex items-center gap-2 select-none">
        <input
          type="checkbox"
          checked={settings.on}
          onChange={(e) => onChange({ on: e.target.checked })}
          className="accent-amber"
        />
        Sky
      </label>
      <button
        type="button"
        aria-expanded={open}
        aria-label="What to draw"
        title="What to draw"
        onClick={() => setOpen((v) => !v)}
        className="rounded px-1 hover:text-ink"
      >
        ▾
      </button>
      {open ? (
        <div className="absolute top-full right-0 z-20 mt-1 flex w-60 max-w-[calc(100vw-2rem)] flex-col items-start gap-2 rounded-md border border-border bg-panel p-3 text-left shadow-md">
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
          <label className="flex w-full flex-col gap-1 select-none">
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
          <label className="flex w-full flex-col gap-1 select-none">
            Opacity: {Math.round(settings.opacity * 100)} %
            <input
              type="range"
              min={10}
              max={100}
              step={5}
              value={Math.round(settings.opacity * 100)}
              onChange={(e) => onChange({ opacity: Number(e.target.value) / 100 })}
              className="accent-amber"
            />
          </label>
        </div>
      ) : null}
    </span>
  )
}
