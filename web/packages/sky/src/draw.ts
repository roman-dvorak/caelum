import type { LensConfig } from '@caelum/api-client'
import { starPositions } from './astro.ts'
import type { SkyData } from './catalog.ts'
import { altAzToFraction } from './lens.ts'

/** The toggleable parts of the sky overlay. */
export const SKY_LAYERS = ['grid', 'constellations', 'stars', 'planets', 'compass'] as const
export type SkyLayer = (typeof SKY_LAYERS)[number]

export interface SkyDrawOptions {
  lens: LensConfig
  latDeg: number
  lonDeg: number
  elevationM?: number
  /** The moment the picture shows. */
  when: Date
  /** Layers switched off. */
  hidden?: ReadonlySet<string>
  /** Dimmest star drawn / named. */
  maxMagnitude?: number
  labelMagnitude?: number
}

const REFERENCE_WIDTH = 1024
const STAR_COLOR = '232, 241, 255'
const GRID_COLOR = '80, 200, 220'
const FIGURE_COLOR = '140, 170, 255'
const BODY_STYLE = {
  sun: { color: '255, 214, 90', radius: 7 },
  moon: { color: '220, 224, 232', radius: 6 },
  planet: { color: '232, 161, 58', radius: 4 },
} as const

/**
 * Draws the sky over the camera into `ctx` (cleared first): the same layers as
 * the backend's `sky_overlay` plugin, but worked out here from the lens, the
 * observer's position and the moment — so it follows the clock without any
 * image being rendered or sent. Sizes are relative to a 1024 px wide canvas.
 */
export function drawSky(ctx: CanvasRenderingContext2D, width: number, height: number, sky: SkyData, o: SkyDrawOptions) {
  ctx.clearRect(0, 0, width, height)
  if (width <= 0 || height <= 0) return
  const scale = width / REFERENCE_WIDTH
  const aspect = width / height
  const horizon = 90 - o.lens.fov_deg / 2
  const minAlt = Math.max(0, horizon)
  const show = (layer: SkyLayer) => !o.hidden?.has(layer)
  const project = (alt: number, az: number): [number, number] | null => {
    const p = altAzToFraction(o.lens, aspect, alt, az)
    return p === null ? null : [p.x * width, p.y * height]
  }
  const inFrame = (p: [number, number] | null): p is [number, number] =>
    p !== null && p[0] >= 0 && p[0] <= width && p[1] >= 0 && p[1] <= height

  ctx.lineCap = 'round'
  ctx.lineJoin = 'round'

  if (show('grid')) {
    ctx.strokeStyle = `rgba(${GRID_COLOR}, 0.45)`
    ctx.lineWidth = Math.max(1, scale)
    const run = (points: ([number, number] | null)[]) => {
      let open = false
      ctx.beginPath()
      for (const p of points) {
        if (p === null) {
          open = false
          continue
        }
        if (open) ctx.lineTo(p[0], p[1])
        else ctx.moveTo(p[0], p[1])
        open = true
      }
      ctx.stroke()
    }
    for (const alt of [0, 30, 60]) {
      if (alt < horizon) continue
      const points: ([number, number] | null)[] = []
      for (let az = 0; az <= 360; az += 5) points.push(project(alt, az))
      run(points)
    }
    for (const az of [0, 90, 180, 270]) {
      const points: ([number, number] | null)[] = []
      for (let alt = minAlt; alt <= 90; alt += 5) points.push(project(alt, az))
      run(points)
    }
  }

  const positions = show('stars') || show('constellations') ? starPositions(sky.stars, o.when, o.latDeg, o.lonDeg) : null

  if (positions && show('constellations')) {
    const byIndex = new Map<number, [number, number]>()
    positions.index.forEach((starIndex, k) => {
      if (positions.alt[k] < minAlt) return
      const p = project(positions.alt[k], positions.az[k])
      if (inFrame(p)) byIndex.set(starIndex, p)
    })
    ctx.strokeStyle = `rgba(${FIGURE_COLOR}, 0.55)`
    ctx.lineWidth = Math.max(1, scale)
    ctx.beginPath()
    for (const [a, b] of sky.figures) {
      const ia = sky.indexOfHr.get(a)
      const ib = sky.indexOfHr.get(b)
      const pa = ia === undefined ? undefined : byIndex.get(ia)
      const pb = ib === undefined ? undefined : byIndex.get(ib)
      if (!pa || !pb) continue
      ctx.moveTo(pa[0], pa[1])
      ctx.lineTo(pb[0], pb[1])
    }
    ctx.stroke()
  }

  const labelFont = `${Math.max(9, Math.round(10 * scale))}px ui-monospace, "DejaVu Sans Mono", monospace`
  if (positions && show('stars')) {
    const maxMag = o.maxMagnitude ?? 4.5
    const labelMag = o.labelMagnitude ?? 2.0
    ctx.lineWidth = Math.max(1, scale)
    ctx.font = labelFont
    ctx.textBaseline = 'middle'
    positions.index.forEach((starIndex, k) => {
      const mag = sky.stars.mag[starIndex]
      if (mag > maxMag || positions.alt[k] < minAlt) return
      const p = project(positions.alt[k], positions.az[k])
      if (!inFrame(p)) return
      // An outline ring rather than a filled dot: it marks the star without
      // hiding it, so it can be compared with the real one underneath.
      const r = Math.max(1, (1.2 + (5 - mag) * 0.55) * scale) + 2 * scale
      ctx.strokeStyle = `rgba(${STAR_COLOR}, 0.67)`
      ctx.beginPath()
      ctx.arc(p[0], p[1], r, 0, Math.PI * 2)
      ctx.stroke()
      const name = sky.stars.name[starIndex]
      if (mag <= labelMag && name) {
        ctx.fillStyle = `rgba(${STAR_COLOR}, 0.92)`
        ctx.fillText(name, p[0] + 9 * scale, p[1])
      }
    })
  }

  if (show('planets')) {
    ctx.font = labelFont
    ctx.textBaseline = 'middle'
    for (const body of sky.bodyPositions(o.when, o.latDeg, o.lonDeg, o.elevationM ?? 0)) {
      if (body.alt < minAlt) continue
      const p = project(body.alt, body.az)
      if (!inFrame(p)) continue
      const style = BODY_STYLE[body.kind]
      const r = style.radius * scale
      ctx.fillStyle = `rgba(${style.color}, 0.27)`
      ctx.strokeStyle = `rgb(${style.color})`
      ctx.lineWidth = Math.max(1, 2 * scale)
      ctx.beginPath()
      ctx.arc(p[0], p[1], r, 0, Math.PI * 2)
      ctx.fill()
      ctx.stroke()
      ctx.fillStyle = `rgb(${style.color})`
      ctx.fillText(body.name, p[0] + r + 3 * scale, p[1])
    }
  }

  if (show('compass')) {
    ctx.font = `bold ${Math.max(9, Math.round(16 * scale))}px ui-monospace, "DejaVu Sans Mono", monospace`
    ctx.textAlign = 'center'
    ctx.textBaseline = 'middle'
    for (const [letter, az] of [['N', 0], ['E', 90], ['S', 180], ['W', 270]] as const) {
      const p = project(minAlt + 6, az)
      if (p === null) continue
      const pad = 3 * scale
      const w = ctx.measureText(letter).width + 2 * pad
      const h = Math.max(9, Math.round(16 * scale)) + 2 * pad
      ctx.fillStyle = 'rgba(8, 10, 14, 0.7)'
      ctx.beginPath()
      ctx.roundRect(p[0] - w / 2, p[1] - h / 2, w, h, 3 * scale)
      ctx.fill()
      ctx.fillStyle = letter === 'N' ? 'rgb(255, 110, 100)' : 'rgb(229, 229, 229)'
      ctx.fillText(letter, p[0], p[1] + scale)
    }
    ctx.textAlign = 'start'
  }
}
