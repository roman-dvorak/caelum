# @roman-dvorak/caelum-sky

Draws the night sky over a fisheye allsky camera picture, in the browser: the lens outline,
the horizon and altitude rings, constellation lines, stars, the Sun, Moon and planets, and the
compass — worked out from the lens calibration, the observer's position and the moment, so
nothing has to be rendered by the camera. It is what the caelum Dashboard and Lens page draw,
and what the Caelum Viewer can use for the same picture.

- **`@roman-dvorak/caelum-sky`** — framework-free core: `loadSkyData()`, `drawSky()`,
  `starPositions()`, `altAzToFraction()` / `fractionToAltAz()` (the lens model), `SKY_LAYERS`.
- **`@roman-dvorak/caelum-sky/react`** — `<SkyCanvas>` (fills a positioned parent, with
  hover popups) and `useSkySettings()` (layers and star magnitude, kept in `localStorage`).

The star catalog (Yale Bright Star Catalogue, 5080 stars) and the planetary ephemeris
(`astronomy-engine`) are lazy chunks, loaded on first use. `react` is an optional peer dependency.

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
