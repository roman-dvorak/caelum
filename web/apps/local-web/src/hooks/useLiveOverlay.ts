import { useState } from 'react'
import type { FrameMetadata } from '@caelum/api-client'
import { localApiClient } from '../services/client.ts'

/** URL of the camera-rendered overlay for the live frame. Each frame
 * arrives first without one and again once every plugin has contributed and
 * it has been rendered; until then the previous frame's overlay stays up,
 * so it doesn't blink off on every capture. */
export function useLiveOverlay(metadata: FrameMetadata | undefined): string | null {
  const current = metadata?.overlay
    ? localApiClient.latestOverlayUrl(`${metadata.captured_at}:${metadata.overlay_elements.length}`)
    : null
  const [last, setLast] = useState<string | null>(null)
  if (current && current !== last) setLast(current)
  return current ?? last
}
