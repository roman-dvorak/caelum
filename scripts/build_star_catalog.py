#!/usr/bin/env python3
"""Builds src/caelum/sky/data/stars.csv.gz from the Yale Bright Star Catalogue.

The BSC (Hoffleit & Warren, 5th revised ed.; public domain, distributed by
CDS/VizieR V/50 and HEASARC) is read from the JSON conversion published by
brettonw/YaleBrightStarCatalog, which comes as two files:

    bsc5.json        full records: RA/Dec (J2000), V, proper motion
    bsc5-short.json  the same stars with Bayer letter (B), proper name (N),
                     constellation (C), Flamsteed number (F)

    scripts/build_star_catalog.py bsc5.json bsc5-short.json [max_vmag]

Only stars brighter than `max_vmag` (default 6.0, about 5000 stars — what a
naked eye, and an allsky camera, can see) are kept. The output is a tiny
gzipped CSV so the catalog is data, not code, and can be re-generated.
"""

from __future__ import annotations

import csv
import gzip
import json
import re
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "src" / "caelum" / "sky" / "data" / "stars.csv.gz"


def _sexagesimal(text: str) -> float:
    m = re.match(r"^([+-]?)(\d+)\D+(\d+)\D+([\d.]+)", text.strip())
    if m is None:
        raise ValueError(f"cannot parse {text!r}")
    sign = -1.0 if m.group(1) == "-" else 1.0
    return sign * (int(m.group(2)) + int(m.group(3)) / 60.0 + float(m.group(4)) / 3600.0)


def _label(short: dict) -> str:
    if short.get("N"):
        return short["N"]
    constellation = short.get("C", "")
    if short.get("B") and constellation:
        return f"{short['B']} {constellation}"
    if short.get("F") and constellation:
        return f"{short['F']} {constellation}"
    return f"HR {short['HR']}"


def main() -> None:
    full = json.loads(Path(sys.argv[1]).read_text())
    names = {s["HR"]: s for s in json.loads(Path(sys.argv[2]).read_text())}
    max_vmag = float(sys.argv[3]) if len(sys.argv) > 3 else 6.0

    rows = []
    for star in full:
        vmag = float(star["Vmag"])
        if vmag > max_vmag:
            continue
        ra_deg = _sexagesimal(star["RA"]) * 15.0
        dec_deg = _sexagesimal(star["Dec"])
        rows.append(
            (
                int(star["HR"]),
                f"{ra_deg:.5f}",
                f"{dec_deg:.5f}",
                f"{vmag:.2f}",
                # arcsec/yr in the BSC; stored as mas/yr integers
                round(float(star["pmRA"]) * 1000),
                round(float(star["pmDE"]) * 1000),
                star.get("K", ""),
                _label(names.get(star["HR"], {"HR": star["HR"]})),
            )
        )
    rows.sort(key=lambda r: float(r[3]))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(OUT, "wt", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["hr", "ra_deg", "dec_deg", "vmag", "pm_ra_mas", "pm_dec_mas", "temp_k", "name"])
        writer.writerows(rows)
    print(f"{len(rows)} stars -> {OUT}")


if __name__ == "__main__":
    main()
