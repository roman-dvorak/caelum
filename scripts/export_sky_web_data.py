#!/usr/bin/env python3
"""Exports the bundled star catalog and constellation figures as JSON for the
web UI (`web/packages/sky/src/data/`), so the browser draws the sky from the
very same data the backend uses.

    scripts/export_sky_web_data.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from caelum.sky.catalog import load_catalog, load_constellations  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "web" / "packages" / "sky" / "src" / "data"


def main() -> None:
    catalog = load_catalog()
    stars = {
        "hr": [int(v) for v in catalog.hr],
        "ra": [round(float(v), 4) for v in catalog.ra_deg],  # J2000, degrees
        "dec": [round(float(v), 4) for v in catalog.dec_deg],
        "mag": [round(float(v), 2) for v in catalog.vmag],
        "pmRa": [round(float(v) * 1000) for v in catalog.pm_ra_arcsec],  # mas/yr, includes cos(dec)
        "pmDec": [round(float(v) * 1000) for v in catalog.pm_dec_arcsec],
        "name": catalog.names,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "stars.json").write_text(json.dumps(stars, separators=(",", ":"), ensure_ascii=False) + "\n")
    (OUT / "constellations.json").write_text(json.dumps(load_constellations(), separators=(",", ":")) + "\n")
    print(f"{len(stars['hr'])} stars, {len(load_constellations())} figure segments -> {OUT}")


if __name__ == "__main__":
    main()
