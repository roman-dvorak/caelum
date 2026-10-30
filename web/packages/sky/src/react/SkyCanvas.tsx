import { useEffect, useMemo, useRef, useState } from 'react'
import {
  compassPoint,
  drawSky,
  fractionToAltAz,
  loadSkyData,
  type LensConfig,
  type SkyData,
  type SkyHit,
} from '../index.ts'

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
  /** How opaque the sky is over the picture, 0 – 1 (default 1). */
  opacity?: number
  /** Show a popup with the name or sky position under the pointer. */
  interactive?: boolean
  /** Click handler, in frame fractions (the lens page uses it to pick the centre). */
  onPick?: (x: number, y: number) => void
  /** Drawn after the sky, in CSS pixels — e.g. the stars a fit matched. */
  extraDraw?: (ctx: CanvasRenderingContext2D, width: number, height: number) => void
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
  opacity = 1,
  interactive = false,
  onPick,
  extraDraw,
}: SkyCanvasProps) {
  const rootRef = useRef<HTMLDivElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const hitsRef = useRef<SkyHit[]>([])
  const [sky, setSky] = useState<SkyData | null>(null)
  const [size, setSize] = useState({ width: 0, height: 0 })
  const [tip, setTip] = useState<Tip | null>(null)

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
    () => ({ lens, latDeg, lonDeg, elevationM, when: new Date(whenMs), hidden, maxMagnitude }),
    [lens, latDeg, lonDeg, elevationM, whenMs, hidden, maxMagnitude],
  )

  useEffect(() => {
    const canvas = canvasRef.current
    const ctx = canvas?.getContext('2d')
    if (!canvas || !ctx || !sky || size.width === 0) return
    const ratio = window.devicePixelRatio || 1
    canvas.width = Math.round(size.width * ratio)
    canvas.height = Math.round(size.height * ratio)
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0)
    hitsRef.current = drawSky(ctx, size.width, size.height, sky, options)
    extraDraw?.(ctx, size.width, size.height)
  }, [sky, size, options, extraDraw])

  function onMove(event: React.PointerEvent<HTMLDivElement>) {
    const rect = rootRef.current?.getBoundingClientRect()
    if (!rect || rect.width === 0) return
    const px = event.clientX - rect.left
    const py = event.clientY - rect.top
    let best: SkyHit | null = null
    let bestDistance = HIT_RADIUS_PX
    for (const hit of hitsRef.current) {
      // Brighter objects win ties: a bright star next to a faint one is the one asked about.
      const distance = Math.hypot(hit.x - px, hit.y - py) + hit.mag * 0.4
      if (distance < bestDistance) {
        best = hit
        bestDistance = distance
      }
    }
    if (best) {
      setTip({ x: best.x, y: best.y, text: describe(best) })
      return
    }
    const altaz = fractionToAltAz(lens, rect.width / rect.height, px / rect.width, py / rect.height)
    setTip(
      altaz
        ? { x: px, y: py, text: `alt ${altaz.alt.toFixed(1)}° · az ${altaz.az.toFixed(1)}° ${compassPoint(altaz.az)}` }
        : null,
    )
  }

  function onDown(event: React.PointerEvent<HTMLDivElement>) {
    const rect = rootRef.current?.getBoundingClientRect()
    if (!onPick || !rect || rect.width === 0) return
    onPick((event.clientX - rect.left) / rect.width, (event.clientY - rect.top) / rect.height)
  }

  return (
    <div
      ref={rootRef}
      style={{
        position: 'absolute',
        inset: 0,
        pointerEvents: interactive ? 'auto' : 'none',
        cursor: onPick ? 'crosshair' : undefined,
      }}
      onPointerMove={interactive ? onMove : undefined}
      onPointerLeave={interactive ? () => setTip(null) : undefined}
      onPointerDown={interactive ? onDown : undefined}
    >
      <canvas
        ref={canvasRef}
        aria-hidden
        style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', pointerEvents: 'none', opacity }}
      />
      {tip ? (
        <div role="tooltip" style={{ ...TOOLTIP_STYLE, left: tip.x, top: tip.y + 14 }}>
          {tip.text}
        </div>
      ) : null}
    </div>
  )
}
