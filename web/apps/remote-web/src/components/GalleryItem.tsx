import { ImageViewer, formatCaptureTime } from '@caelum/ui'
import { remoteApiClient } from '../services/client.ts'

export interface GalleryItemProps {
  slug: string
  time: string
  thumbnailPath: string
  /** The camera-rendered overlay PNG, when it is a separate file — absent
   * when it is burned into the thumbnail or overlays are switched off. */
  overlayPath?: string
  /** Paths of the toggleable overlay layers to stack, already filtered to the visible ones. */
  layerPaths?: string[]
  showOverlay?: boolean
}

/** One gallery tile: the thumbnail with the overlay the camera rendered for
 * it stacked on top — the same pixels the camera's own live view shows. */
export function GalleryItem({ slug, time, thumbnailPath, overlayPath, layerPaths = [], showOverlay = true }: GalleryItemProps) {
  return (
    <figure className="overflow-hidden border border-border bg-surface-0 rounded-md">
      <ImageViewer
        src={remoteApiClient.resolveCameraUrl(slug, thumbnailPath)}
        overlaySrc={overlayPath ? remoteApiClient.resolveCameraUrl(slug, overlayPath) : null}
        layerSrcs={layerPaths.map((path) => remoteApiClient.resolveCameraUrl(slug, path))}
        showOverlay={showOverlay}
        alt={`Frame at ${time}`}
      />
      <figcaption className="border-t border-border-subtle px-2 py-1 text-center font-mono text-xs text-ink-muted">
        {formatCaptureTime(time)}
      </figcaption>
    </figure>
  )
}
