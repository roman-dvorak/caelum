import { useEffect, useState } from 'react'
import type { FrameMetadata } from '@caelum/api-client'
import { remoteApiClient } from '../services/client.ts'

/** Fetches a single `<HHMMSS>.json` sidecar for one gallery thumbnail. Kept
 * as its own tiny hook (rather than batch-fetching a whole date's worth of
 * sidecars up front) so opening a date with hundreds of frames doesn't fire
 * hundreds of requests before anything is visible. */
export function useFrameMetadata(slug: string, relativeMetadataPath: string): FrameMetadata | null {
  const [metadata, setMetadata] = useState<FrameMetadata | null>(null)

  useEffect(() => {
    let cancelled = false

    async function load() {
      try {
        const next = await remoteApiClient.getFrameMetadata(slug, relativeMetadataPath)
        if (!cancelled) setMetadata(next)
      } catch {
        // Missing/invalid sidecar just means no overlay for this frame.
        if (!cancelled) setMetadata(null)
      }
    }

    void load()
    return () => {
      cancelled = true
    }
  }, [slug, relativeMetadataPath])

  return metadata
}
