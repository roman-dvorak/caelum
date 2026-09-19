from __future__ import annotations

from datetime import UTC, datetime

import pytest

from caelum.config.schema import StoragePolicyConfig
from caelum.control.skystate import SkyState
from caelum.control.storage_policy import StoragePolicy


def _sky_state(period: str) -> SkyState:
    return SkyState(
        timestamp=datetime.now(UTC),
        sun_altitude_deg=0.0,
        sun_azimuth_deg=0.0,
        moon_altitude_deg=0.0,
        moon_azimuth_deg=0.0,
        moon_illumination=0.0,
        period=period,
    )


@pytest.fixture
def cfg() -> StoragePolicyConfig:
    return StoragePolicyConfig(
        raw_periods=("astronomical_twilight", "night"),
        night_capture_interval_s=30.0,
        day_capture_interval_s=60.0,
    )


@pytest.mark.parametrize(
    "period,expected_save_raw",
    [
        ("day", False),
        ("civil_twilight", False),
        ("nautical_twilight", False),
        ("astronomical_twilight", True),
        ("night", True),
    ],
)
def test_save_raw_follows_configured_raw_periods(cfg, period, expected_save_raw):
    decision = StoragePolicy().decide(_sky_state(period), cfg)
    assert decision.save_raw is expected_save_raw


def test_capture_interval_matches_raw_vs_thumbnail_only(cfg):
    night_decision = StoragePolicy().decide(_sky_state("night"), cfg)
    day_decision = StoragePolicy().decide(_sky_state("day"), cfg)
    assert night_decision.capture_interval_s == cfg.night_capture_interval_s
    assert day_decision.capture_interval_s == cfg.day_capture_interval_s
