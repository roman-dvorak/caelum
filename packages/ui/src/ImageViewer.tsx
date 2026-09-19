import { useState } from 'react'
import type { FrameMetadata } from '@caelum/api-client'
import { OverlayRenderer } from './OverlayRenderer.js'

export interface ImageViewerProps {
  /** A live blob URL (from the WS binary frame, local-web) or a static URL
   * (remote-web history browsing) — both are just `<img src>` values. */
  src: string
  /** Overlay metadata for this exact image, if any. Omit to show the plain
   * image with no overlay (e.g. while metadata hasn't loaded yet). */
  metadata?: FrameMetadata | null
  alt?: string
  className?: string
  /** How the image fills its container. "contain" (default) never crops;
   * "cover" fills the box and may crop. Only matters when `className` gives
   * the wrapper an explicit size — by default the wrapper just hugs the
   * image's natural aspect ratio. */
  fit?: 'contain' | 'cover'
}

/**
 * Wraps an `<img>` and an `OverlayRenderer` so overlay elements always line
 * up with the rendered image, regardless of whether it came from a live WS
 * blob or a static history URL.
 */
export function ImageViewer({ src, metadata, alt, className, fit = 'contain' }: ImageViewerProps) {
  const [failed, setFailed] = useState(false)

  return (
    <div className={['relative inline-block w-full leading-none', className ?? ''].join(' ')}>
      {failed ? (
        <div className="flex aspect-video w-full items-center justify-center bg-panel text-sm text-ink-faint">
          Image failed to load
        </div>
      ) : (
        <img
          src={src}
          alt={alt ?? 'Camera frame'}
          className={['block w-full', fit === 'cover' ? 'h-full object-cover' : 'h-auto object-contain'].join(' ')}
          onError={() => setFailed(true)}
          onLoad={() => setFailed(false)}
        />
      )}
      {!failed && metadata ? <OverlayRenderer metadata={metadata} /> : null}
    </div>
  )
}
