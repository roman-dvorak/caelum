import { useEffect, useState } from 'react'
import type { CameraManifest } from '@caelum/api-client'
import { remoteApiClient } from '../services/client.ts'

export interface UseCameraManifestResult {
  manifest: CameraManifest | null
  error: string | null
  loading: boolean
}

export function useCameraManifest(slug: string): UseCameraManifestResult {
  const [manifest, setManifest] = useState<CameraManifest | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false

    async function load() {
      setLoading(true)
      setManifest(null)
      try {
        const next = await remoteApiClient.getCameraManifest(slug)
        if (!cancelled) {
          setManifest(next)
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
  }, [slug])

  return { manifest, error, loading }
}
