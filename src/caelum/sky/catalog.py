"""The bundled bright-star catalog (`data/stars.csv.gz`).

Yale Bright Star Catalogue, 5th revised edition (Hoffleit & Warren; public
domain, via CDS/VizieR V/50), the ~5000 stars brighter than V = 6.0, with
proper names where the star has one and "<Bayer letter> <constellation>"
otherwise. Positions are J2000 plus proper motion; `positions.py` brings
them to the date. Regenerate with `scripts/build_star_catalog.py`.
"""

from __future__ import annotations

import csv
import functools
import gzip
from dataclasses import dataclass
from pathlib import Path

import numpy as np

_DATA = Path(__file__).with_name("data") / "stars.csv.gz"


@dataclass(frozen=True)
class StarCatalog:
    hr: np.ndarray
    ra_deg: np.ndarray  # J2000
    dec_deg: np.ndarray  # J2000
    vmag: np.ndarray
    pm_ra_arcsec: np.ndarray  # per year, includes cos(dec)
    pm_dec_arcsec: np.ndarray  # per year
    names: list[str]

    def __len__(self) -> int:
        return len(self.names)


@functools.lru_cache(maxsize=1)
def load_catalog() -> StarCatalog:
    with gzip.open(_DATA, "rt", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return StarCatalog(
        hr=np.array([int(r["hr"]) for r in rows]),
        ra_deg=np.array([float(r["ra_deg"]) for r in rows]),
        dec_deg=np.array([float(r["dec_deg"]) for r in rows]),
        vmag=np.array([float(r["vmag"]) for r in rows]),
        pm_ra_arcsec=np.array([float(r["pm_ra_mas"]) / 1000.0 for r in rows]),
        pm_dec_arcsec=np.array([float(r["pm_dec_mas"]) / 1000.0 for r in rows]),
        names=[r["name"] for r in rows],
    )
