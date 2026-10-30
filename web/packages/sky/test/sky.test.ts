import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'
import { altAzToFraction, eclipticPath, fractionToAltAz, starPositions, type LensConfig, type StarCatalog } from '../src/index.ts'
import { bodyPositions } from '../src/bodies.ts'

// What the Python backend computes (scripts/export_sky_fixtures.py): the reference.
interface Fixtures {
  cases: {
    when: string
    lat: number
    lon: number
    elevation_m: number
    stars: Record<string, [number, number]>
    bodies: Record<string, [number, number]>
    ecliptic: [number, number][]
  }[]
  projections: { lens: LensConfig; aspect: number; alt: number; az: number; point: [number, number] | null }[]
}

const fixtures = JSON.parse(readFileSync(new URL('./fixtures.json', import.meta.url), 'utf8')) as Fixtures
const catalog = JSON.parse(readFileSync(new URL('../src/data/stars.json', import.meta.url), 'utf8')) as StarCatalog

/** Angular distance on the sky, in degrees, between two (alt, az) directions. */
function separation([alt1, az1]: [number, number], [alt2, az2]: [number, number]): number {
  const r = Math.PI / 180
  const c =
    Math.sin(alt1 * r) * Math.sin(alt2 * r) + Math.cos(alt1 * r) * Math.cos(alt2 * r) * Math.cos((az1 - az2) * r)
  return Math.acos(Math.max(-1, Math.min(1, c))) / r
}

describe.each(fixtures.cases)('sky at $when ($lat, $lon)', (c) => {
  it('puts every catalog star where the backend does (under 0.001°)', () => {
    const p = starPositions(catalog, new Date(c.when), c.lat, c.lon, 3.5)
    expect(p.index.length).toBe(Object.keys(c.stars).length)
    p.index.forEach((i, k) => {
      const expected = c.stars[String(catalog.hr[i])]
      expect(expected, `HR ${catalog.hr[i]}`).toBeDefined()
      expect(separation([p.alt[k], p.az[k]], expected)).toBeLessThan(0.001)
    })
  })

  it('runs the ecliptic where the backend does (under 0.001°)', () => {
    const path = eclipticPath(new Date(c.when), c.lat, c.lon, 15)
    expect(path.length).toBe(c.ecliptic.length)
    path.forEach((point, i) => expect(separation(point, c.ecliptic[i])).toBeLessThan(0.001))
  })

  it('puts the Sun, Moon and planets where astropy does (under 0.05°)', () => {
    for (const body of bodyPositions(new Date(c.when), c.lat, c.lon, c.elevation_m)) {
      expect(separation([body.alt, body.az], c.bodies[body.name]), body.name).toBeLessThan(0.05)
    }
  })
})

describe('lens projection', () => {
  it('matches the backend', () => {
    for (const { lens, aspect, alt, az, point } of fixtures.projections) {
      const got = altAzToFraction(lens, aspect, alt, az)
      if (point === null) {
        expect(got).toBeNull()
        continue
      }
      expect(got).not.toBeNull()
      expect(got!.x).toBeCloseTo(point[0], 5)
      expect(got!.y).toBeCloseTo(point[1], 5)
    }
  })

  it('inverts', () => {
    for (const { lens, aspect, alt, az, point } of fixtures.projections) {
      // On the very edge of the image circle the rounded fixture may fall just outside it.
      if (point === null || 90 - alt > lens.fov_deg / 2 - 0.5) continue
      const back = fractionToAltAz(lens, aspect, point[0], point[1])
      expect(back).not.toBeNull()
      expect(separation([back!.alt, back!.az], [alt, az])).toBeLessThan(0.01)
    }
  })
})
