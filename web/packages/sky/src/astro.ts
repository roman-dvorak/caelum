/**
 * Where the catalog stars are over an observer at a given moment — the same
 * plain maths as the backend's `caelum.sky.positions` (proper motion, IAU 1976
 * precession from J2000 to the date, mean sidereal time): a few arcseconds,
 * under a pixel on a fisheye frame, and no ephemeris needed. Nutation,
 * aberration and refraction are left out.
 */

const J2000_JD = 2451545.0
const ARCSEC = Math.PI / (180 * 3600)
const rad = (deg: number) => (deg * Math.PI) / 180
const deg = (r: number) => (r * 180) / Math.PI

export interface StarCatalog {
  hr: number[]
  ra: number[] // degrees, J2000
  dec: number[]
  mag: number[]
  pmRa: number[] // mas/yr, includes cos(dec)
  pmDec: number[]
  name: string[]
}

export interface StarPositions {
  /** Index into the catalog arrays. */
  index: number[]
  alt: number[]
  az: number[]
}

export function julianDate(when: Date): number {
  return when.getTime() / 86_400_000 + 2_440_587.5
}

/** Meeus 21.2/21.4: mean equatorial J2000 -> mean equator of date (`t` in Julian centuries). */
function precessFromJ2000(ra: number, dec: number, t: number): [number, number] {
  const zeta = (2306.2181 * t + 0.30188 * t * t + 0.017998 * t ** 3) * ARCSEC
  const z = (2306.2181 * t + 1.09468 * t * t + 0.018203 * t ** 3) * ARCSEC
  const theta = (2004.3109 * t - 0.42665 * t * t - 0.041833 * t ** 3) * ARCSEC
  const a = Math.cos(dec) * Math.sin(ra + zeta)
  const b = Math.cos(theta) * Math.cos(dec) * Math.cos(ra + zeta) - Math.sin(theta) * Math.sin(dec)
  const c = Math.sin(theta) * Math.cos(dec) * Math.cos(ra + zeta) + Math.cos(theta) * Math.sin(dec)
  return [Math.atan2(a, b) + z, Math.asin(Math.max(-1, Math.min(1, c)))]
}

/** (alt, az) in degrees, azimuth from north through east. */
export function horizontal(ra: number, dec: number, jd: number, latDeg: number, lonDeg: number): [number, number] {
  const t = (jd - J2000_JD) / 36525
  const gmst = 280.46061837 + 360.98564736629 * (jd - J2000_JD) + 0.000387933 * t * t - t ** 3 / 38_710_000
  const hourAngle = rad((((gmst + lonDeg) % 360) + 360) % 360) - ra
  const lat = rad(latDeg)
  const sinAlt = Math.sin(lat) * Math.sin(dec) + Math.cos(lat) * Math.cos(dec) * Math.cos(hourAngle)
  const alt = Math.asin(Math.max(-1, Math.min(1, sinAlt)))
  const az = Math.atan2(
    -Math.cos(dec) * Math.sin(hourAngle),
    Math.sin(dec) * Math.cos(lat) - Math.cos(dec) * Math.cos(hourAngle) * Math.sin(lat),
  )
  return [deg(alt), (deg(az) + 360) % 360]
}

/** Alt/az of every catalog star brighter than `maxMag` (above or below the horizon). */
export function starPositions(
  catalog: StarCatalog,
  when: Date,
  latDeg: number,
  lonDeg: number,
  maxMag = 6,
): StarPositions {
  const jd = julianDate(when)
  const years = (jd - J2000_JD) / 365.25
  const out: StarPositions = { index: [], alt: [], az: [] }
  for (let i = 0; i < catalog.hr.length; i++) {
    if (catalog.mag[i] > maxMag) continue
    const dec0 = rad(catalog.dec[i])
    const ra0 = rad(catalog.ra[i])
    const dec = dec0 + (catalog.pmDec[i] / 1000) * years * ARCSEC
    const ra = ra0 + ((catalog.pmRa[i] / 1000) * years * ARCSEC) / Math.max(Math.cos(dec0), 1e-6)
    const [raDate, decDate] = precessFromJ2000(ra, dec, years / 100)
    const [alt, az] = horizontal(raDate, decDate, jd, latDeg, lonDeg)
    out.index.push(i)
    out.alt.push(alt)
    out.az.push(az)
  }
  return out
}

/**
 * Alt/az of points along the ecliptic (ecliptic latitude 0, longitudes every
 * `stepDeg`; mean obliquity of the date) — the line the Sun and the planets keep to.
 */
export function eclipticPath(when: Date, latDeg: number, lonDeg: number, stepDeg = 5): [number, number][] {
  const jd = julianDate(when)
  const t = (jd - J2000_JD) / 36525
  const eps = rad(23.439291 - 0.0130042 * t)
  const out: [number, number][] = []
  for (let lambda = 0; lambda <= 360 + stepDeg / 2; lambda += stepDeg) {
    const l = rad(lambda)
    const ra = Math.atan2(Math.sin(l) * Math.cos(eps), Math.cos(l))
    const dec = Math.asin(Math.sin(l) * Math.sin(eps))
    out.push(horizontal(ra, dec, jd, latDeg, lonDeg))
  }
  return out
}
