import { useEffect, useState } from 'react'
import type { SkyObjectsResponse } from '@caelum/api-client'
import { localApiClient } from '../services/client.ts'

const REFRESH_MS = 60_000

/** The sky over the camera, refreshed once a minute (it moves ~0.25° in that
 * time — far less than a pixel of the live view). `enabled=false` skips the
 * requests, e.g. while the popups are switched off. */
export function useSkyObjects(maxMag = 4.5, enabled = true): SkyObjectsResponse | null {
  const [sky, setSky] = useState<SkyObjectsResponse | null>(null)

  useEffect(() => {
    if (!enabled) return
    let disposed = false
    async function load() {
      try {
        const next = await localApiClient.getSkyObjects(maxMag)
        if (!disposed) setSky(next)
      } catch {
        /* keep the last answer; the popups just go stale */
      }
    }
    void load()
    const timer = window.setInterval(() => void load(), REFRESH_MS)
    return () => {
      disposed = true
      window.clearInterval(timer)
    }
  }, [maxMag, enabled])

  return sky
}
