import { useContext, useEffect, useMemo, useRef, useState } from 'react'
import {
  compassPoint,
  drawSky,
  fractionToAltAz,
  loadSkyData,
  type LensConfig,
  type SkyData,
  type SkyHit,
} from '../index.ts'
import { SkyDetailContext } from './detail.ts'

const HIT_RADIUS_PX = 14


export interface SkyCanvasProps {
  lens: LensConfig
  latDeg: number
  lonDeg: number
  elevationM?: number
  /** The moment the image shows. */
  when: Date
  /** Layers switched off (see `SKY_LAYERS`). */
  hidden?: ReadonlySet<string>
  /** Dimmest star drawn. */
  maxMagnitude?: number
  /** Size of the star and body rings relative to the default (1). */
  symbolScale?: number
  /** How opaque the sky is over the picture, 0 – 1 (default 1). */
  opacity?: number
  /** Show a popup with the name or sky position under the pointer. */
  interactive?: boolean
  /** Click handler, in frame fractions (the lens page uses it to pick the centre). */
  onPick?: (x: number, y: number) => void
  /** Overrides `SkyDetailContext`: draw this many times finer than the box. */
  detail?: number
  /** Drawn after the sky, in CSS pixels of the (detail-scaled) canvas — e.g. the stars a fit matched. */
  extraDraw?: (ctx: CanvasRenderingContext2D, width: number, height: number) => void
  /**
   * Lets a star's ring be grabbed and dragged onto the real star in the picture
   * (a line follows the pointer). Called on release with the star and where it
   * was dropped, in frame fractions. Ignored while `onPick` is set.
   */
  onStarDrag?: (hit: SkyHit, x: number, y: number) => void
}

// Inline styles, so the component looks right in any app — with or without
// Tailwind or the caelum design system. Colours follow `--sky-tooltip-*` custom
// properties when the host app defines them.
const TOOLTIP_STYLE: React.CSSProperties = {
  position: 'absolute',
  zIndex: 10,
  transform: 'translateX(-50%)',
  whiteSpace: 'nowrap',
  pointerEvents: 'none',
  padding: '4px 8px',
  borderRadius: 6,
  fontSize: 12,
  lineHeight: 1.4,
  background: 'var(--sky-tooltip-bg, #141a24)',
  color: 'var(--sky-tooltip-fg, #e5e5e5)',
  border: '1px solid var(--sky-tooltip-border, #2b3446)',
  boxShadow: '0 2px 8px rgba(0, 0, 0, 0.5)',
}

interface Tip {
  x: number
  y: number
  /** On-screen pixels per layout pixel of the box (the host's zoom): the label is drawn at its natural size. */
  scale: number
  text: string
}

function describe(hit: SkyHit): string {
  const where = `alt ${hit.alt.toFixed(1)}° · az ${hit.az.toFixed(0)}° ${compassPoint(hit.az)}`
  return hit.kind === 'star' ? `${hit.name} · mag ${hit.mag.toFixed(1)} · ${where}` : `${hit.name} · ${where}`
}

/**
 * The sky drawn over an image, live, in the browser — the very thing the lens
 * calibration page shows: lens outline, horizon and altitude rings,
 * constellations, stars, planets and compass, worked out from the lens, the
 * observer's position and `when`. Nothing is rendered or fetched per frame.
 * It fills its positioned parent (an `ImageViewer`) so it lines up with the
 * picture at any size; with `interactive` it names what the pointer is on.
 * The star catalog and ephemeris load on first use.
 */
export function SkyCanvas({
  lens,
  latDeg,
  lonDeg,
  elevationM = 0,
  when,
  hidden,
  maxMagnitude,
  symbolScale,
  opacity = 1,
  interactive = false,
  onPick,
  extraDraw,
  onStarDrag,
  detail: detailProp,
}: SkyCanvasProps) {
  const contextDetail = useContext(SkyDetailContext)
  const detail = Math.max(1, detailProp ?? contextDetail)
  const rootRef = useRef<HTMLDivElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const hitsRef = useRef<SkyHit[]>([])
  const [sky, setSky] = useState<SkyData | null>(null)
  const [size, setSize] = useState({ width: 0, height: 0 })
  const [tip, setTip] = useState<Tip | null>(null)
  // A star being dragged: the star (in drawing units) and where the pointer is (layout pixels of the box).
  const [drag, setDrag] = useState<{ hit: SkyHit; x: number; y: number; scale: number } | null>(null)

  useEffect(() => {
    let disposed = false
    loadSkyData().then(
      (data) => {
        if (!disposed) setSky(data)
      },
      () => {
        /* chunk failed to load: no sky, the image itself is unaffected */
      },
    )
    return () => {
      disposed = true
    }
  }, [])

  useEffect(() => {
    const root = rootRef.current
    if (!root) return
    const observer = new ResizeObserver(() => setSize({ width: root.clientWidth, height: root.clientHeight }))
    observer.observe(root)
    return () => observer.disconnect()
  }, [])

  const whenMs = when.getTime()
  const options = useMemo(
    () => ({ lens, latDeg, lonDeg, elevationM, when: new Date(whenMs), hidden, maxMagnitude, symbolScale }),
    [lens, latDeg, lonDeg, elevationM, whenMs, hidden, maxMagnitude, symbolScale],
  )

  useEffect(() => {
    const canvas = canvasRef.current
    const ctx = canvas?.getContext('2d')
    if (!canvas || !ctx || !sky || size.width === 0) return
    const ratio = window.devicePixelRatio || 1
    const width = size.width * detail
    const height = size.height * detail
    canvas.width = Math.round(width * ratio)
    canvas.height = Math.round(height * ratio)
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0)
    hitsRef.current = drawSky(ctx, width, height, sky, options)
    extraDraw?.(ctx, width, height)
  }, [sky, size, options, extraDraw, detail])

  /**
   * The pointer in the canvas' own drawing units. The box may be scaled or
   * panned by the host (CSS transform): its on-screen rectangle then differs
   * from its layout size, and positions have to be converted back.
   */
  function locate(event: React.PointerEvent<HTMLDivElement>) {
    const root = rootRef.current
    const rect = root?.getBoundingClientRect()
    if (!root || !rect || rect.width === 0 || root.clientWidth === 0) return null
    const screenPerLayout = rect.width / root.clientWidth
    const lx = (event.clientX - rect.left) / screenPerLayout
    const ly = (event.clientY - rect.top) / screenPerLayout
    return { rect, screenPerLayout, lx, ly, dx: lx * detail, dy: ly * detail, screenPerDraw: screenPerLayout / detail }
  }

  function hitAt(px: number, py: number, screenPerDraw: number): SkyHit | null {
    let best: SkyHit | null = null
    let bestDistance = HIT_RADIUS_PX
    for (const hit of hitsRef.current) {
      // Brighter objects win ties: a bright star next to a faint one is the one asked about.
      const distance = Math.hypot(hit.x - px, hit.y - py) * screenPerDraw + hit.mag * 0.4
      if (distance < bestDistance) {
        best = hit
        bestDistance = distance
      }
    }
    return best
  }

  function onMove(event: React.PointerEvent<HTMLDivElement>) {
    const at = locate(event)
    if (!at) return
    if (drag) {
      setDrag({ ...drag, x: at.lx, y: at.ly, scale: at.screenPerLayout })
      setTip(null)
      return
    }
    // Positions in `tip` are layout pixels of the box; `scale` undoes the host's zoom for the label.
    const best = hitAt(at.dx, at.dy, at.screenPerDraw)
    if (best) {
      setTip({ x: best.x / detail, y: best.y / detail, scale: at.screenPerLayout, text: describe(best) })
      return
    }
    const altaz = fractionToAltAz(lens, at.rect.width / at.rect.height, (event.clientX - at.rect.left) / at.rect.width, (event.clientY - at.rect.top) / at.rect.height)
    setTip(
      altaz
        ? { x: at.lx, y: at.ly, scale: at.screenPerLayout, text: `alt ${altaz.alt.toFixed(1)}° · az ${altaz.az.toFixed(1)}° ${compassPoint(altaz.az)}` }
        : null,
    )
  }

  function onDown(event: React.PointerEvent<HTMLDivElement>) {
    const at = locate(event)
    if (!at) return
    const fx = (event.clientX - at.rect.left) / at.rect.width
    const fy = (event.clientY - at.rect.top) / at.rect.height
    if (onPick) {
      event.stopPropagation() // a click here is a pick, not the start of a pan
      onPick(fx, fy)
      return
    }
    if (!onStarDrag) return
    const hit = hitAt(at.dx, at.dy, at.screenPerDraw)
    if (!hit) return
    event.stopPropagation()
    event.currentTarget.setPointerCapture(event.pointerId)
    setDrag({ hit, x: at.lx, y: at.ly, scale: at.screenPerLayout })
  }

  function onUp(event: React.PointerEvent<HTMLDivElement>) {
    const at = locate(event)
    if (!drag || !at) return
    const { hit } = drag
    setDrag(null)
    const x = (event.clientX - at.rect.left) / at.rect.width
    const y = (event.clientY - at.rect.top) / at.rect.height
    // Let go on the ring itself (a click) is not a move.
    if (Math.hypot(at.dx - hit.x, at.dy - hit.y) * at.screenPerDraw < 3) return
    if (x >= 0 && x <= 1 && y >= 0 && y <= 1) onStarDrag?.(hit, x, y)
  }

  return (
    <div
      ref={rootRef}
      style={{
        position: 'absolute',
        inset: 0,
        pointerEvents: interactive ? 'auto' : 'none',
        cursor: onPick ? 'crosshair' : drag ? 'grabbing' : undefined,
        touchAction: onStarDrag ? 'none' : undefined,
      }}
      onPointerMove={interactive ? onMove : undefined}
      onPointerLeave={interactive ? () => setTip(null) : undefined}
      onPointerDown={interactive ? onDown : undefined}
      onPointerUp={interactive ? onUp : undefined}
      onPointerCancel={interactive ? () => setDrag(null) : undefined}
    >
      <canvas
        ref={canvasRef}
        aria-hidden
        style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', pointerEvents: 'none', opacity }}
      />
      {drag ? (
        <svg aria-hidden style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', pointerEvents: 'none' }}>
          <line x1={drag.hit.x / detail} y1={drag.hit.y / detail} x2={drag.x} y2={drag.y} stroke="#7CFC9A" strokeWidth={1.5 / drag.scale} />
          <circle cx={drag.x} cy={drag.y} r={5 / drag.scale} fill="none" stroke="#7CFC9A" strokeWidth={1.5 / drag.scale} />
        </svg>
      ) : null}
      {tip ? (
        <div
          role="tooltip"
          style={{
            ...TOOLTIP_STYLE,
            left: tip.x,
            top: tip.y + 14 / tip.scale,
            transform: `translateX(-50%) scale(${1 / tip.scale})`,
            transformOrigin: 'top center',
          }}
        >
          {tip.text}
        </div>
      ) : null}
    </div>
  )
}
