from __future__ import annotations

from datetime import UTC, datetime

import pytest

from caelum.capture.stats import FrameStats
from caelum.config.schema import ExposurePolicyConfig, ExposurePreset
from caelum.control.exposure import ExposureController, ExposureTarget
from caelum.control.skystate import SkyState


def _sky_state(period: str) -> SkyState:
    return SkyState(
        timestamp=datetime.now(UTC),
        sun_altitude_deg=-30.0 if period == "night" else 30.0,
        sun_azimuth_deg=180.0,
        moon_altitude_deg=10.0,
        moon_azimuth_deg=90.0,
        moon_illumination=0.5,
        period=period,
    )


def _stats(mean: float, p99: float | None = None, focus_score: float = 100.0) -> FrameStats:
    return FrameStats(
        mean=mean, p95=mean, p99=p99 if p99 is not None else mean, saturated_fraction=0.0, focus_score=focus_score
    )


@pytest.fixture
def policy() -> ExposurePolicyConfig:
    return ExposurePolicyConfig(
        presets={
            "day": ExposurePreset(
                exposure_us_min=100, exposure_us_max=10_000, gain_min=1.0, gain_max=2.0,
                target_mean_adu=128, saturation_threshold=250,
            ),
            "civil_twilight": ExposurePreset(),
            "nautical_twilight": ExposurePreset(),
            "astronomical_twilight": ExposurePreset(),
            "night": ExposurePreset(
                exposure_us_min=100_000, exposure_us_max=15_000_000, gain_min=1.0, gain_max=16.0,
                target_mean_adu=100, saturation_threshold=250,
            ),
        }
    )


@pytest.fixture
def controller() -> ExposureController:
    return ExposureController()


def test_first_cycle_with_no_stats_starts_at_geometric_middle(controller, policy):
    day = policy.preset_for("day")
    target = controller.compute_target(_sky_state("day"), None, ExposureTarget(0, 0.0), policy)
    assert day.exposure_us_min <= target.exposure_us <= day.exposure_us_max
    assert day.gain_min <= target.analogue_gain <= day.gain_max


def test_underexposed_frame_increases_exposure_or_gain(controller, policy):
    current = ExposureTarget(exposure_us=1_000_000, analogue_gain=2.0)
    target = controller.compute_target(_sky_state("night"), _stats(mean=20.0), current, policy)
    assert target.exposure_us * target.analogue_gain > current.exposure_us * current.analogue_gain


def test_overexposed_frame_decreases_exposure_or_gain(controller, policy):
    current = ExposureTarget(exposure_us=1_000_000, analogue_gain=2.0)
    target = controller.compute_target(_sky_state("night"), _stats(mean=250.0), current, policy)
    assert target.exposure_us * target.analogue_gain < current.exposure_us * current.analogue_gain


def test_correction_is_clamped_to_at_most_double_per_cycle(controller, policy):
    # mean of ~1 vs target of 100 would imply a huge correction without the clamp
    current = ExposureTarget(exposure_us=1_000_000, analogue_gain=1.0)
    target = controller.compute_target(_sky_state("night"), _stats(mean=1.0), current, policy)
    assert target.exposure_us * target.analogue_gain <= current.exposure_us * current.analogue_gain * 2.0 + 1e-6


def test_correction_is_clamped_to_at_least_half_per_cycle(controller, policy):
    current = ExposureTarget(exposure_us=1_000_000, analogue_gain=1.0)
    target = controller.compute_target(_sky_state("night"), _stats(mean=255.0), current, policy)
    assert target.exposure_us * target.analogue_gain >= current.exposure_us * current.analogue_gain * 0.5 - 1e-6


def test_highlight_guard_forces_downward_correction_despite_low_mean(controller, policy):
    # mean says "too dark, expose more" but p99 says highlights are blown —
    # the guard must win.
    current = ExposureTarget(exposure_us=1_000_000, analogue_gain=1.0)
    target = controller.compute_target(
        _sky_state("night"), _stats(mean=20.0, p99=254.0), current, policy
    )
    assert target.exposure_us * target.analogue_gain < current.exposure_us * current.analogue_gain


def test_prefers_exposure_over_gain_while_headroom_remains(controller, policy):
    night = policy.preset_for("night")
    current = ExposureTarget(exposure_us=200_000, analogue_gain=1.0)
    target = controller.compute_target(_sky_state("night"), _stats(mean=50.0), current, policy)
    # target_mean_adu=100 is 2x the measured 50 -> correction clamps at 2.0,
    # well within exposure headroom (200_000 * 2 = 400_000 << exposure_us_max)
    assert target.analogue_gain == pytest.approx(night.gain_min)
    assert target.exposure_us > current.exposure_us


def test_falls_back_to_gain_once_exposure_is_saturated(controller, policy):
    night = policy.preset_for("night")
    current = ExposureTarget(exposure_us=night.exposure_us_max, analogue_gain=1.0)
    target = controller.compute_target(_sky_state("night"), _stats(mean=50.0), current, policy)
    assert target.exposure_us == night.exposure_us_max
    assert target.analogue_gain > 1.0


def test_respects_period_specific_bounds(controller, policy):
    day = policy.preset_for("day")
    current = ExposureTarget(exposure_us=day.exposure_us_max, analogue_gain=day.gain_max)
    target = controller.compute_target(_sky_state("day"), _stats(mean=1.0), current, policy)
    assert target.exposure_us <= day.exposure_us_max
    assert target.analogue_gain <= day.gain_max
