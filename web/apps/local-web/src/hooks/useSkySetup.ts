import { useEffect, useState } from 'react'
import type { SkySetup } from '@caelum/api-client'
import { localApiClient } from '../services/client.ts'

const REFRESH_MS = 60_000

/** The lens and the observer's position the browser draws the sky from; it is
 * re-read every minute so a recalibration shows up without a reload. */
export function useSkySetup(): SkySetup | null {
  const [setup, setSetup] = useState<SkySetup | null>(null)
  useEffect(() => {
    let disposed = false
    async function load() {
      try {
        const next = await localApiClient.getSkySetup()
        // Same values -> same object, so the canvas does not redraw for nothing.
        if (!disposed) setSetup((previous) => (JSON.stringify(previous) === JSON.stringify(next) ? previous : next))
      } catch {
        /* keep the last one */
      }
    }
    void load()
    const timer = window.setInterval(() => void load(), REFRESH_MS)
    return () => {
      disposed = true
      window.clearInterval(timer)
    }
  }, [])
  return setup
}
