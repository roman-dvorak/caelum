import type { LensConfig } from './types.ts'

/**
 * The lens model, in the browser — the same maths as the backend's
 * `caelum.derivatives.projection` (the tests there pin the numbers). It is
 * here so the calibration page can move the sky around instantly while a
 * value is dragged, without asking the server for every step.
 *
 * Positions are fractions of the frame width/height; `radius` is a fraction
 * of the frame's *shorter* side, so `aspect` (width / height) is needed to
 * turn it into the right pixels on a 4:3 frame.
 */

type Radial = (theta: number) => number

const RADIAL: Record<LensConfig['projection'], Radial> = {
  equidistant_fisheye: (t) => t,
  equisolid_fisheye: (t) => 2 * Math.sin(t / 2),
  stereographic_fisheye: (t) => 2 * Math.tan(t / 2),
  orthographic_fisheye: (t) => Math.sin(t),
}

const rad = (deg: number) => (deg * Math.PI) / 180
const deg = (r: number) => (r * 180) / Math.PI

function axisScales(aspect: number): [number, number] {
  const a = aspect > 0 ? aspect : 1
  return a >= 1 ? [1 / a, 1] : [1, a]
}

export interface Point {
  x: number
  y: number
}

/** Frame fraction of a sky direction, or null when the lens cannot see it. */
export function altAzToFraction(lens: LensConfig, aspect: number, altDeg: number, azDeg: number): Point | null {
  const thetaMax = rad(lens.fov_deg) / 2
  const theta = rad(90 - altDeg)
  if (theta > thetaMax + 1e-9) return null
  const f = RADIAL[lens.projection] ?? RADIAL.equidistant_fisheye
  const r = (lens.radius * f(theta)) / f(thetaMax)
  let phi = rad(azDeg + lens.azimuth_offset_deg)
  if (lens.mirror) phi = -phi
  const [sx, sy] = axisScales(aspect)
  return { x: lens.center_x + r * Math.sin(phi) * sx, y: lens.center_y - r * Math.cos(phi) * sy }
}

/** What the pixel at a frame fraction is looking at, or null outside the image circle. */
export function fractionToAltAz(
  lens: LensConfig,
  aspect: number,
  x: number,
  y: number,
): { alt: number; az: number } | null {
  if (lens.radius <= 0) return null
  const [sx, sy] = axisScales(aspect)
  const dx = (x - lens.center_x) / sx
  const dy = (lens.center_y - y) / sy
  const r = Math.hypot(dx, dy)
  if (r > lens.radius) return null
  let phi = Math.atan2(dx, dy)
  if (lens.mirror) phi = -phi
  const az = (((deg(phi) - lens.azimuth_offset_deg) % 360) + 360) % 360
  const thetaMax = rad(lens.fov_deg) / 2
  const f = RADIAL[lens.projection] ?? RADIAL.equidistant_fisheye
  const target = (r / lens.radius) * f(thetaMax)
  let theta: number
  switch (lens.projection) {
    case 'equisolid_fisheye':
      theta = 2 * Math.asin(Math.min(1, target / 2))
      break
    case 'stereographic_fisheye':
      theta = 2 * Math.atan(target / 2)
      break
    case 'orthographic_fisheye':
      theta = Math.asin(Math.min(1, target))
      break
    default:
      theta = target
  }
  return { alt: 90 - deg(theta), az }
}

const COMPASS = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE', 'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW']

export function compassPoint(azDeg: number): string {
  return COMPASS[Math.round(azDeg / 22.5) % 16]
}
