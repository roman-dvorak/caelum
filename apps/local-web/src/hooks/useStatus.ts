import { useEffect, useState } from 'react'
import type { StatusResponse } from '@caelum/api-client'
import { localApiClient } from '../services/client.ts'

const POLL_INTERVAL_MS = 5_000

export interface UseStatusResult {
  status: StatusResponse | null
  error: string | null
  loading: boolean
}

/** Polls `/api/status` on an interval. Cheap enough (a single small JSON
 * response) that plain polling beats plumbing another WS channel for it. */
export function useStatus(pollIntervalMs = POLL_INTERVAL_MS): UseStatusResult {
  const [status, setStatus] = useState<StatusResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false

    async function poll() {
      try {
        const next = await localApiClient.getStatus()
        if (!cancelled) {
          setStatus(next)
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

  return { status, error, loading }
}
