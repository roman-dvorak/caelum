#!/usr/bin/env python3
"""Builds src/caelum/sky/data/constellations.json: constellation stick figures
as pairs of Yale BSC numbers (the `hr` column of stars.csv.gz).

The figures come from d3-celestial's `constellations.lines.json` (BSD-3, the
figures themselves follow Stellarium's modern sky culture), which gives each
line's vertices as J2000 RA/Dec. Every vertex is matched to the nearest
catalog star; a vertex with no star within `TOLERANCE_DEG` (a figure through
a star dimmer than the catalog's limit) cuts the line there.

    scripts/build_constellations.py constellations.lines.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from caelum.sky.catalog import load_catalog  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "src" / "caelum" / "sky" / "data" / "constellations.json"
TOLERANCE_DEG = 0.3


def main(source: Path) -> None:
    catalog = load_catalog()
    ra = np.radians(catalog.ra_deg)
    dec = np.radians(catalog.dec_deg)
    xyz = np.stack([np.cos(dec) * np.cos(ra), np.cos(dec) * np.sin(ra), np.sin(dec)], axis=1)

    def nearest(lon: float, lat: float) -> int | None:
        r, d = np.radians(lon % 360.0), np.radians(lat)
        v = np.array([np.cos(d) * np.cos(r), np.cos(d) * np.sin(r), np.sin(d)])
        dots = xyz @ v
        i = int(np.argmax(dots))
        return int(catalog.hr[i]) if np.degrees(np.arccos(min(1.0, dots[i]))) <= TOLERANCE_DEG else None

    result: dict[str, list[list[int]]] = {}
    missed = 0
    for feature in json.loads(source.read_text())["features"]:
        pairs: set[tuple[int, int]] = set()
        for line in feature["geometry"]["coordinates"]:
            ids = [nearest(lon, lat) for lon, lat in line]
            missed += ids.count(None)
            for a, b in zip(ids, ids[1:], strict=False):
                if a is not None and b is not None and a != b:
                    pairs.add((min(a, b), max(a, b)))
        if pairs:
            result[feature["id"]] = sorted([a, b] for a, b in pairs)
    OUT.write_text(json.dumps(result, separators=(",", ":")) + "\n")
    print(f"{len(result)} constellations, {sum(map(len, result.values()))} segments, "
          f"{missed} vertices without a catalog star -> {OUT}")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
