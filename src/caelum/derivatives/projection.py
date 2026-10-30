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
from collections.abc import Callable
from typing import Literal, NamedTuple, Protocol


class Point(NamedTuple):
    x: float
    y: float


ProjectionName = Literal["equidistant_fisheye", "equisolid_fisheye", "stereographic_fisheye", "orthographic_fisheye"]

#: Image-plane distance from the optical axis for a ray `theta` radians off
#: it, up to a constant. Real fisheye lenses follow one of these (or
#: something close to them); the constant drops out because every function is
#: normalised to the image circle's edge below.
_RADIAL: dict[str, Callable[[float], float]] = {
    "equidistant_fisheye": lambda t: t,
    "equisolid_fisheye": lambda t: 2.0 * math.sin(t / 2.0),
    "stereographic_fisheye": lambda t: 2.0 * math.tan(t / 2.0),
    "orthographic_fisheye": lambda t: math.sin(t),
}


def _radial_fraction(projection: str, theta: float, theta_max: float) -> float:
    """r / r_edge for a ray at angle `theta` from the optical axis."""
    f = _RADIAL.get(projection, _RADIAL["equidistant_fisheye"])
    return f(theta) / f(theta_max)


def _inverse_radial_fraction(projection: str, fraction: float, theta_max: float) -> float:
    """Inverse of `_radial_fraction`: the angle off the axis at `fraction` of the edge radius."""
    f = _RADIAL.get(projection, _RADIAL["equidistant_fisheye"])
    target = fraction * f(theta_max)
    if projection == "equisolid_fisheye":
        return 2.0 * math.asin(min(1.0, target / 2.0))
    if projection == "stereographic_fisheye":
        return 2.0 * math.atan(target / 2.0)
    if projection == "orthographic_fisheye":
        return math.asin(min(1.0, target))
    return target


def _axis_scales(aspect: float) -> tuple[float, float]:
    """Fractions of the image width/height that one unit of `radius` spans.

    `radius` is a fraction of the image's *shorter* side, so on a 4:3 frame a
    circle of radius 0.48 is 0.48 of the height but only 0.36 of the width.
    Treating both axes as the same fraction would draw an ellipse.
    `aspect` is width / height."""
    aspect = aspect if aspect > 0 else 1.0
    return (1.0 / aspect, 1.0) if aspect >= 1.0 else (1.0, aspect)


def altaz_to_fraction(
    alt_deg: float,
    az_deg: float,
    *,
    center_x: float,
    center_y: float,
    radius: float,
    azimuth_offset_deg: float,
    mirror: bool,
    aspect: float = 1.0,
    fov_deg: float = 180.0,
    projection: str = "equidistant_fisheye",
) -> Point | None:
    """Allsky fisheye projection. The optical axis points at the zenith, so
    the zenith angle (90 - altitude) goes through the lens' radial function
    and the direction comes straight from azimuth. `radius` is the edge of
    the image circle, which is where the zenith angle reaches `fov_deg / 2`
    (the horizon, for a 180 degree lens). Returns None for anything the lens
    cannot see (below the horizon on a 180 degree lens, outside the circle
    on a wider one) — there is nothing to draw."""
    theta_max = math.radians(fov_deg) / 2.0
    theta = math.radians(90.0 - alt_deg)
    if theta > theta_max + 1e-9:
        return None
    r = radius * _radial_fraction(projection, theta, theta_max)
    phi = math.radians(az_deg + azimuth_offset_deg)
    if mirror:
        phi = -phi
    sx, sy = _axis_scales(aspect)
    return Point(x=center_x + r * math.sin(phi) * sx, y=center_y - r * math.cos(phi) * sy)


def fraction_to_altaz(
    x_frac: float,
    y_frac: float,
    *,
    center_x: float,
    center_y: float,
    radius: float,
    azimuth_offset_deg: float,
    mirror: bool,
    aspect: float = 1.0,
    fov_deg: float = 180.0,
    projection: str = "equidistant_fisheye",
) -> tuple[float, float] | None:
    """Inverse of `altaz_to_fraction`. Returns None outside the calibrated
    image circle (including a degenerate `radius <= 0`, which encloses
    nothing)."""
    if radius <= 0.0:
        return None
    sx, sy = _axis_scales(aspect)
    dx = (x_frac - center_x) / sx
    dy = (center_y - y_frac) / sy
    r = math.hypot(dx, dy)
    if r > radius:
        return None
    phi = math.atan2(dx, dy)
    if mirror:
        phi = -phi
    az_deg = (math.degrees(phi) - azimuth_offset_deg) % 360.0
    theta = _inverse_radial_fraction(projection, r / radius, math.radians(fov_deg) / 2.0)
    return 90.0 - math.degrees(theta), az_deg


class _CalibrationLike(Protocol):
    """Structural shape shared by `LensConfig` and `TelescopePositionSettings`
    — matched by attribute, not by inheritance, so this module stays free of
    a dependency on either's home package. Settings objects without `fov_deg`
    / `projection` are treated as a plain 180 degree equidistant lens."""

    center_x: float
    center_y: float
    radius: float
    azimuth_offset_deg: float
    mirror: bool


def _kwargs(calibration: _CalibrationLike, aspect: float) -> dict:
    return {
        "center_x": calibration.center_x,
        "center_y": calibration.center_y,
        "radius": calibration.radius,
        "azimuth_offset_deg": calibration.azimuth_offset_deg,
        "mirror": calibration.mirror,
        "aspect": aspect,
        "fov_deg": getattr(calibration, "fov_deg", 180.0),
        "projection": getattr(calibration, "projection", "equidistant_fisheye"),
    }


def project_pixel_to_altaz(
    x_frac: float, y_frac: float, calibration: _CalibrationLike, aspect: float = 1.0
) -> tuple[float, float] | None:
    """Convenience wrapper around `fraction_to_altaz` for callers that
    already have a calibration object (e.g. `CameraConfig.lens`)."""
    return fraction_to_altaz(x_frac, y_frac, **_kwargs(calibration, aspect))


def project_altaz_to_pixel(
    alt_deg: float, az_deg: float, calibration: _CalibrationLike, aspect: float = 1.0
) -> Point | None:
    """Convenience wrapper around `altaz_to_fraction` for a calibration object."""
    return altaz_to_fraction(alt_deg, az_deg, **_kwargs(calibration, aspect))
