---
description: 'Calibrating the fisheye lens: finding the image circle, the north offset, the field of view and the projection from the stars, then drawing the live sky, a compass and altitude rings over every frame.'
---

# Lens calibration and the sky overlay

caelum can only say *where in the sky* a pixel is, or *where in the image* a
star is, once it knows the lens: where the optical centre lands on the sensor,
how large the image circle is, which way north points and how the lens maps
angles to distance from the centre. That is `camera.lens`, and **Manage →
Lens** in the web interface fills it in for you. You need an administrator
account and a frame from the camera.

## Doing it

1. **Detect image circle** (any frame, day or night). Finds the lit disc of the
   lens and sets the centre and the radius. It also works when the disc is
   larger than the sensor and is cut off at the top and bottom — only the
   visible part of its edge is used. If the edge is not clean (vignetting, a
   lit horizon) the page says so; check the orange circle by eye.
2. **Fit from stars** (a clear, dark night frame — no Moon, no clouds, with
   the location and the camera clock right). Finds the stars in the frame and
   tries every azimuth, and both handednesses, against the catalog stars that
   should be above the horizon at that moment, then refines by least squares.
   It reports how many stars matched and the residual in pixels, and solves
   for:
   - the **north offset** and whether the lens **mirrors** the sky,
   - the optical **centre**,
   - the **field of view** (the radius of the circle is a measurement and is
     kept; *Fit from stars, keep field of view* holds the field of view too),
   - the **projection**: equidistant, equisolid, stereographic or
     orthographic — the RMS of each is shown so you can see the choice is a
     real one.
3. Drag any value by hand if you want, or **Pick centre on image**. The
   circled stars, the 0°/30°/60° rings and the N/E/S/W letters follow
   immediately, in the browser. Hover over the image for the name and the
   altitude/azimuth of whatever is under the pointer.
4. **Save lens.**

A good fit is 20+ stars with an RMS of a pixel or two. Few matches usually
mean wrong `location.lat`/`lon` or a camera clock that is off by minutes; the
page says which of its checks failed.

## The lens model

| Setting | Meaning |
| --- | --- |
| `center_x`, `center_y` | Optical centre (the zenith), fractions of the frame width / height. |
| `radius` | Edge of the image circle, as a fraction of the frame's **shorter** side — so the same number means the same circle on 4:3 and 16:9. |
| `fov_deg` | Field of view across the circle. 180 means the edge is the horizon; a 190° lens sees 5° below it. |
| `projection` | `equidistant_fisheye` (r ∝ θ, most allsky lenses), `equisolid_fisheye`, `stereographic_fisheye`, `orthographic_fisheye`. |
| `azimuth_offset_deg` | How far the camera is turned against true north. |
| `mirror` | East and west swapped. A camera looking up with north at the top sees east on the left, which needs this on. |

::: warning Older configuration
Before this release `radius` was a fraction of the width on one axis and of the
height on the other, so on a non-square frame the "circle" was an ellipse and
every conversion was off. If you typed a lens in by hand, run the calibration
again.
:::

## The sky on the Dashboard

Once the lens is saved, the **Dashboard** draws the sky over the live picture,
exactly as the Lens page does — live, in the browser, nothing is rendered or
sent per frame:

- the lens outline (the orange image circle and its centre),
- the horizon and the 30° / 60° altitude rings, with the meridians,
- constellation lines (stick figures of the 88 constellations),
- stars as rings sized by magnitude, with names for the bright ones,
- the Sun, Moon and naked-eye planets,
- the N/E/S/W letters.

Hover the picture for a popup with the name, magnitude and sky position of the
star or planet under the pointer, or the altitude and azimuth of any point.
Which parts are drawn, and how faint a star, is set in the small **Sky ▾** menu
above the picture (the same menu is on the Lens page); the choice is saved in
the browser and applies on every page that shows the sky.

The browser works the positions out from the lens (`GET
/api/sky/setup`), the camera's position and the time of the frame it shows, with
the same maths as the backend (checked against it to under 0.001° for stars).
The star catalog and the planetary ephemeris are loaded on first use.

The remote viewer does the same for cameras that publish their position
(`camera.identity.publish_location`, see [Upload](/guide/upload)).

The drawing code is the npm package **`@roman-dvorak/caelum-sky`**, published to
GitHub Packages with every release, so other web apps — the Caelum Viewer —
can draw the same sky with `<SkyCanvas>` (see the package's README for the
`.npmrc` and an example). Its numbers are tested against this backend.

### Sky in the stored pictures

The optional **`sky_overlay`** plugin (a button on the Lens page, or on the
Plugins page; off by default) draws the same sky into every frame's overlay on
the camera, so it is also in stored thumbnails, timelapses and the overlay PNG —
for archives that should show it without a viewer that draws it. Settings
(Plugins page): `max_magnitude` (default 3.5), `label_magnitude`, `show_stars`,
`show_constellations`, `show_planets`, `show_grid`, `show_compass` and the
colours. The frame's sidecar stores only the parameters (time, place, lens,
options — about a kilobyte), not the star positions.

### Names on hover

The Live view and the Lens page show a popup with the name, magnitude and
sky position of the star, planet, Sun or Moon under the pointer. It is built
from `GET /api/sky/objects`, available at preview level: the objects of the
catalog above the horizon, projected with the configured lens.

## Where the data comes from

Stars come from the **Yale Bright Star Catalogue** (5th revised edition,
Hoffleit & Warren; public domain, via CDS/VizieR V/50): the 5080 stars brighter
than magnitude 6.0, with proper motion, bundled as
`src/caelum/sky/data/stars.csv.gz` and regenerated with
`scripts/build_star_catalog.py` (the constellation figures, from d3-celestial,
with `scripts/build_constellations.py`; both are exported for the web UI with
`scripts/export_sky_web_data.py`). Positions are brought to the date with proper
motion, precession and sidereal time — a few arcseconds, with no network or
ephemeris file involved. The Sun, Moon and planets use astropy's builtin
ephemeris, like the rest of caelum's sky state; the browser uses the
`astronomy-engine` library for them. Refraction is not modelled
(under a pixel on a fisheye image).

## API

All admin-only unless noted; none of them writes configuration (the page saves
through `PUT /api/config`).

| Request | Purpose |
| --- | --- |
| `POST /api/camera/lens/detect-circle` | Image circle of the latest frame. |
| `POST /api/camera/lens/fit-stars` | `{fit_fov, from_config}` — fit to the stars of the latest frame. |
| `GET /api/sky/setup` | Preview level. The lens and the observer's position the Dashboard draws the sky from. |
| `GET /api/sky/objects` | Preview level. Sky objects projected with the configured lens. |
| `POST /api/sky/objects` | The same with a lens given in the body. |
