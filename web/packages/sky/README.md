# @roman-dvorak/caelum-sky

Draws the night sky over a fisheye allsky camera picture, in the browser: the lens outline,
the horizon and altitude rings, constellation lines, stars, the Sun, Moon and planets, and the
compass — worked out from the lens calibration, the observer's position and the moment, so
nothing has to be rendered by the camera. It is what the caelum Dashboard and Lens page draw,
and what the Caelum Viewer can use for the same picture.

## What is in it

Two entry points, ESM only, with TypeScript types:

**`@roman-dvorak/caelum-sky`** — the framework-free core
| Export | What it does |
| --- | --- |
| `loadSkyData()` | Loads (once, lazily) the star catalog, constellation figures and the planetary ephemeris → `SkyData`. |
| `drawSky(ctx, width, height, sky, options)` | Draws everything into a 2D canvas context in CSS pixels, returns what it drew (`SkyHit[]`: name, magnitude, alt/az, canvas position) for hit-testing. |
| `SKY_LAYERS` | The parts `drawSky` can draw, each switchable through `options.hidden`: `outline`, `grid`, `constellations`, `stars`, `planets`, `compass`. |
| `starPositions(catalog, when, lat, lon, maxMag)` | Alt/az of catalog stars (proper motion, precession, sidereal time). |
| `altAzToFraction(lens, aspect, alt, az)` / `fractionToAltAz(...)` | The fisheye lens model (equidistant, equisolid, stereographic, orthographic; centre, radius, field of view, north offset, mirror): sky direction ⇄ position in the frame as fractions of its width/height. |
| `compassPoint(az)` | `"NNE"`-style name of an azimuth. |
| types | `LensConfig`, `LensProjection`, `SkyData`, `StarCatalog`, `SkyDrawOptions`, `SkyHit`, `SkyLayer`. |

**`@roman-dvorak/caelum-sky/react`** — React 19 bindings (`react` is an optional peer dependency)
| Export | What it does |
| --- | --- |
| `<SkyCanvas lens latDeg lonDeg when … />` | A canvas that fills its positioned parent (put it over an `<img>` of the same aspect ratio), redraws on resize, loads the data on first mount. With `interactive` it shows a popup naming the star/planet under the pointer, or the altitude/azimuth of the point; `onPick` gives clicks as frame fractions; `extraDraw` draws more on top. Styled with inline styles only — no Tailwind or CSS needed; the popup follows `--sky-tooltip-bg/-fg/-border` if set. |
| `useSkySettings()` | Which layers are off and how faint a star is drawn, kept in `localStorage` (`caelum.skyView`). |

What it contains as data (loaded as separate chunks, only when `loadSkyData()` runs):
the Yale Bright Star Catalogue, 5080 stars brighter than magnitude 6 (~210 kB, ~80 kB gzipped),
the 88 constellation figures (~9 kB), and `astronomy-engine` (a regular dependency) for the Sun,
Moon and planets. Star positions agree with the Python backend to under 0.001°, bodies to under 0.05°
(`test/` checks this against numbers exported from it).

What it does **not** do: fetch frames or camera data, know about caelum's file layout or API, render
anything on the server, or model atmospheric refraction. It has no notion of a camera — you give it
the lens calibration (`manifest.sky.lens` of a camera that publishes it, or `GET /api/sky/setup`),
the observer's position and the time of the frame.

## Using it from another app

The package is published to **GitHub Packages** with every caelum release (same version).
In the app's repository:

```ini
# .npmrc
@roman-dvorak:registry=https://npm.pkg.github.com
//npm.pkg.github.com/:_authToken=${NODE_AUTH_TOKEN}
```

```bash
pnpm add @roman-dvorak/caelum-sky
```

`NODE_AUTH_TOKEN` is a token with `read:packages` (in GitHub Actions of a repository in the
same organisation, `${{ github.token }}` works when the package grants the repository access:
package → *Package settings* → *Manage Actions access*).

```tsx
import { SkyCanvas } from '@roman-dvorak/caelum-sky/react'

<div style={{ position: 'relative' }}>
  <img src={frameUrl} />
  <SkyCanvas lens={manifest.sky.lens} latDeg={manifest.location.lat} lonDeg={manifest.location.lon}
             when={capturedAt} interactive />
</div>
```

`lens` and `location` come from the camera's `manifest.json` (`sky.lens`, `location` — published
only with `camera.identity.publish_location`) or from `GET /api/sky/setup` when the viewer talks
to a camera directly. `when` is the moment of the frame (UTC).

## Developing

Part of the caelum monorepo (`web/packages/sky`); the apps import its TypeScript source directly.
`pnpm build` type-checks and builds `dist/` (what is published), `pnpm test` checks the numbers
against the Python backend.

The catalog (`src/data/`) and the test fixtures (`test/fixtures.json`) are generated from the
backend — `scripts/export_sky_web_data.py` and `scripts/export_sky_fixtures.py`; a backend test
fails when they are out of date.
