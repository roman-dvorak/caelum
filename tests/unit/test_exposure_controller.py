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


def _no_hysteresis_policy(policy: ExposurePolicyConfig) -> ExposurePolicyConfig:
    """The fixture's presets carry the new default deadband/step hysteresis
    — tests of the older, still-present *absolute* 0.5-2.0x clamp need it
    switched off to isolate that behavior."""
    night = policy.preset_for("night")
    return ExposurePolicyConfig(
        presets={**policy.presets, "night": night.model_copy(update={"deadband_pct": 0.0, "max_step_pct": 1.0})}
    )


def test_correction_is_clamped_to_at_most_double_per_cycle(controller, policy):
    # mean of ~1 vs target of 100 would imply a huge correction without the clamp
    policy = _no_hysteresis_policy(policy)
    current = ExposureTarget(exposure_us=1_000_000, analogue_gain=1.0)
    target = controller.compute_target(_sky_state("night"), _stats(mean=1.0), current, policy)
    assert target.exposure_us * target.analogue_gain <= current.exposure_us * current.analogue_gain * 2.0 + 1e-6


def test_correction_is_clamped_to_at_least_half_per_cycle(controller, policy):
    policy = _no_hysteresis_policy(policy)
    current = ExposureTarget(exposure_us=1_000_000, analogue_gain=1.0)
    target = controller.compute_target(_sky_state("night"), _stats(mean=255.0), current, policy)
    assert target.exposure_us * target.analogue_gain >= current.exposure_us * current.analogue_gain * 0.5 - 1e-6


def test_deadband_holds_steady_for_small_deviations(controller, policy):
    night = policy.preset_for("night")
    tight_policy = ExposurePolicyConfig(
        presets={**policy.presets, "night": night.model_copy(update={"deadband_pct": 0.1, "max_step_pct": 1.0})}
    )
    current = ExposureTarget(exposure_us=1_000_000, analogue_gain=1.0)
    # target_mean_adu=100, measured=105 -> correction factor ~0.952, inside the 10% deadband.
    target = controller.compute_target(_sky_state("night"), _stats(mean=105.0), current, tight_policy)
    assert target.exposure_us == current.exposure_us
    assert target.analogue_gain == pytest.approx(current.analogue_gain)


def test_max_step_limits_correction_more_tightly_than_the_absolute_clamp(controller, policy):
    night = policy.preset_for("night")
    tight_policy = ExposurePolicyConfig(
        presets={**policy.presets, "night": night.model_copy(update={"deadband_pct": 0.0, "max_step_pct": 0.1})}
    )
    current = ExposureTarget(exposure_us=1_000_000, analogue_gain=1.0)
    # Deviation would otherwise justify the full 2.0x absolute clamp.
    target = controller.compute_target(_sky_state("night"), _stats(mean=1.0), current, tight_policy)
    new_product = target.exposure_us * target.analogue_gain
    old_product = current.exposure_us * current.analogue_gain
    assert new_product <= old_product * 1.1 + 1e-6


def test_diagnose_with_no_prev_stats_reports_no_measurement(controller, policy):
    diag = controller.diagnose(_sky_state("night"), None, policy)
    assert diag.measured_mean is None
    assert diag.error_adu is None
    assert diag.correction_factor is None
    assert diag.target_mean_adu == policy.preset_for("night").target_mean_adu


def test_diagnose_reports_error_and_correction_matching_compute_target(controller, policy):
    night = policy.preset_for("night")
    tight_policy = ExposurePolicyConfig(
        presets={**policy.presets, "night": night.model_copy(update={"deadband_pct": 0.0, "max_step_pct": 1.0})}
    )
    stats = _stats(mean=50.0)
    current = ExposureTarget(exposure_us=1_000_000, analogue_gain=1.0)

    diag = controller.diagnose(_sky_state("night"), stats, tight_policy)
    target = controller.compute_target(_sky_state("night"), stats, current, tight_policy)

    assert diag.measured_mean == 50.0
    assert diag.error_adu == pytest.approx(night.target_mean_adu - 50.0)
    assert diag.correction_factor == pytest.approx(2.0)  # 100/50 clamped at the 2.0x ceiling
    expected_product = current.exposure_us * current.analogue_gain * diag.correction_factor
    assert target.exposure_us * target.analogue_gain == pytest.approx(expected_product, rel=1e-6)


def test_diagnose_flags_within_deadband(controller, policy):
    night = policy.preset_for("night")
    tight_policy = ExposurePolicyConfig(
        presets={**policy.presets, "night": night.model_copy(update={"deadband_pct": 0.1, "max_step_pct": 1.0})}
    )
    diag = controller.diagnose(_sky_state("night"), _stats(mean=105.0), tight_policy)
    assert diag.within_deadband is True
    assert diag.correction_factor == pytest.approx(1.0)


def test_deadband_and_max_step_off_matches_pre_hysteresis_behavior(controller, policy):
    """Both fields at their off-equivalent values (0 / 1.0) must reproduce
    exactly the old bounded-only correction — an explicit regression guard
    for deployments that don't opt into the new hysteresis."""
    policy_off = _no_hysteresis_policy(policy)
    current = ExposureTarget(exposure_us=1_000_000, analogue_gain=1.0)
    for mean in (1.0, 50.0, 100.0, 255.0):
        target = controller.compute_target(_sky_state("night"), _stats(mean=mean), current, policy_off)
        measured_mean = max(mean, 1e-3)
        expected_factor = max(0.5, min(2.0, 100.0 / measured_mean))
        expected_product = current.exposure_us * current.analogue_gain * expected_factor
        assert target.exposure_us * target.analogue_gain == pytest.approx(expected_product, rel=1e-6)


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
