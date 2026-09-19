import { useEffect, useState } from 'react'
import type { CamerasIndex } from '@caelum/api-client'
import { remoteApiClient } from '../services/client.ts'

export interface UseCamerasResult {
  cameras: CamerasIndex | null
  error: string | null
  loading: boolean
}

export function useCameras(): UseCamerasResult {
  const [cameras, setCameras] = useState<CamerasIndex | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false

    async function load() {
      setLoading(true)
      try {
        const index = await remoteApiClient.getCameras()
        if (!cancelled) {
          setCameras(index)
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
  }, [])

  return { cameras, error, loading }
}
