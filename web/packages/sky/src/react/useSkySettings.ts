import { useCallback, useState } from 'react'
import { DEFAULT_MAX_MAGNITUDE } from '../index.ts'

/** What the viewer chose to see of the sky overlay, kept in this browser. */
export interface SkySettings {
  /** Layers switched off (see `SKY_LAYERS`). */
  hidden: ReadonlySet<string>
  /** Dimmest star drawn. */
  maxMagnitude: number
}

const STORAGE_KEY = 'caelum.skyView'

function read(): SkySettings {
  try {
    const raw = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? '{}') as { hidden?: unknown; maxMagnitude?: unknown }
    return {
      hidden: new Set(Array.isArray(raw.hidden) ? raw.hidden.filter((x): x is string => typeof x === 'string') : []),
      maxMagnitude: typeof raw.maxMagnitude === 'number' ? raw.maxMagnitude : DEFAULT_MAX_MAGNITUDE,
    }
  } catch {
    return { hidden: new Set(), maxMagnitude: DEFAULT_MAX_MAGNITUDE }
  }
}

/** The sky settings, persisted in `localStorage` — the same on every page that shows the sky. */
export function useSkySettings(): [SkySettings, (patch: { layer?: [string, boolean]; maxMagnitude?: number }) => void] {
  const [settings, setSettings] = useState<SkySettings>(read)
  const update = useCallback((patch: { layer?: [string, boolean]; maxMagnitude?: number }) => {
    setSettings((previous) => {
      const hidden = new Set(previous.hidden)
      if (patch.layer) {
        if (patch.layer[1]) hidden.delete(patch.layer[0])
        else hidden.add(patch.layer[0])
      }
      const next = { hidden, maxMagnitude: patch.maxMagnitude ?? previous.maxMagnitude }
      try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify({ hidden: [...hidden], maxMagnitude: next.maxMagnitude }))
      } catch {
        /* storage unavailable — the choice just isn't remembered */
      }
      return next
    })
  }, [])
  return [settings, update]
}
