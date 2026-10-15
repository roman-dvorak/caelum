import { useEffect, useState } from 'react'
import type { DateIndex } from '@caelum/api-client'
import { remoteApiClient } from '../services/client.ts'

export interface UseDateIndexResult {
  dateIndex: DateIndex | null
  error: string | null
  loading: boolean
}

/** Fetches `<slug>/thumbnails/<date>/index.json` for one specific date —
 * only called once a date is actually selected, per the backend contract
 * ("fetched lazily"). Callers that render this conditionally per-date
 * should mount it with `key={date}` so switching dates gets fresh state
 * for free instead of needing an extra reset effect. */
export function useDateIndex(slug: string, date: string): UseDateIndexResult {
  const [dateIndex, setDateIndex] = useState<DateIndex | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false

    async function load() {
      setLoading(true)
      try {
        const next = await remoteApiClient.getDateIndex(slug, date)
        if (!cancelled) {
          setDateIndex(next)
          setError(null)
        }
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err))
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    void load()
    return () => {
      cancelled = true
    }
  }, [slug, date])

  return { dateIndex, error, loading }
}
