"""Closed-loop exposure/gain controller.

Each cycle: look up the preset for the current sky-state period, compute a
bounded brightness-correction factor from the previous frame's stats, and
split the corrected exposure*gain product back into exposure/gain with a
"prefer exposure over gain" ordering — hold gain at its floor and let
exposure absorb the correction; only once exposure saturates at the
preset's max does gain start rising to make up the rest. That single rule
is what keeps noise down at night (plenty of exposure headroom, gain rarely
needed) *and* keeps gain near its minimum during the day (the preset's
exposure range alone is normally enough) — it's the same mechanism, not two
different code paths for day vs. night.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from caelum.capture.stats import FrameStats
from caelum.config.schema import ExposurePolicyConfig, ExposurePreset
from caelum.control.skystate import SkyState

# Bounds how much the exposure*gain product may swing in one cycle — the
# anti-flicker guard. A period transition (e.g. civil -> nautical twilight)
# therefore eases in over several cycles instead of jump-cutting.
_MIN_CORRECTION = 0.5
_MAX_CORRECTION = 2.0

# If the previous frame had blown highlights, force a downward correction
# regardless of what the mean-brightness math alone would suggest.
_HIGHLIGHT_GUARD_CORRECTION = 0.8


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


@dataclass(frozen=True)
class ExposureTarget:
    exposure_us: int
    analogue_gain: float


class ExposureController:
    def compute_target(
        self,
        sky_state: SkyState,
        prev_stats: FrameStats | None,
        current: ExposureTarget,
        policy: ExposurePolicyConfig,
    ) -> ExposureTarget:
        preset = policy.preset_for(sky_state.period)

        if prev_stats is None:
            # No feedback yet (first cycle, or backend just switched preset
            # ranges) — start at the preset's geometric middle.
            exposure_us = math.sqrt(preset.exposure_us_min * preset.exposure_us_max)
            gain = math.sqrt(preset.gain_min * preset.gain_max)
            return ExposureTarget(exposure_us=int(round(exposure_us)), analogue_gain=float(gain))

        measured_mean = max(prev_stats.mean, 1e-3)
        correction_factor = _clamp(preset.target_mean_adu / measured_mean, _MIN_CORRECTION, _MAX_CORRECTION)
        if prev_stats.p99 > preset.saturation_threshold:
            correction_factor = min(correction_factor, _HIGHLIGHT_GUARD_CORRECTION)

        new_product = current.exposure_us * current.analogue_gain * correction_factor
        exposure_us, gain = self._split_exposure_first(new_product, preset)

        return ExposureTarget(exposure_us=int(round(exposure_us)), analogue_gain=float(gain))

    @staticmethod
    def _split_exposure_first(product: float, preset: ExposurePreset) -> tuple[float, float]:
        exposure_us = _clamp(product / preset.gain_min, preset.exposure_us_min, preset.exposure_us_max)
        gain = _clamp(product / exposure_us, preset.gain_min, preset.gain_max)
        return exposure_us, gain
