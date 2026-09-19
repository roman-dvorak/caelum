import { ImageViewer } from '@caelum/ui'
import { useFrameMetadata } from '../hooks/useFrameMetadata.ts'
import { remoteApiClient } from '../services/client.ts'

export interface GalleryItemProps {
  slug: string
  time: string
  thumbnailPath: string
  metadataPath: string
}

/** One gallery tile: resolves its own thumbnail URL and lazily fetches its
 * `<HHMMSS>.json` sidecar so the overlay (timestamp, exposure, sky state,
 * any detection boxes) renders once it arrives. */
export function GalleryItem({ slug, time, thumbnailPath, metadataPath }: GalleryItemProps) {
  const metadata = useFrameMetadata(slug, metadataPath)
  const thumbnailUrl = remoteApiClient.resolveCameraUrl(slug, thumbnailPath)

  return (
    <figure className="overflow-hidden border border-line bg-void">
      <ImageViewer src={thumbnailUrl} metadata={metadata} alt={`Frame at ${time}`} />
      <figcaption className="border-t border-line-soft px-2 py-1 text-center font-mono text-xs text-ink-faint">
        {formatTime(time)}
      </figcaption>
    </figure>
  )
}

function formatTime(time: string): string {
  const match = /^(\d{2})(\d{2})(\d{2})$/.exec(time)
  if (!match) return time
  const [, h, m, s] = match
  return `${h}:${m}:${s}`
}
