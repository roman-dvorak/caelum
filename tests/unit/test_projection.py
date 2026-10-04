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
