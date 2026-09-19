from __future__ import annotations

from datetime import UTC, datetime

import pytest

from caelum.control.skystate import SkyStateCalculator

PRAGUE = {"lat": 50.0755, "lon": 14.4378, "elevation_m": 200.0}


@pytest.fixture(scope="module")
def calculator():
    return SkyStateCalculator(**PRAGUE)


def test_summer_solstice_midday_sun_is_near_its_yearly_max_altitude(calculator):
    # Solar-noon altitude at the summer solstice ≈ 90 - |lat - declination|
    # ≈ 90 - (50.0755 - 23.44) ≈ 63.4° for this latitude.
    state = calculator.compute(datetime(2026, 6, 21, 11, 0, tzinfo=UTC))
    assert 60.0 < state.sun_altitude_deg < 66.0
    assert state.period == "day"


def test_winter_solstice_midday_sun_is_near_its_yearly_min_altitude(calculator):
    # ≈ 90 - (50.0755 + 23.44) ≈ 16.5°.
    state = calculator.compute(datetime(2026, 12, 21, 11, 0, tzinfo=UTC))
    assert 13.0 < state.sun_altitude_deg < 20.0
    assert state.period == "day"


def test_deep_night_is_classified_as_night(calculator):
    state = calculator.compute(datetime(2026, 12, 21, 23, 0, tzinfo=UTC))
    assert state.sun_altitude_deg < -18.0
    assert state.period == "night"


def test_moon_illumination_is_a_fraction_between_zero_and_one(calculator):
    state = calculator.compute(datetime(2026, 3, 15, 22, 0, tzinfo=UTC))
    assert 0.0 <= state.moon_illumination <= 1.0


def test_period_over_one_day_rises_then_falls_exactly_once(calculator):
    # Hourly samples across a full day should trace a single unimodal arc
    # (night -> ... -> day -> ... -> night): non-decreasing up to the peak,
    # non-increasing after it. A classification bug (e.g. a mislabeled
    # twilight band) would show up as a second, spurious peak.
    order = {"night": 0, "astronomical_twilight": 1, "nautical_twilight": 2, "civil_twilight": 3, "day": 4}
    codes = [
        order[calculator.compute(datetime(2026, 3, 15, hour, 0, tzinfo=UTC)).period]
        for hour in range(24)
    ]
    peak = codes.index(max(codes))
    assert all(a <= b for a, b in zip(codes[: peak + 1], codes[1 : peak + 1], strict=False))
    assert all(a >= b for a, b in zip(codes[peak:], codes[peak + 1 :], strict=False))


def test_compute_defaults_to_now_without_error(calculator):
    state = calculator.compute()
    assert isinstance(state.sun_altitude_deg, float)
