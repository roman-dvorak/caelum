import { useCallback, useState } from 'react'
import { DEFAULT_MAX_MAGNITUDE } from '../index.ts'

/** What the viewer chose to see of the sky overlay, kept in this browser. */
export interface SkySettings {
  /** The sky is drawn at all. */
  on: boolean
  /** Layers switched off (see `SKY_LAYERS`). */
  hidden: ReadonlySet<string>
  /** Dimmest star drawn. */
  maxMagnitude: number
  /** How opaque the sky is drawn over the picture, 0.1 – 1. */
  opacity: number
}

/** One change to the settings. */
export interface SkySettingsPatch {
  on?: boolean
  layer?: [string, boolean]
  maxMagnitude?: number
  opacity?: number
}

const STORAGE_KEY = 'caelum.skyView'

function read(defaultOn: boolean): SkySettings {
  try {
    const raw = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? '{}') as {
      on?: unknown
      hidden?: unknown
      maxMagnitude?: unknown
      opacity?: unknown
    }
    return {
      on: typeof raw.on === 'boolean' ? raw.on : defaultOn,
      hidden: new Set(Array.isArray(raw.hidden) ? raw.hidden.filter((x): x is string => typeof x === 'string') : []),
      maxMagnitude: typeof raw.maxMagnitude === 'number' ? raw.maxMagnitude : DEFAULT_MAX_MAGNITUDE,
      opacity: typeof raw.opacity === 'number' ? Math.min(1, Math.max(0.1, raw.opacity)) : 1,
    }
  } catch {
    return { on: defaultOn, hidden: new Set(), maxMagnitude: DEFAULT_MAX_MAGNITUDE, opacity: 1 }
  }
}

/**
 * The sky settings, persisted in `localStorage` — the same on every page that
 * shows the sky. `defaultOn` is whether the sky is drawn until the viewer
 * chooses otherwise.
 */
export function useSkySettings(defaultOn = true): [SkySettings, (patch: SkySettingsPatch) => void] {
  const [settings, setSettings] = useState<SkySettings>(() => read(defaultOn))
  const update = useCallback((patch: SkySettingsPatch) => {
    setSettings((previous) => {
      const hidden = new Set(previous.hidden)
      if (patch.layer) {
        if (patch.layer[1]) hidden.delete(patch.layer[0])
        else hidden.add(patch.layer[0])
      }
      const next = {
        on: patch.on ?? previous.on,
        hidden,
        maxMagnitude: patch.maxMagnitude ?? previous.maxMagnitude,
        opacity: patch.opacity ?? previous.opacity,
      }
      try {
        localStorage.setItem(
          STORAGE_KEY,
          JSON.stringify({ on: next.on, hidden: [...hidden], maxMagnitude: next.maxMagnitude, opacity: next.opacity }),
        )
      } catch {
        /* storage unavailable — the choice just isn't remembered */
      }
      return next
    })
  }, [])
  return [settings, update]
}
