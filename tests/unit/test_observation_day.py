from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from caelum.control.observation_day import ObservationDays
from caelum.control.skystate import SkyStateCalculator

PRAGUE = ZoneInfo("Europe/Prague")


def test_fixed_start_keeps_a_night_in_one_day():
    days = ObservationDays(None, PRAGUE, "09:00")
    # 23:00 on the 15th and 03:00 on the 16th (local) are the same night.
    assert days.label_of(datetime(2026, 10, 15, 21, 0, tzinfo=UTC)) == "2026-10-15"
    assert days.label_of(datetime(2026, 10, 16, 1, 0, tzinfo=UTC)) == "2026-10-15"
    # 09:30 local on the 16th starts the next one.
    assert days.label_of(datetime(2026, 10, 16, 7, 30, tzinfo=UTC)) == "2026-10-16"
    assert days.window("2026-10-15") == (
        datetime(2026, 10, 15, 7, 0, tzinfo=UTC),
        datetime(2026, 10, 16, 7, 0, tzinfo=UTC),
    )


def test_fixed_start_follows_local_time_across_dst():
    days = ObservationDays(None, PRAGUE, "09:00")
    start, end = days.window("2026-10-24")  # clocks go back on the 25th
    assert (start.hour, end.hour) == (7, 8)  # 09:00 CEST, then 09:00 CET
    assert (end - start).total_seconds() == 25 * 3600


def test_sunrise_start_matches_the_calculated_sunrise():
    calc = SkyStateCalculator(lat=50.0755, lon=14.4378, elevation_m=200.0)
    days = ObservationDays(calc, PRAGUE, "sunrise")
    start, end = days.window("2026-10-15")
    assert start == calc.next_sunrise(datetime(2026, 10, 14, 22, 0, tzinfo=UTC))  # local midnight
    assert days.label_of(start) == "2026-10-15"
    assert days.label_of(end) == "2026-10-16"
    assert days.label_of(datetime(2026, 10, 15, 23, 0, tzinfo=UTC)) == "2026-10-15"  # 01:00 local
