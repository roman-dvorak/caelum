import { useEffect, useState } from 'react'
import type { SystemInfoResponse } from '@caelum/api-client'
import { localApiClient } from '../services/client.ts'

const POLL_INTERVAL_MS = 3_000

export interface UseSystemInfoResult {
  info: SystemInfoResponse | null
  error: string | null
  loading: boolean
}

/** Polls `/api/system/info` on an interval — plain REST is enough for
 * numbers that only need to look "live", not push-exact. */
export function useSystemInfo(pollIntervalMs = POLL_INTERVAL_MS): UseSystemInfoResult {
  const [info, setInfo] = useState<SystemInfoResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false

    async function poll() {
      try {
        const next = await localApiClient.getSystemInfo()
        if (!cancelled) {
          setInfo(next)
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

  return { info, error, loading }
}
