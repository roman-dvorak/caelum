import { useState, type ReactNode } from 'react'

export interface ImageViewerProps {
  /** A live blob URL (from the WS binary frame, local-web) or a static URL
   * (remote-web history browsing) — both are just `<img src>` values. */
  src: string
  /** The overlay the camera rendered for this exact image — a transparent
   * image of the same size, stacked on top. Omit when there is none (not
   * rendered yet, burned into `src`, or overlays switched off). */
  overlaySrc?: string | null
  /** Drawn on top of the image and the overlay, filling the same box — e.g.
   * the live `SkyCanvas`. */
  children?: ReactNode
  /** Hide the overlay without dropping it, e.g. from an on/off toggle. */
  showOverlay?: boolean
  alt?: string
  className?: string
  /** How the image fills its container. "contain" (default) never crops;
   * "cover" fills the box and may crop. Only matters when `className` gives
   * the wrapper an explicit size — by default the wrapper just hugs the
   * image's natural aspect ratio. */
  fit?: 'contain' | 'cover'
}

/**
 * An `<img>` with the camera-rendered overlay stacked exactly over it. The
 * overlay has the frame's aspect ratio and is fitted the same way, so it
 * lines up at any display size — no overlay is ever drawn in the browser.
 */
export function ImageViewer({
  src,
  overlaySrc,
  children,
  showOverlay = true,
  alt,
  className,
  fit = 'contain',
}: ImageViewerProps) {
  const [failed, setFailed] = useState(false)
  const [overlayFailed, setOverlayFailed] = useState<string | null>(null)
  const fitClass = fit === 'cover' ? 'h-full object-cover' : 'h-auto object-contain'

  return (
    <div className={['relative inline-block w-full leading-none', className ?? ''].join(' ')}>
      {failed ? (
        <div className="flex aspect-video w-full items-center justify-center bg-panel text-sm text-ink-muted">
          Image failed to load
        </div>
      ) : (
        <img
          src={src}
          alt={alt ?? 'Camera frame'}
          className={['block w-full', fitClass].join(' ')}
          onError={() => setFailed(true)}
          onLoad={() => setFailed(false)}
        />
      )}
      {!failed && overlaySrc && showOverlay && overlayFailed !== overlaySrc ? (
        <img
          src={overlaySrc}
          alt=""
          aria-hidden
          className={['pointer-events-none absolute inset-0 h-full w-full', fit === 'cover' ? 'object-cover' : 'object-contain'].join(' ')}
          onError={() => setOverlayFailed(overlaySrc)}
        />
      ) : null}
      {!failed && showOverlay ? children : null}
    </div>
  )
}

const LAYER_LABELS: Record<string, string> = {
  grid: 'Grid',
  constellations: 'Constellations',
  stars: 'Stars',
  planets: 'Planets',
  compass: 'Compass',
}

/** One checkbox per toggleable overlay layer (stars, constellations, ...). */
export function LayerToggles({
  layers,
  hidden,
  onChange,
}: {
  layers: string[]
  hidden: ReadonlySet<string>
  onChange: (layer: string, visible: boolean) => void
}) {
  return (
    <>
      {layers.map((layer) => (
        <label key={layer} className="flex items-center gap-2 text-label-md text-ink-muted select-none">
          <input
            type="checkbox"
            checked={!hidden.has(layer)}
            onChange={(e) => onChange(layer, e.target.checked)}
            className="accent-amber"
          />
          {LAYER_LABELS[layer] ?? layer}
        </label>
      ))}
    </>
  )
}

/** The "Overlay" on/off switch shown next to an `ImageViewer`. */
export function OverlayToggle({ checked, onChange }: { checked: boolean; onChange: (checked: boolean) => void }) {
  return (
    <label className="flex items-center gap-2 text-label-md text-ink-muted select-none">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} className="accent-amber" />
      Overlay
    </label>
  )
}
