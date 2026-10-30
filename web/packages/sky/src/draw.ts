import type { LensConfig } from './types.ts'
import { eclipticPath, starPositions } from './astro.ts'
import type { SkyData } from './catalog.ts'
import { altAzToFraction } from './lens.ts'

/** The toggleable parts of the sky overlay. */
export const SKY_LAYERS = ['outline', 'grid', 'ecliptic', 'constellations', 'stars', 'planets', 'compass'] as const
export type SkyLayer = (typeof SKY_LAYERS)[number]

export const DEFAULT_MAX_MAGNITUDE = 3.5
/** Stars up to this magnitude also get their name. */
export const LABEL_MAGNITUDE = 1.6

export interface SkyDrawOptions {
  lens: LensConfig
  latDeg: number
  lonDeg: number
  elevationM?: number
  /** The moment the picture shows. */
  when: Date
  /** Layers switched off. */
  hidden?: ReadonlySet<string>
  /** Dimmest star drawn. */
  maxMagnitude?: number
}

/** A star or body that was drawn, with its place on the canvas (CSS pixels). */
export interface SkyHit {
  kind: 'star' | 'sun' | 'moon' | 'planet'
  name: string
  mag: number
  alt: number
  az: number
  x: number
  y: number
}

const OUTLINE_COLOR = '#f6be64'
const GRID_COLOR = '#50c8dc'
const ECLIPTIC_COLOR = '#f0d060'
const STAR_COLOR = '#e8f1ff'
const FIGURE_COLOR = '#8caaff'
const BODY_COLOR = { sun: '#ffd65a', moon: '#dce0e8', planet: '#e8a13a' } as const
const MONO = 'ui-monospace, "DejaVu Sans Mono", monospace'

/**
 * Draws the sky over the camera into `ctx`, in CSS pixels (the caller sets
 * the device-pixel transform): the image circle and optical centre, altitude
 * rings and meridians, constellation figures, stars, Sun/Moon/planets and the
 * compass — worked out here from the lens, the observer's position and the
 * moment, so it follows the clock without any image being rendered or sent.
 * The lens calibration page draws with this same function. Returns what it
 * drew, for pointer hit-testing.
 */
export function drawSky(
  ctx: CanvasRenderingContext2D,
  width: number,
  height: number,
  sky: SkyData,
  o: SkyDrawOptions,
): SkyHit[] {
  ctx.clearRect(0, 0, width, height)
  const hits: SkyHit[] = []
  if (width <= 0 || height <= 0) return hits
  // Sizes were designed for a ~800 px wide view; small thumbnails shrink them.
  const k = Math.min(1, Math.max(0.45, width / 800))
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

  if (show('outline')) {
    // The image circle and the optical centre.
    const cx = o.lens.center_x * width
    const cy = o.lens.center_y * height
    ctx.lineWidth = 1.5 * k
    ctx.strokeStyle = OUTLINE_COLOR
    ctx.beginPath()
    ctx.arc(cx, cy, o.lens.radius * Math.min(width, height), 0, Math.PI * 2)
    ctx.stroke()
    ctx.beginPath()
    ctx.moveTo(cx - 10 * k, cy)
    ctx.lineTo(cx + 10 * k, cy)
    ctx.moveTo(cx, cy - 10 * k)
    ctx.lineTo(cx, cy + 10 * k)
    ctx.stroke()
  }

  if (show('grid')) {
    ctx.strokeStyle = GRID_COLOR
    ctx.globalAlpha = 0.6
    ctx.lineWidth = Math.max(1, k)
    const line = (points: ([number, number] | null)[]) => {
      ctx.beginPath()
      let pen = false
      for (const p of points) {
        if (!p) {
          pen = false
          continue
        }
        if (pen) ctx.lineTo(p[0], p[1])
        else ctx.moveTo(p[0], p[1])
        pen = true
      }
      ctx.stroke()
    }
    // 0° is the horizon; with a lens that sees less than 180° it is off the image.
    for (const alt of [0, 30, 60]) {
      if (alt < horizon) continue
      line(Array.from({ length: 73 }, (_, i) => project(alt, i * 5)))
    }
    for (const az of [0, 90, 180, 270]) {
      line(Array.from({ length: 19 }, (_, i) => project(Math.min(90, minAlt + i * 5), az)))
    }
    ctx.globalAlpha = 1
  }

  if (show('ecliptic')) {
    // The Sun's path: dashed, with its name where it is highest in the picture.
    ctx.strokeStyle = ECLIPTIC_COLOR
    ctx.globalAlpha = 0.75
    ctx.lineWidth = Math.max(1, 1.5 * k)
    ctx.setLineDash([6 * k, 5 * k])
    let pen = false
    let top: [number, number] | null = null
    let topAlt = -90
    ctx.beginPath()
    for (const [alt, az] of eclipticPath(o.when, o.latDeg, o.lonDeg, 2)) {
      const p = alt >= minAlt ? project(alt, az) : null
      if (!inFrame(p)) {
        pen = false
        continue
      }
      if (pen) ctx.lineTo(p[0], p[1])
      else ctx.moveTo(p[0], p[1])
      pen = true
      if (alt > topAlt) {
        topAlt = alt
        top = p
      }
    }
    ctx.stroke()
    ctx.setLineDash([])
    ctx.globalAlpha = 1
    if (top) {
      ctx.font = `${Math.max(9, Math.round(11 * k))}px ${MONO}`
      ctx.textAlign = 'left'
      ctx.textBaseline = 'bottom'
      ctx.fillStyle = ECLIPTIC_COLOR
      ctx.fillText('ecliptic', top[0] + 6 * k, top[1] - 4 * k)
    }
  }

  const positions = show('stars') || show('constellations') ? starPositions(sky.stars, o.when, o.latDeg, o.lonDeg) : null

  if (positions && show('constellations')) {
    const byIndex = new Map<number, [number, number]>()
    positions.index.forEach((starIndex, i) => {
      if (positions.alt[i] < minAlt) return
      const p = project(positions.alt[i], positions.az[i])
      if (inFrame(p)) byIndex.set(starIndex, p)
    })
    ctx.strokeStyle = FIGURE_COLOR
    ctx.globalAlpha = 0.55
    ctx.lineWidth = Math.max(1, k)
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
    ctx.globalAlpha = 1
  }

  const label = (text: string, x: number, y: number, color: string) => {
    ctx.fillStyle = color
    ctx.font = `${Math.max(9, Math.round(11 * k))}px ${MONO}`
    ctx.textAlign = 'left'
    ctx.textBaseline = 'middle'
    ctx.fillText(text, x, y)
  }

  if (positions && show('stars')) {
    const maxMag = o.maxMagnitude ?? DEFAULT_MAX_MAGNITUDE
    ctx.strokeStyle = STAR_COLOR
    ctx.lineWidth = Math.max(1, k)
    positions.index.forEach((starIndex, i) => {
      const mag = sky.stars.mag[starIndex]
      if (mag > maxMag || positions.alt[i] < minAlt) return
      const p = project(positions.alt[i], positions.az[i])
      if (!inFrame(p)) return
      // A ring rather than a dot: it marks the star without hiding it, so it
      // can be compared with the real one underneath.
      const size = Math.max(3, 3 + (4.5 - mag) * 1.6) * k
      ctx.globalAlpha = 0.85
      ctx.beginPath()
      ctx.arc(p[0], p[1], size, 0, Math.PI * 2)
      ctx.stroke()
      ctx.globalAlpha = 1
      const name = sky.stars.name[starIndex]
      if (mag <= LABEL_MAGNITUDE && name) label(name, p[0] + size + 3 * k, p[1], 'rgba(232,241,255,0.95)')
      hits.push({ kind: 'star', name: name || `HR ${sky.stars.hr[starIndex]}`, mag, alt: positions.alt[i], az: positions.az[i], x: p[0], y: p[1] })
    })
  }

  if (show('planets')) {
    for (const body of sky.bodyPositions(o.when, o.latDeg, o.lonDeg, o.elevationM ?? 0)) {
      if (body.alt < minAlt) continue
      const p = project(body.alt, body.az)
      if (!inFrame(p)) continue
      ctx.strokeStyle = BODY_COLOR[body.kind]
      ctx.lineWidth = 2 * k
      ctx.beginPath()
      ctx.arc(p[0], p[1], (body.kind === 'planet' ? 5 : 8) * k, 0, Math.PI * 2)
      ctx.stroke()
      label(body.name, p[0] + 12 * k, p[1], BODY_COLOR[body.kind])
      hits.push({ kind: body.kind, name: body.name, mag: body.kind === 'planet' ? 0 : -10, alt: body.alt, az: body.az, x: p[0], y: p[1] })
    }
  }

  if (show('compass')) {
    ctx.font = `bold ${Math.max(10, Math.round(15 * k))}px ${MONO}`
    ctx.textAlign = 'center'
    ctx.textBaseline = 'middle'
    const half = 10 * k
    for (const [letter, az] of [['N', 0], ['E', 90], ['S', 180], ['W', 270]] as const) {
      const p = project(minAlt + 7, az)
      if (!p) continue
      ctx.fillStyle = 'rgba(8,10,14,0.7)'
      ctx.fillRect(p[0] - half, p[1] - half, 2 * half, 2 * half)
      ctx.fillStyle = letter === 'N' ? '#ff6e64' : '#e5e5e5'
      ctx.fillText(letter, p[0], p[1])
    }
  }
  return hits
}
