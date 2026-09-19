import { useEffect, useState } from 'react'
import type { SkyStateResponse } from '@caelum/api-client'
import { localApiClient } from '../services/client.ts'

const POLL_INTERVAL_MS = 30_000

export interface UseSkyStateResult {
  skyState: SkyStateResponse | null
  error: string | null
  loading: boolean
}

/** Polls `/api/skystate` every ~30s — sun/moon position barely moves faster
 * than that, so this is plenty fresh without hammering the backend. */
export function useSkyState(pollIntervalMs = POLL_INTERVAL_MS): UseSkyStateResult {
  const [skyState, setSkyState] = useState<SkyStateResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false

    async function poll() {
      try {
        const next = await localApiClient.getSkyState()
        if (!cancelled) {
          setSkyState(next)
          setError(null)
        }
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err))
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    void poll()
    const id = window.setInterval(() => void poll(), pollIntervalMs)
    return () => {
      cancelled = true
      window.clearInterval(id)
    }
  }, [pollIntervalMs])

  return { skyState, error, loading }
}
