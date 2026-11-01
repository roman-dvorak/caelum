import { useEffect, useRef, useState } from 'react'
import { SKY_LAYERS, SKY_SLIDERS, skySliderLabel, skyText } from '@roman-dvorak/caelum-sky'
import type { SkySettings, SkySettingsPatch } from '@roman-dvorak/caelum-sky/react'

/**
 * The sky overlay's controls: a "Sky" checkbox switches it on and off, and the
 * small arrow next to it folds out which parts are drawn and how faint a star.
 * The values live in `useSkySettings` (saved in the browser).
 */
export function SkySettingsMenu({
  settings,
  onChange,
  locale = 'en',
}: {
  settings: SkySettings
  onChange: (patch: SkySettingsPatch) => void
  locale?: string
}) {
  const text = skyText(locale)
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
        {text.sky}
      </label>
      <button
        type="button"
        aria-expanded={open}
        aria-label={text.options}
        title={text.options}
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
              {text.layers[layer]}
            </label>
          ))}
          {SKY_SLIDERS.map((spec) => (
            <label key={spec.key} className="flex w-full flex-col gap-1 select-none">
              {skySliderLabel(spec, text, settings[spec.key])}
              <input
                type="range"
                min={spec.min}
                max={spec.max}
                step={spec.step}
                value={Math.round(settings[spec.key] * spec.factor * 100) / 100}
                onChange={(e) => onChange({ [spec.key]: Number(e.target.value) / spec.factor })}
                className="accent-amber"
              />
            </label>
          ))}
        </div>
      ) : null}
    </span>
  )
}
