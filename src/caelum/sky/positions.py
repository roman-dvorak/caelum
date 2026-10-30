"""Where things are in the sky over the camera at a given moment.

Stars are computed here with plain numpy (proper motion, IAU 1976 precession
from J2000 to the date, mean sidereal time) — a few arcseconds of accuracy
and a few milliseconds for the whole catalog, with no network, ephemeris file
or IERS table involved. Nutation, aberration and refraction are left out:
they are at most a few arcminutes, under a pixel on a fisheye image where one
pixel is a few tenths of a degree. The Sun, Moon and planets come from
astropy's builtin ephemeris (the same one `control/skystate.py` uses).
"""

from __future__ import annotations

import functools
import math
from dataclasses import dataclass
from datetime import UTC, datetime

import numpy as np

from .catalog import StarCatalog, load_catalog

_J2000_JD = 2451545.0
_ARCSEC = math.pi / (180.0 * 3600.0)

#: Rough apparent magnitudes — only used to size and rank the symbols.
_BODIES: tuple[tuple[str, str, float], ...] = (
    ("sun", "Sun", -26.7),
    ("moon", "Moon", -12.0),
    ("mercury", "Mercury", 0.0),
    ("venus", "Venus", -4.0),
    ("mars", "Mars", 0.8),
    ("jupiter", "Jupiter", -2.3),
    ("saturn", "Saturn", 0.7),
)


@dataclass(frozen=True)
class SkyObject:
    kind: str  # "star" | "sun" | "moon" | "planet"
    name: str
    mag: float
    alt_deg: float
    az_deg: float


def julian_date(when: datetime) -> float:
    """JD of a datetime, taking UTC as UT1 (they differ by under a second,
    i.e. 15 arcseconds of sidereal time)."""
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return when.timestamp() / 86400.0 + 2440587.5


def _horizontal(ra_rad: np.ndarray, dec_rad: np.ndarray, jd: float, lat_deg: float, lon_deg: float):
    """(alt, az) in degrees, azimuth from north through east, for apparent
    positions of date."""
    t = (jd - _J2000_JD) / 36525.0
    gmst = 280.46061837 + 360.98564736629 * (jd - _J2000_JD) + 0.000387933 * t * t - t**3 / 38710000.0
    hour_angle = np.radians((gmst + lon_deg) % 360.0) - ra_rad
    lat = math.radians(lat_deg)
    sin_alt = math.sin(lat) * np.sin(dec_rad) + math.cos(lat) * np.cos(dec_rad) * np.cos(hour_angle)
    alt = np.arcsin(np.clip(sin_alt, -1.0, 1.0))
    az = np.arctan2(
        -np.cos(dec_rad) * np.sin(hour_angle),
        np.sin(dec_rad) * math.cos(lat) - np.cos(dec_rad) * np.cos(hour_angle) * math.sin(lat),
    )
    return np.degrees(alt), np.degrees(az) % 360.0


def _precess_from_j2000(ra_rad: np.ndarray, dec_rad: np.ndarray, t: float):
    """Meeus (21.2/21.4): mean equatorial J2000 -> mean equator of date; `t` in Julian centuries."""
    zeta = (2306.2181 * t + 0.30188 * t * t + 0.017998 * t**3) * _ARCSEC
    z = (2306.2181 * t + 1.09468 * t * t + 0.018203 * t**3) * _ARCSEC
    theta = (2004.3109 * t - 0.42665 * t * t - 0.041833 * t**3) * _ARCSEC
    a = np.cos(dec_rad) * np.sin(ra_rad + zeta)
    b = math.cos(theta) * np.cos(dec_rad) * np.cos(ra_rad + zeta) - math.sin(theta) * np.sin(dec_rad)
    c = math.sin(theta) * np.cos(dec_rad) * np.cos(ra_rad + zeta) + math.cos(theta) * np.sin(dec_rad)
    return np.arctan2(a, b) + z, np.arcsin(np.clip(c, -1.0, 1.0))


@dataclass(frozen=True)
class StarPositions:
    hr: np.ndarray
    names: list[str]
    mag: np.ndarray
    alt_deg: np.ndarray
    az_deg: np.ndarray


def star_positions(
    when: datetime, lat_deg: float, lon_deg: float, catalog: StarCatalog | None = None, max_mag: float = 6.0
) -> StarPositions:
    """Alt/az of every catalog star brighter than `max_mag` (above or below
    the horizon — callers decide what to keep)."""
    catalog = catalog or load_catalog()
    keep = np.flatnonzero(catalog.vmag <= max_mag)
    jd = julian_date(when)
    years = (jd - _J2000_JD) / 365.25
    dec0 = np.radians(catalog.dec_deg[keep])
    ra0 = np.radians(catalog.ra_deg[keep])
    # Proper motion; the RA component is stored as mu_alpha*cos(dec).
    dec = dec0 + catalog.pm_dec_arcsec[keep] * years * _ARCSEC
    ra = ra0 + catalog.pm_ra_arcsec[keep] * years * _ARCSEC / np.maximum(np.cos(dec0), 1e-6)
    ra, dec = _precess_from_j2000(ra, dec, years / 100.0)
    alt, az = _horizontal(ra, dec, jd, lat_deg, lon_deg)
    return StarPositions(
        hr=catalog.hr[keep], names=[catalog.names[i] for i in keep], mag=catalog.vmag[keep], alt_deg=alt, az_deg=az
    )


def body_positions(when: datetime, lat_deg: float, lon_deg: float, elevation_m: float = 0.0) -> list[SkyObject]:
    """Sun, Moon and the naked-eye planets (astropy, builtin ephemeris — no download)."""
    import astropy.units as u
    from astropy.coordinates import AltAz, EarthLocation, get_body
    from astropy.time import Time

    from caelum.control import skystate  # noqa: F401  (sets astropy's IERS config: no network, ever)

    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    t = Time(when, scale="utc")
    location = EarthLocation(lat=lat_deg * u.deg, lon=lon_deg * u.deg, height=elevation_m * u.m)
    frame = AltAz(obstime=t, location=location)
    bodies = []
    for key, name, mag in _BODIES:
        coord = get_body(key, t, location).transform_to(frame)
        kind = key if key in ("sun", "moon") else "planet"
        bodies.append(SkyObject(kind, name, mag, float(coord.alt.deg), float(coord.az.deg)))
    return bodies


@functools.lru_cache(maxsize=4)
def _bodies_cached(minute: int, lat: float, lon: float, elevation: float) -> tuple[SkyObject, ...]:
    return tuple(body_positions(datetime.fromtimestamp(minute * 60, tz=UTC), lat, lon, elevation))


def bodies_for(when: datetime, lat_deg: float, lon_deg: float, elevation_m: float = 0.0) -> list[SkyObject]:
    """`body_positions`, cached per minute (the Moon moves ~0.5 arcmin in one,
    and astropy costs tens of milliseconds a call on a Pi)."""
    return list(_bodies_cached(int(when.timestamp() // 60), round(lat_deg, 4), round(lon_deg, 4), round(elevation_m)))


def sky_objects(
    when: datetime,
    lat_deg: float,
    lon_deg: float,
    elevation_m: float = 0.0,
    *,
    max_mag: float = 4.5,
    min_alt_deg: float = -90.0,
    bodies: bool = True,
) -> list[SkyObject]:
    """Everything worth drawing: stars up to `max_mag` and the bodies, above `min_alt_deg`."""
    stars = star_positions(when, lat_deg, lon_deg, max_mag=max_mag)
    objects = [
        SkyObject("star", stars.names[i], float(stars.mag[i]), float(stars.alt_deg[i]), float(stars.az_deg[i]))
        for i in np.flatnonzero(stars.alt_deg >= min_alt_deg)
    ]
    if bodies:
        objects += [b for b in bodies_for(when, lat_deg, lon_deg, elevation_m) if b.alt_deg >= min_alt_deg]
    return objects
