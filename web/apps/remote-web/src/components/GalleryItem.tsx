import type { LensConfig } from '@caelum/api-client'
import { ImageViewer, SkyCanvas, formatCaptureTime } from '@caelum/ui'
import { remoteApiClient } from '../services/client.ts'

/** What the viewer needs to draw the sky over a frame itself — published by
 * cameras with `camera.identity.publish_location` on. */
export interface SkyView {
  lens: LensConfig
  lat: number
  lon: number
  hidden: ReadonlySet<string>
}

export interface GalleryItemProps {
  slug: string
  time: string
  thumbnailPath: string
  /** The camera-rendered overlay PNG, when it is a separate file — absent
   * when it is burned into the thumbnail or overlays are switched off. */
  overlayPath?: string
  showOverlay?: boolean
  sky?: SkyView
}

/** `YYYYMMDD-HHMMSS` (UTC) -> Date. */
function captureDate(time: string): Date {
  const m = /^(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})(\d{2})$/.exec(time)
  return m ? new Date(Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], +m[6])) : new Date(NaN)
}

/** One gallery tile: the thumbnail with the overlay the camera rendered for
 * it stacked on top — the same pixels the camera's own live view shows — and,
 * when the camera published its position, the sky drawn live over it. */
export function GalleryItem({ slug, time, thumbnailPath, overlayPath, showOverlay = true, sky }: GalleryItemProps) {
  const when = captureDate(time)
  return (
    <figure className="overflow-hidden border border-border bg-surface-0 rounded-md">
      <ImageViewer
        src={remoteApiClient.resolveCameraUrl(slug, thumbnailPath)}
        overlaySrc={overlayPath ? remoteApiClient.resolveCameraUrl(slug, overlayPath) : null}
        showOverlay={showOverlay}
        alt={`Frame at ${time}`}
      >
        {sky && !Number.isNaN(when.getTime()) ? (
          <SkyCanvas lens={sky.lens} latDeg={sky.lat} lonDeg={sky.lon} when={when} hidden={sky.hidden} />
        ) : null}
      </ImageViewer>
      <figcaption className="border-t border-border-subtle px-2 py-1 text-center font-mono text-xs text-ink-muted">
        {formatCaptureTime(time)}
      </figcaption>
    </figure>
  )
}
