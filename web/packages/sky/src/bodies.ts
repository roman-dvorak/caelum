import * as Astronomy from 'astronomy-engine'

export interface SkyBody {
  kind: 'sun' | 'moon' | 'planet'
  name: string
  alt: number
  az: number
}

const BODIES: [Astronomy.Body, string, SkyBody['kind']][] = [
  [Astronomy.Body.Sun, 'Sun', 'sun'],
  [Astronomy.Body.Moon, 'Moon', 'moon'],
  [Astronomy.Body.Mercury, 'Mercury', 'planet'],
  [Astronomy.Body.Venus, 'Venus', 'planet'],
  [Astronomy.Body.Mars, 'Mars', 'planet'],
  [Astronomy.Body.Jupiter, 'Jupiter', 'planet'],
  [Astronomy.Body.Saturn, 'Saturn', 'planet'],
]

/** Sun, Moon and the naked-eye planets over an observer (topocentric, no refraction). */
export function bodyPositions(when: Date, latDeg: number, lonDeg: number, elevationM = 0): SkyBody[] {
  const observer = new Astronomy.Observer(latDeg, lonDeg, elevationM)
  return BODIES.map(([body, name, kind]) => {
    const eq = Astronomy.Equator(body, when, observer, true, true)
    const hor = Astronomy.Horizon(when, observer, eq.ra, eq.dec)
    return { kind, name, alt: hor.altitude, az: hor.azimuth }
  })
}
