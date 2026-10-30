from __future__ import annotations

import pytest

from caelum.derivatives.projection import altaz_to_fraction, fraction_to_altaz

_CALIBRATIONS = [
    dict(center_x=0.5, center_y=0.5, radius=0.48, azimuth_offset_deg=0.0, mirror=False),
    dict(center_x=0.5, center_y=0.5, radius=0.48, azimuth_offset_deg=15.0, mirror=False),
    dict(center_x=0.5, center_y=0.5, radius=0.48, azimuth_offset_deg=0.0, mirror=True),
    dict(center_x=0.45, center_y=0.55, radius=0.4, azimuth_offset_deg=-30.0, mirror=True),
]


@pytest.mark.parametrize("calibration", _CALIBRATIONS)
@pytest.mark.parametrize("alt_deg,az_deg", [(90.0, 0.0), (60.0, 30.0), (30.0, 200.0), (0.0, 350.0), (10.0, 190.0)])
def test_pixel_to_altaz_round_trips_through_altaz_to_fraction(calibration, alt_deg, az_deg):
    point = altaz_to_fraction(alt_deg, az_deg, **calibration)
    assert point is not None

    recovered = fraction_to_altaz(point.x, point.y, **calibration)
    assert recovered is not None
    recovered_alt, recovered_az = recovered

    assert recovered_alt == pytest.approx(alt_deg, abs=1e-6)
    if alt_deg < 90.0:
        # At the zenith itself (r=0) azimuth is undefined — any azimuth maps
        # to the same pixel, so there's nothing meaningful to recover.
        assert recovered_az == pytest.approx(az_deg % 360.0, abs=1e-6)


def test_altaz_to_fraction_below_horizon_is_none():
    point = altaz_to_fraction(-5.0, 90.0, center_x=0.5, center_y=0.5, radius=0.48, azimuth_offset_deg=0.0, mirror=False)
    assert point is None


def test_fraction_to_altaz_outside_radius_is_none():
    assert (
        fraction_to_altaz(0.99, 0.99, center_x=0.5, center_y=0.5, radius=0.1, azimuth_offset_deg=0.0, mirror=False)
        is None
    )


def test_fraction_to_altaz_zero_radius_is_none():
    assert (
        fraction_to_altaz(0.5, 0.5, center_x=0.5, center_y=0.5, radius=0.0, azimuth_offset_deg=0.0, mirror=False)
        is None
    )


def test_fraction_to_altaz_at_center_is_zenith():
    result = fraction_to_altaz(0.5, 0.5, center_x=0.5, center_y=0.5, radius=0.48, azimuth_offset_deg=0.0, mirror=False)
    assert result is not None
    alt_deg, _ = result
    assert alt_deg == pytest.approx(90.0)


@pytest.mark.parametrize("aspect", [4 / 3, 1.0, 3 / 4])
@pytest.mark.parametrize(
    "projection", ["equidistant_fisheye", "equisolid_fisheye", "stereographic_fisheye", "orthographic_fisheye"]
)
@pytest.mark.parametrize("fov_deg", [180.0, 190.0])
def test_round_trip_on_non_square_frames_and_other_lenses(aspect, projection, fov_deg):
    cal = dict(center_x=0.5, center_y=0.5, radius=0.45, azimuth_offset_deg=12.0, mirror=False,
               aspect=aspect, fov_deg=fov_deg, projection=projection)
    for alt, az in [(80.0, 10.0), (45.0, 123.0), (5.0, 300.0)]:
        point = altaz_to_fraction(alt, az, **cal)
        assert point is not None
        alt2, az2 = fraction_to_altaz(point.x, point.y, **cal)
        assert alt2 == pytest.approx(alt, abs=1e-6)
        assert az2 == pytest.approx(az, abs=1e-6)


def test_horizon_is_a_circle_in_pixels_not_an_ellipse():
    # 4:3 frame, radius 0.4 of the shorter side (the height).
    width, height = 4056, 3040
    cal = dict(center_x=0.5, center_y=0.5, radius=0.4, azimuth_offset_deg=0.0, mirror=False, aspect=width / height)
    for az in (0.0, 90.0, 180.0, 270.0, 37.0):
        p = altaz_to_fraction(0.0, az, **cal)
        dist_px = ((p.x - 0.5) * width) ** 2 + ((p.y - 0.5) * height) ** 2
        assert dist_px ** 0.5 == pytest.approx(0.4 * height, rel=1e-9)


def test_wide_lens_sees_below_the_horizon_but_not_past_its_edge():
    cal = dict(center_x=0.5, center_y=0.5, radius=0.48, azimuth_offset_deg=0.0, mirror=False, fov_deg=190.0)
    assert altaz_to_fraction(-4.0, 0.0, **cal) is not None
    assert altaz_to_fraction(-6.0, 0.0, **cal) is None
    horizon = altaz_to_fraction(0.0, 0.0, **cal)
    assert 0.5 - horizon.y < 0.48  # the horizon lies inside the circle's edge
