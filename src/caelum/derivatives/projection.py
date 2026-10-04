"""Shared equidistant-fisheye allsky projection math.

Both the camera's own lens calibration (`CameraConfig.lens`, used to turn a
clicked pixel into an alt/az sky position) and the `telescope_position` demo
plugin (used to turn a tracked alt/az position into a screen pixel) describe
the same physical projection, just in opposite directions. They intentionally
keep separate config objects — a fixed lens calibration is not the same
thing as a demo/future-INDI mount-tracking overlay, and coupling them would
force awkward precedence questions if the two are ever set to different
values for testing — but there is no reason to duplicate the trigonometry
twice, so both delegate to this module.
"""

from __future__ import annotations

import math
from typing import NamedTuple, Protocol


class Point(NamedTuple):
    x: float
    y: float


def altaz_to_fraction(
    alt_deg: float,
    az_deg: float,
    *,
    center_x: float,
    center_y: float,
    radius: float,
    azimuth_offset_deg: float,
    mirror: bool,
) -> Point | None:
    """Standard allsky equidistant-fisheye projection: distance from the
    zenith pixel scales linearly with zenith angle (90 - altitude), and
    direction comes straight from azimuth. Returns None below the horizon —
    there is nothing to draw."""
    if alt_deg < 0.0:
        return None
    r = radius * (90.0 - alt_deg) / 90.0
    theta = math.radians(az_deg + azimuth_offset_deg)
    if mirror:
        theta = -theta
    x = center_x + r * math.sin(theta)
    y = center_y - r * math.cos(theta)
    return Point(x=x, y=y)


def fraction_to_altaz(
    x_frac: float,
    y_frac: float,
    *,
    center_x: float,
    center_y: float,
    radius: float,
    azimuth_offset_deg: float,
    mirror: bool,
) -> tuple[float, float] | None:
    """Inverse of `altaz_to_fraction`. Returns None outside the calibrated
    horizon circle (including a degenerate `radius <= 0`, which encloses
    nothing)."""
    if radius <= 0.0:
        return None
    dx = x_frac - center_x
    dy = center_y - y_frac
    r = math.hypot(dx, dy)
    if r > radius:
        return None
    theta = math.atan2(dx, dy)
    if mirror:
        theta = -theta
    az_deg = (math.degrees(theta) - azimuth_offset_deg) % 360.0
    alt_deg = 90.0 - 90.0 * (r / radius)
    return alt_deg, az_deg


class _CalibrationLike(Protocol):
    """Structural shape shared by `LensConfig` and `TelescopePositionSettings`
    — matched by attribute, not by inheritance, so this module stays free of
    a dependency on either's home package."""

    center_x: float
    center_y: float
    radius: float
    azimuth_offset_deg: float
    mirror: bool


def project_pixel_to_altaz(x_frac: float, y_frac: float, calibration: _CalibrationLike) -> tuple[float, float] | None:
    """Convenience wrapper around `fraction_to_altaz` for callers that
    already have a calibration object (e.g. `CameraConfig.lens`)."""
    return fraction_to_altaz(
        x_frac,
        y_frac,
        center_x=calibration.center_x,
        center_y=calibration.center_y,
        radius=calibration.radius,
        azimuth_offset_deg=calibration.azimuth_offset_deg,
        mirror=calibration.mirror,
    )
