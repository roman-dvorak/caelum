from __future__ import annotations

import math
from collections import deque

import pytest

from caelum.capture.brightness import BrightnessSample
from caelum.config.schema import ExposurePolicyConfig, ExposurePreset, adu_to_ev
from caelum.control.exposure import (
    EvLimits,
    ExposureController,
    ExposureTarget,
    exposure_control_snapshot,
    move_split,
    split_ev,
    target_from_ev,
    target_to_ev,
)

NIGHT = ExposurePreset(
    exposure_us_min=100_000,
    exposure_us_max=15_000_000,
    gain_min=1.0,
    gain_max=16.0,
    target_ev=-1.35,  # ≈ 100 ADU
    deadband_ev=0.07,
)
DAY = ExposurePreset(exposure_us_min=100, exposure_us_max=10_000, gain_min=1.0, gain_max=2.0, target_ev=-1.0)
TARGET_ADU = 255 * 2**-1.35


@pytest.fixture
def policy() -> ExposurePolicyConfig:
    base = ExposurePolicyConfig()
    return base.model_copy(update={"presets": {**base.presets, "day": DAY, "night": NIGHT}})


def _sample(median: float, p99: float | None = None) -> BrightnessSample:
    return BrightnessSample(median=median, p99=p99 if p99 is not None else median, pixel_count=1000)


def _scene(k: float, gamma: float = 1.0 / 2.2):
    """A camera looking at a static scene: median ADU as a function of the
    exposure*gain actually used. gamma < 1 mimics the ISP's tone curve."""

    def median(target: ExposureTarget) -> float:
        product = target.exposure_us / 1e6 * target.analogue_gain
        return min(255.0, k * product**gamma)

    return median


def _scene_hitting_target_at(seconds: float, gamma: float = 1.0 / 2.2):
    return _scene(TARGET_ADU / seconds**gamma, gamma)


def _run(controller, policy, scene, start: ExposureTarget, cycles: int, period: str = "night", lag: int = 0):
    """Closed loop against `scene`. With `lag`, the camera applies a new
    setting only `lag` frames after it was requested — like libcamera with
    queued requests and long frames."""
    pipeline = deque([start] * lag)
    applied = start
    history = []
    for _ in range(cycles):
        target = controller.step(_sample(scene(applied)), applied, period, policy)
        history.append((applied, target, controller.diagnostics))
        pipeline.append(target)
        applied = pipeline.popleft()
    return history


# ---- EV conversion and splitting ---------------------------------------------


def test_ev_is_log2_of_seconds_plus_log2_of_gain():
    assert target_to_ev(ExposureTarget(1_000_000, 1.0)) == pytest.approx(0.0)
    assert target_to_ev(ExposureTarget(2_000_000, 1.0)) == pytest.approx(1.0)
    assert target_to_ev(ExposureTarget(1_000_000, 4.0)) == pytest.approx(2.0)
    assert target_to_ev(ExposureTarget(1_000, 1.0)) == pytest.approx(math.log2(1e-3))


def test_image_brightness_ev_is_relative_to_full_scale():
    assert adu_to_ev(255) == pytest.approx(0.0)
    assert adu_to_ev(127.5) == pytest.approx(-1.0)


def test_target_from_ev_round_trips_within_the_preset():
    for target in (ExposureTarget(150_000, 1.0), ExposureTarget(15_000_000, 3.0), ExposureTarget(4_000_000, 1.0)):
        back = target_from_ev(target_to_ev(target), NIGHT)
        assert back.exposure_us == pytest.approx(target.exposure_us, rel=1e-5)
        assert back.analogue_gain == pytest.approx(target.analogue_gain, rel=1e-6)


def test_split_ev_starts_exposure_first():
    limits = EvLimits.from_preset(NIGHT)
    ev_t, ev_g = split_ev(limits.exposure_max + 1.5, limits)
    assert ev_t == pytest.approx(limits.exposure_max)
    assert ev_g == pytest.approx(1.5)


def test_move_split_more_light_raises_exposure_first():
    limits = EvLimits.from_preset(NIGHT)
    t, g = move_split(limits.exposure_max - 1.0, 0.0, 2.5, limits)
    assert t == pytest.approx(limits.exposure_max)
    assert g == pytest.approx(1.5)


def test_move_split_less_light_lowers_gain_first():
    limits = EvLimits.from_preset(NIGHT)
    t, g = move_split(limits.exposure_max, 2.0, -3.0, limits)
    assert g == pytest.approx(limits.gain_min)
    assert t == pytest.approx(limits.exposure_max - 1.0)


def test_move_split_only_moves_out_of_range_values_toward_the_range():
    limits = EvLimits.from_preset(NIGHT)
    above = limits.exposure_max + 2.0  # e.g. left over from a longer preset
    t, g = move_split(above, 1.0, 0.5, limits)  # more light wanted
    assert t == pytest.approx(above)  # not pushed further out, nor snapped back
    assert g == pytest.approx(1.5)


# ---- regulation -------------------------------------------------------------


def test_initial_target_is_the_middle_of_the_ev_range(policy):
    target = ExposureController().initial_target("night", policy)
    limits = EvLimits.from_preset(NIGHT)
    assert target_to_ev(target) == pytest.approx((limits.total_min + limits.total_max) / 2, abs=1e-3)


def test_underexposed_frame_raises_exposure(policy):
    current = ExposureTarget(1_000_000, 1.0)
    target = ExposureController().step(_sample(20.0), current, "night", policy)
    assert target_to_ev(target) > target_to_ev(current)


def test_overexposed_frame_lowers_exposure(policy):
    current = ExposureTarget(1_000_000, 1.0)
    target = ExposureController().step(_sample(200.0), current, "night", policy)
    assert target_to_ev(target) < target_to_ev(current)


def test_error_and_terms_are_in_ev(policy):
    controller = ExposureController()
    controller.step(_sample(TARGET_ADU / 2), ExposureTarget(1_000_000, 1.0), "night", policy)
    d = controller.diagnostics
    assert d.target_ev == pytest.approx(-1.35)
    assert d.measured_ev == pytest.approx(-2.35)
    assert d.error_ev == pytest.approx(1.0)
    assert d.correction_ev == pytest.approx(1.0 / policy.response_gamma)
    assert d.applied_ev == pytest.approx(0.0)
    assert d.required_ev == pytest.approx(d.applied_ev + d.correction_ev)
    assert d.remaining_ev == pytest.approx(d.required_ev)
    assert d.p_term_ev == 0.0  # first frame: nothing to compare the required EV with yet
    assert d.i_term_ev == pytest.approx(NIGHT.ki * d.remaining_ev)
    assert d.d_term_ev == 0.0


@pytest.mark.parametrize("gamma", [1.0 / 2.2, 1.0])
@pytest.mark.parametrize("lag", [0, 3])
def test_converges_without_oscillating_even_when_the_camera_lags(policy, gamma, lag):
    scene = _scene_hitting_target_at(2.0, gamma)  # target reached at 2 s, gain 1
    history = _run(ExposureController(), policy, scene, ExposureTarget(100_000, 1.0), cycles=80, lag=lag)
    applied = [a for a, _, _ in history]
    final = [scene(a) for a in applied[-10:]]
    assert all(abs(math.log2(m / TARGET_ADU)) < 0.1 for m in final)
    assert applied[-1].analogue_gain == pytest.approx(1.0)  # gain never needed here
    if gamma < 1:
        # With a realistic (ISP tone curve) response there's no real overshoot past 2 s.
        assert max(target_to_ev(t) for _, t, _ in history) <= 1.0 + 0.2


def test_every_frame_is_measured_while_a_change_is_still_in_the_pipeline(policy):
    history = _run(ExposureController(), policy, _scene_hitting_target_at(4.0), ExposureTarget(100_000, 1.0),
                   cycles=12, lag=3)
    assert all(d.error_ev is not None and d.remaining_ev is not None for _, _, d in history)


def test_p_acts_on_scene_changes_only(policy):
    controller = ExposureController()
    current = ExposureTarget(1_000_000, 1.0)
    # Same scene twice, settings unchanged (camera lagging): P stays zero.
    controller.step(_sample(40.0), current, "night", policy)
    controller.step(_sample(40.0), current, "night", policy)
    assert controller.diagnostics.p_term_ev == pytest.approx(0.0)
    # The scene gets 2x brighter: P responds to the required-EV change.
    controller.step(_sample(40.0 * 2**policy.response_gamma), current, "night", policy)
    assert controller.diagnostics.p_term_ev == pytest.approx(-NIGHT.kp, abs=1e-6)


def test_within_deadband_nothing_moves_or_integrates(policy):
    controller = ExposureController()
    current = ExposureTarget(2_000_000, 1.0)
    target = controller.step(_sample(TARGET_ADU * 1.02), current, "night", policy)
    assert target == current
    assert controller.diagnostics.within_deadband is True
    assert controller.diagnostics.integrating is False


def test_saturated_median_corrects_by_a_big_step(policy):
    controller = ExposureController()
    current = ExposureTarget(2_000_000, 4.0)
    controller.step(_sample(255.0), current, "night", policy)
    d = controller.diagnostics
    assert d.saturated is True
    assert d.correction_ev <= -policy.saturated_step_ev
    assert d.change_ev <= -NIGHT.ki * policy.saturated_step_ev + 1e-9


def test_saturated_highlights_alone_do_not_override_an_underexposed_median(policy):
    # The sun in an allsky frame saturates p99 all day; the median decides.
    current = ExposureTarget(2_000_000, 1.0)
    target = ExposureController().step(_sample(TARGET_ADU / 2, p99=255.0), current, "night", policy)
    assert target_to_ev(target) > target_to_ev(current)


# ---- anti-windup -------------------------------------------------------------


def test_does_not_integrate_while_pinned_at_the_upper_limit(policy):
    controller = ExposureController()
    too_dark = _scene(k=0.5)  # can't reach the target even at max exposure*gain
    history = _run(controller, policy, too_dark, ExposureTarget(1_000_000, 1.0), cycles=100)
    pinned = [d for a, _, d in history if a == ExposureTarget(NIGHT.exposure_us_max, NIGHT.gain_max)]
    assert len(pinned) > 50
    assert all(d.limited == "upper" and d.integrating is False for d in pinned[1:])

    # Suddenly far too bright: the very next frame already goes down, gain first.
    at_max = history[-1][0]
    next_target = controller.step(_sample(_scene(k=5000.0)(at_max)), at_max, "night", policy)
    assert next_target.analogue_gain < NIGHT.gain_max
    assert next_target.exposure_us == NIGHT.exposure_us_max


def test_does_not_integrate_while_pinned_at_the_lower_limit(policy):
    controller = ExposureController()
    history = _run(controller, policy, _scene(k=1e6), ExposureTarget(1_000_000, 1.0), cycles=60)
    pinned = [d for a, _, d in history if a == ExposureTarget(NIGHT.exposure_us_min, NIGHT.gain_min)]
    assert len(pinned) > 20
    assert all(d.limited == "lower" and d.integrating is False for d in pinned[1:])


# ---- sky periods, start, manual ------------------------------------------------


def test_dawn_lowers_gain_first_even_when_the_next_preset_allows_less_exposure(policy):
    twilight = ExposurePreset(
        exposure_us_min=10_000, exposure_us_max=8_000_000, gain_min=1.0, gain_max=12.0, target_ev=-1.35
    )
    policy = policy.model_copy(update={"presets": {**policy.presets, "astronomical_twilight": twilight}})
    controller = ExposureController()
    current = ExposureTarget(15_000_000, 8.0)
    controller.prime(current, "night")

    k = 40.0
    previous = current
    for _ in range(60):
        k *= 1.25  # the sky keeps getting brighter
        current = controller.step(_sample(_scene(k)(current)), current, "astronomical_twilight", policy)
        assert current.analogue_gain <= previous.analogue_gain + 1e-9  # gain never goes up
        assert current.exposure_us <= previous.exposure_us
        if current.exposure_us < previous.exposure_us:
            assert current.analogue_gain == pytest.approx(1.0)  # exposure only moves with gain at its floor
        previous = current
    assert current.exposure_us < 8_000_000


def test_dusk_raises_exposure_first_then_gain(policy):
    controller = ExposureController()
    current = ExposureTarget(100_000, 1.0)
    controller.prime(current, "night")
    k = 2000.0
    for _ in range(80):
        k /= 1.2  # the sky keeps getting darker
        previous = current
        current = controller.step(_sample(_scene(k)(current)), current, "night", policy)
        if current.analogue_gain > previous.analogue_gain + 1e-9:
            assert current.exposure_us == NIGHT.exposure_us_max
    assert current.exposure_us == NIGHT.exposure_us_max


def test_primed_controller_regulates_from_the_commanded_setting(policy):
    controller = ExposureController()
    commanded = ExposureTarget(6_800_000, 1.0)
    controller.prime(commanded, "night")
    # The camera's first frame still has its own defaults; it is still a
    # valid measurement (r is anchored to what it was taken with), but the
    # next command starts from what was commanded, not from those defaults.
    default = ExposureTarget(66_000, 16.0)
    scene = _scene_hitting_target_at(4.0)
    target = controller.step(_sample(scene(default)), default, "night", policy)
    assert target.analogue_gain == pytest.approx(1.0)


def test_manual_override_is_tracked_and_released_bumplessly(policy):
    controller = ExposureController()
    manual = ExposureTarget(3_000_000, 2.0)
    controller.track(manual, _sample(TARGET_ADU), manual, "night", policy)
    assert controller.diagnostics.manual is True
    assert controller.diagnostics.output_ev == pytest.approx(target_to_ev(manual))
    target = controller.step(_sample(TARGET_ADU), manual, "night", policy)
    assert target.exposure_us == manual.exposure_us
    assert target.analogue_gain == pytest.approx(manual.analogue_gain)


def test_snapshot_is_all_ev(policy):
    controller = ExposureController()
    controller.step(_sample(50.0), ExposureTarget(1_000_000, 1.0), "night", policy)
    snapshot = exposure_control_snapshot(controller.diagnostics)
    assert {"target_ev", "measured_ev", "error_ev", "p_term_ev", "i_term_ev", "output_ev"} <= snapshot.keys()
    assert not any("adu" in key or "pct" in key for key in snapshot)


# ---- config migration ----------------------------------------------------------


def test_legacy_adu_and_percent_config_is_converted_to_ev():
    preset = ExposurePreset.model_validate(
        {
            "exposure_us_min": 100,
            "exposure_us_max": 1000,
            "gain_min": 1.0,
            "gain_max": 2.0,
            "target_mean_adu": 127.5,
            "saturation_threshold": 255.0,
            "deadband_pct": 0.2,
            "deadband_ev": None,
            "max_step_pct": 0.25,
            "max_step_ev": None,
        }
    )
    assert preset.target_ev == pytest.approx(-1.0)
    assert preset.saturation_ev == pytest.approx(0.0)
    assert preset.deadband_ev == pytest.approx(math.log2(1.2), abs=1e-3)


def test_new_keys_win_over_legacy_ones():
    preset = ExposurePreset.model_validate({"target_ev": -2.0, "target_mean_adu": 200})
    assert preset.target_ev == -2.0
