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

## The sky overlay

With the lens saved, enable the **`sky_overlay`** plugin (a button on the Lens
page, or on the Plugins page). It draws, into every frame's overlay:

- stars as rings sized by magnitude, with names for the bright ones,
- the Sun, Moon and naked-eye planets,
- constellation lines (stick figures of the 88 constellations),
- the N/E/S/W letters and the 0°/30°/60° altitude rings.

Each of these is a separate *layer* — `grid`, `constellations`, `stars`,
`planets`, `compass`. With `storage_policy.overlay_mode = "file"` every layer is
stored as its own PNG next to the overlay, and the Dashboard (and the remote
viewer, from the uploaded files) shows an on/off checkbox for each. With
`"burn"` the layers are burned into the thumbnail and cannot be toggled.

It is recomputed for every frame from the clock, so it stays correct all
night, and it goes wherever overlays go (live view, thumbnails, the remote
archive, timelapses). Settings (Plugins page): `max_magnitude` (default 3.5),
`label_magnitude`, `show_stars`, `show_constellations`, `show_planets`, `show_grid`, `show_compass`
and the colours. The frame's sidecar stores only the parameters (time, place,
lens, options — about a kilobyte), not the star positions: the overlay image
is drawn from them on the camera, and viewers show that image.

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
`scripts/build_star_catalog.py`. Positions are brought to the date with proper
motion, precession and sidereal time — a few arcseconds, with no network or
ephemeris file involved. The Sun, Moon and planets use astropy's builtin
ephemeris, like the rest of caelum's sky state. Refraction is not modelled
(under a pixel on a fisheye image).

## API

All admin-only unless noted; none of them writes configuration (the page saves
through `PUT /api/config`).

| Request | Purpose |
| --- | --- |
| `POST /api/camera/lens/detect-circle` | Image circle of the latest frame. |
| `POST /api/camera/lens/fit-stars` | `{fit_fov, from_config}` — fit to the stars of the latest frame. |
| `GET /api/sky/objects` | Preview level. Sky objects projected with the configured lens. |
| `POST /api/sky/objects` | The same with a lens given in the body. |
