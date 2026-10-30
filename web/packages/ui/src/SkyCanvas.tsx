import { useEffect, useRef, useState } from 'react'
import type { LensConfig } from '@caelum/api-client'
import { drawSky, loadSkyData, type SkyData } from '@caelum/sky'

export interface SkyCanvasProps {
  lens: LensConfig
  latDeg: number
  lonDeg: number
  elevationM?: number
  /** The moment the image shows. */
  when: Date
  /** Layers switched off (see `SKY_LAYERS`). */
  hidden?: ReadonlySet<string>
}

/**
 * The sky drawn over an image, live, in the browser: stars, constellation
 * figures, planets, compass and altitude rings, worked out from the lens, the
 * observer's position and `when` — nothing is rendered or fetched per frame.
 * It fills its positioned parent (an `ImageViewer`), so it lines up with the
 * picture at any size. The star catalog and ephemeris load on first use.
 */
export function SkyCanvas({ lens, latDeg, lonDeg, elevationM = 0, when, hidden }: SkyCanvasProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const [sky, setSky] = useState<SkyData | null>(null)
  const [size, setSize] = useState<{ width: number; height: number }>({ width: 0, height: 0 })

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
    const canvas = canvasRef.current
    if (!canvas) return
    const observer = new ResizeObserver(() => {
      const dpr = window.devicePixelRatio || 1
      setSize({ width: Math.round(canvas.clientWidth * dpr), height: Math.round(canvas.clientHeight * dpr) })
    })
    observer.observe(canvas)
    return () => observer.disconnect()
  }, [])

  const whenMs = when.getTime()
  useEffect(() => {
    const canvas = canvasRef.current
    const ctx = canvas?.getContext('2d')
    if (!canvas || !ctx || !sky || size.width === 0) return
    drawSky(ctx, size.width, size.height, sky, {
      lens,
      latDeg,
      lonDeg,
      elevationM,
      when: new Date(whenMs),
      hidden,
    })
  }, [sky, size, lens, latDeg, lonDeg, elevationM, whenMs, hidden])

  return (
    <canvas
      ref={canvasRef}
      width={size.width}
      height={size.height}
      aria-hidden
      className="pointer-events-none absolute inset-0 h-full w-full"
    />
  )
}
