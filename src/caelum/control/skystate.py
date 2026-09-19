"""Sun/moon position + twilight-period classification for one observer.

Uses `astropy` with its builtin (bundled, analytic) solar-system ephemeris
and `iers.conf.auto_download = False` — this needs **no external file and no
network access, ever**: no ephemeris kernel to pre-seed, nothing that can go
stale or fail to download on a field-deployed Pi. Precision is well within
what altitude-based twilight classification and moon-illumination display
need (cross-checked against `skyfield`'s JPL DE421 ephemeris during
development: sun/moon altitude agreed to within ~0.05°).

`astral` was ruled out earlier for lacking moon altitude/azimuth (only phase).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import astropy.units as u
import numpy as np
from astropy.coordinates import AltAz, EarthLocation, get_body
from astropy.time import Time
from astropy.utils import iers

from caelum.config.schema import SkyPeriod

iers.conf.auto_download = False

# Standard astronomical twilight thresholds (sun altitude, degrees) — the
# same convention used by NOAA/USNO almanacs.
_DAY_THRESHOLD = -0.8333  # accounts for the solar disk radius + refraction
_CIVIL_THRESHOLD = -6.0
_NAUTICAL_THRESHOLD = -12.0
_ASTRONOMICAL_THRESHOLD = -18.0


def _classify_period(sun_altitude_deg: float) -> SkyPeriod:
    if sun_altitude_deg > _DAY_THRESHOLD:
        return "day"
    if sun_altitude_deg > _CIVIL_THRESHOLD:
        return "civil_twilight"
    if sun_altitude_deg > _NAUTICAL_THRESHOLD:
        return "nautical_twilight"
    if sun_altitude_deg > _ASTRONOMICAL_THRESHOLD:
        return "astronomical_twilight"
    return "night"


@dataclass(frozen=True)
class SkyState:
    timestamp: datetime
    sun_altitude_deg: float
    sun_azimuth_deg: float
    moon_altitude_deg: float
    moon_azimuth_deg: float
    moon_illumination: float
    period: SkyPeriod


class SkyStateCalculator:
    def __init__(self, lat: float, lon: float, elevation_m: float) -> None:
        self._location = EarthLocation(lat=lat * u.deg, lon=lon * u.deg, height=elevation_m * u.m)

    def compute(self, when: datetime | None = None) -> SkyState:
        when = when or datetime.now(UTC)
        t = Time(when if when.tzinfo else when.replace(tzinfo=UTC), scale="utc")
        frame = AltAz(obstime=t, location=self._location)

        sun = get_body("sun", t, self._location).transform_to(frame)
        moon = get_body("moon", t, self._location).transform_to(frame)

        # Illuminated fraction from the Sun-Moon elongation as seen from the
        # observer: k = (1 - cos(elongation)) / 2 (0 at new moon, 1 at full
        # moon) — the standard low-error approximation that ignores the
        # small Earth-Moon vs. Sun-Moon distance correction.
        elongation = sun.separation(moon)
        illumination = float((1 - np.cos(elongation.rad)) / 2)

        return SkyState(
            timestamp=when,
            sun_altitude_deg=float(sun.alt.deg),
            sun_azimuth_deg=float(sun.az.deg),
            moon_altitude_deg=float(moon.alt.deg),
            moon_azimuth_deg=float(moon.az.deg),
            moon_illumination=illumination,
            period=_classify_period(float(sun.alt.deg)),
        )
