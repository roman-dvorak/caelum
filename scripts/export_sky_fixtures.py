#!/usr/bin/env python3
"""Writes `web/packages/sky/test/fixtures.json`: what the backend computes for
a few moments and lenses, which the web package's tests must reproduce. The
backend (numpy + astropy) is the reference; the browser implementation
(`@roman-dvorak/caelum-sky`) is checked against these numbers.

    scripts/export_sky_fixtures.py
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from caelum.config.schema import LensConfig  # noqa: E402
from caelum.derivatives.projection import project_altaz_to_pixel  # noqa: E402
from caelum.sky.positions import body_positions, star_positions  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "web" / "packages" / "sky" / "test" / "fixtures.json"

MOMENTS = [
    ("2026-10-30T21:00:00+00:00", 50.0755, 14.4378, 200.0),
    ("2026-01-15T03:30:00+00:00", -33.9, 18.4, 20.0),
    ("2031-06-21T23:10:00+00:00", 28.3, -16.5, 2300.0),
]
LENSES = [
    LensConfig(),
    LensConfig(projection="equisolid_fisheye", center_x=0.52, center_y=0.47, radius=0.45, fov_deg=170,
               azimuth_offset_deg=33.0, mirror=True),
    LensConfig(projection="stereographic_fisheye", radius=0.4, fov_deg=160, azimuth_offset_deg=-80.0),
]
ASPECT = 4 / 3
POINTS = [(85.0, 10.0), (60.0, 120.0), (30.0, 200.0), (12.0, 300.0), (5.0, 45.0)]


def build() -> dict:
    cases = []
    for iso, lat, lon, elevation in MOMENTS:
        when = datetime.fromisoformat(iso).astimezone(UTC)
        stars = star_positions(when, lat, lon, max_mag=3.5)
        cases.append({
            "when": iso, "lat": lat, "lon": lon, "elevation_m": elevation,
            "stars": {str(int(hr)): [round(float(a), 5), round(float(z), 5)]
                      for hr, a, z in zip(stars.hr, stars.alt_deg, stars.az_deg, strict=True)},
            "bodies": {b.name: [round(b.alt_deg, 4), round(b.az_deg, 4)]
                       for b in body_positions(when, lat, lon, elevation)},
        })
    projections = []
    for lens in LENSES:
        for alt, az in POINTS:
            point = project_altaz_to_pixel(alt, az, lens, ASPECT)
            projections.append({"lens": lens.model_dump(), "aspect": ASPECT, "alt": alt, "az": az,
                                "point": None if point is None else [round(point.x, 6), round(point.y, 6)]})
    return {"cases": cases, "projections": projections}


def main() -> None:
    data = build()
    OUT.write_text(json.dumps(data, separators=(",", ":")) + "\n")
    print(f"{len(data['cases'])} moments, {len(data['projections'])} projections -> {OUT}")


if __name__ == "__main__":
    main()
