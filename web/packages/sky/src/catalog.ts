import type { StarCatalog } from './astro.ts'
import type { SkyBody } from './bodies.ts'

/** Everything needed to draw the sky, loaded on first use (it is ~80 kB
 * gzipped plus the planetary ephemeris, which the rest of the UI never needs). */
export interface SkyData {
  stars: StarCatalog
  /** Constellation figure segments as pairs of catalog `hr` numbers. */
  figures: [number, number][]
  /** catalog `hr` -> index into `stars` arrays. */
  indexOfHr: Map<number, number>
  bodyPositions: (when: Date, latDeg: number, lonDeg: number, elevationM?: number) => SkyBody[]
}

let loading: Promise<SkyData> | null = null

export function loadSkyData(): Promise<SkyData> {
  loading ??= (async () => {
    const [stars, figures, bodies] = await Promise.all([
      import('./data/stars.json'),
      import('./data/constellations.json'),
      import('./bodies.ts'),
    ])
    const catalog = stars.default as StarCatalog
    return {
      stars: catalog,
      figures: figures.default as [number, number][],
      indexOfHr: new Map(catalog.hr.map((hr, i) => [hr, i])),
      bodyPositions: bodies.bodyPositions,
    }
  })().catch((error: unknown) => {
    loading = null // a failed chunk load may be retried
    throw error
  })
  return loading
}
