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
from datetime import UTC, datetime, timedelta

import astropy.units as u
import numpy as np
from astropy.coordinates import AltAz, EarthLocation, SkyCoord, get_body
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

# Sunrise search: coarse-step forward looking for the threshold crossing,
# then bisect within the bracketing pair down to this tolerance. 4 minutes
# is well under the smallest twilight band width at any latitude this app
# targets, so a coarse step can never step clean over a crossing; 30 seconds
# is far tighter than capture intervals (seconds to minutes), so grouping
# frames by the result is never in doubt at the boundary.
_CROSSING_STEP = timedelta(minutes=4)
_CROSSING_SEARCH_WINDOW = timedelta(hours=48)
_CROSSING_TOLERANCE = timedelta(seconds=30)


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

    def _altaz(self, body: str, t: Time) -> SkyCoord:
        return get_body(body, t, self._location).transform_to(AltAz(obstime=t, location=self._location))

    def compute(self, when: datetime | None = None) -> SkyState:
        when = when or datetime.now(UTC)
        t = Time(when if when.tzinfo else when.replace(tzinfo=UTC), scale="utc")

        sun = self._altaz("sun", t)
        moon = self._altaz("moon", t)

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

    def next_sunrise(self, after: datetime | None = None) -> datetime:
        """UTC time of the next sunrise — sun altitude rising through the
        same day/twilight threshold `compute()` classifies against — at or
        after `after` (default: now).

        The only caller is `api/routes/frames.py`'s "observation night"
        grouping, which needs a day boundary that doesn't split a single
        night's data at a fixed-zone midnight. Coarse-step-then-bisect
        rather than a closed-form sunrise formula: this reuses the exact
        `get_body`/`AltAz` transform `compute()` uses, so a sunrise and a
        `compute()` period boundary can never silently disagree.
        """
        after = after or datetime.now(UTC)
        if after.tzinfo is None:
            after = after.replace(tzinfo=UTC)

        prev_t = after
        prev_alt = self._sun_altitude_deg(prev_t)
        steps = int(_CROSSING_SEARCH_WINDOW / _CROSSING_STEP)
        for _ in range(steps):
            t = prev_t + _CROSSING_STEP
            alt = self._sun_altitude_deg(t)
            if prev_alt <= _DAY_THRESHOLD < alt:
                return self._bisect_sunrise(prev_t, t)
            prev_t, prev_alt = t, alt

        raise RuntimeError(
            f"No sunrise found within {_CROSSING_SEARCH_WINDOW} of {after.isoformat()} — "
            "check the configured latitude/longitude (polar day/night at this time of year?)"
        )

    def _sun_altitude_deg(self, when: datetime) -> float:
        return float(self._altaz("sun", Time(when, scale="utc")).alt.deg)

    def _bisect_sunrise(self, before: datetime, after: datetime) -> datetime:
        """`before` is known sub-threshold, `after` known above it; narrows
        that bracket to `_CROSSING_TOLERANCE` and returns its above-threshold
        end, so the result always satisfies "sun is up at or after this"."""
        while (after - before) > _CROSSING_TOLERANCE:
            mid = before + (after - before) / 2
            if self._sun_altitude_deg(mid) > _DAY_THRESHOLD:
                after = mid
            else:
                before = mid
        return after
