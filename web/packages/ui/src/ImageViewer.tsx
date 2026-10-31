import { useCallback, useEffect, useRef, useState, type ReactNode, type Ref } from 'react'
import { SkyDetailContext } from '@roman-dvorak/caelum-sky/react'

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
  /** Wheel to zoom (about the pointer), drag to pan, double-click to reset, with
   * +/−/reset buttons. The image, overlay and children move together, so a
   * `SkyCanvas` child stays on its stars; it is redrawn crisp up to 4×.
   * Pointer events a child claims (dragging a star, picking a point) do not pan. */
  zoomable?: boolean
  /** The `<img>` element, e.g. to read its pixels. */
  imgRef?: Ref<HTMLImageElement>
  /** The picture finished loading (its natural size is then known). */
  onImageLoad?: (img: HTMLImageElement) => void
}

const MAX_ZOOM = 40
/** The sky is redrawn at the zoomed size up to this factor, scaled as a bitmap beyond it. */
const MAX_DETAIL = 4

interface View {
  scale: number
  x: number
  y: number
}
const RESET: View = { scale: 1, x: 0, y: 0 }

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
  zoomable = false,
  imgRef,
  onImageLoad,
}: ImageViewerProps) {
  // The src that failed: a new src gets a fresh try instead of staying on the error message.
  const [failedSrc, setFailedSrc] = useState<string | null>(null)
  const failed = failedSrc === src
  const [overlayFailed, setOverlayFailed] = useState<string | null>(null)
  const fitClass = fit === 'cover' ? 'h-full object-cover' : 'h-auto object-contain'

  const box = useRef<HTMLDivElement>(null)
  const [view, setView] = useState<View>(RESET)
  const pan = useRef<{ x: number; y: number; vx: number; vy: number } | null>(null)

  // Keep the picture covering the box: it cannot be panned off into empty space.
  const clamp = useCallback((v: View): View => {
    const el = box.current
    if (!el || v.scale <= 1) return RESET
    return {
      scale: v.scale,
      x: Math.min(0, Math.max(el.clientWidth * (1 - v.scale), v.x)),
      y: Math.min(0, Math.max(el.clientHeight * (1 - v.scale), v.y)),
    }
  }, [])

  /** Zoom by `factor` about (cx, cy), in pixels from the box's top-left corner. */
  const zoomAt = useCallback(
    (factor: number, cx: number, cy: number) =>
      setView((v) => {
        const scale = Math.min(MAX_ZOOM, Math.max(1, v.scale * factor))
        const k = scale / v.scale
        return clamp({ scale, x: cx - (cx - v.x) * k, y: cy - (cy - v.y) * k })
      }),
    [clamp],
  )

  useEffect(() => {
    const el = box.current
    if (!zoomable || !el) return
    const onWheel = (e: WheelEvent) => {
      e.preventDefault()
      const r = el.getBoundingClientRect()
      zoomAt(Math.exp(-e.deltaY * 0.0015), e.clientX - r.left, e.clientY - r.top)
    }
    el.addEventListener('wheel', onWheel, { passive: false })
    return () => el.removeEventListener('wheel', onWheel)
  }, [zoomable, zoomAt])

  const scale = zoomable ? view.scale : 1
  const centre = () => ({ x: (box.current?.clientWidth ?? 0) / 2, y: (box.current?.clientHeight ?? 0) / 2 })

  return (
    <div
      ref={box}
      className={['relative inline-block w-full leading-none', zoomable ? 'overflow-hidden' : '', className ?? ''].join(' ')}
      style={zoomable && scale > 1 ? { cursor: 'grab', touchAction: 'none' } : undefined}
      onPointerDown={
        zoomable
          ? (e) => {
              if (view.scale === 1 || e.button !== 0) return
              e.currentTarget.setPointerCapture(e.pointerId)
              pan.current = { x: e.clientX, y: e.clientY, vx: view.x, vy: view.y }
            }
          : undefined
      }
      onPointerMove={
        zoomable
          ? (e) => {
              const p = pan.current
              if (p) setView((v) => clamp({ ...v, x: p.vx + e.clientX - p.x, y: p.vy + e.clientY - p.y }))
            }
          : undefined
      }
      onPointerUp={zoomable ? () => (pan.current = null) : undefined}
      onPointerCancel={zoomable ? () => (pan.current = null) : undefined}
      onDoubleClick={zoomable ? () => setView(RESET) : undefined}
    >
      <div
        style={
          zoomable
            ? { transformOrigin: '0 0', transform: `translate(${view.x}px, ${view.y}px) scale(${view.scale})` }
            : undefined
        }
        className="relative h-full w-full leading-none"
      >
        <SkyDetailContext.Provider value={Math.min(scale, MAX_DETAIL)}>
      {failed ? (
        <div className="flex aspect-video w-full items-center justify-center bg-panel text-sm text-ink-muted">
          Image failed to load
        </div>
      ) : (
        <img
          src={src}
          alt={alt ?? 'Camera frame'}
          className={['block w-full', fitClass].join(' ')}
          ref={imgRef}
          draggable={false}
          onError={() => setFailedSrc(src)}
          onLoad={(e) => {
            setFailedSrc(null)
            onImageLoad?.(e.currentTarget)
          }}
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
        </SkyDetailContext.Provider>
      </div>
      {zoomable ? (
        <div
          className="absolute top-2 right-2 z-20 flex items-center gap-1 rounded-md bg-panel/80 p-1 text-label-md text-ink backdrop-blur"
          onPointerDown={(e) => e.stopPropagation()}
          onDoubleClick={(e) => e.stopPropagation()}
        >
          <button type="button" title="Zoom in" aria-label="Zoom in" className="size-6 rounded hover:bg-panel-hover" onClick={() => zoomAt(1.5, centre().x, centre().y)}>
            +
          </button>
          <button type="button" title="Zoom out" aria-label="Zoom out" className="size-6 rounded hover:bg-panel-hover" onClick={() => zoomAt(1 / 1.5, centre().x, centre().y)}>
            −
          </button>
          <button type="button" title="Reset zoom (double-click)" className="rounded px-1.5 hover:bg-panel-hover disabled:opacity-60" disabled={view.scale === 1} onClick={() => setView(RESET)}>
            {Math.round(view.scale * 100)} %
          </button>
        </div>
      ) : null}
    </div>
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
