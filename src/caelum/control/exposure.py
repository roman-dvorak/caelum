"""Closed-loop exposure/gain controller — a PI(D) regulator working in EV.

Everything is EV (base-2 logarithms):

    EV_t = log2(exposure_us / 1e6)   exposure, relative to 1 s
    EV_g = log2(gain)                analogue gain, relative to 1x
    EV   = EV_t + EV_g               exposure*gain; +1 EV = twice the light
    Y    = log2(median / 255)        image brightness, relative to full scale

**Measurement.** Y is the median of a central circle of the frame (see
`capture/brightness.py`); the setpoint `target_ev` is on the same scale.

**What the frame says it needed.** Every frame carries the exposure and
gain it was really taken with (`applied`), so on its own it tells how much
light it should have had:

    c = (target_ev − Y) / response_gamma      correction, in exposure EV
    r = EV(applied) + c                       the EV the scene requires

(`response_gamma` < 1 because the ISP's tone curve compresses brightness.)
A saturated median caps c at −`saturated_step_ev`. Bright highlights alone
(p99) deliberately don't steer anything: in an allsky frame the sun saturates
them all day, and letting them override the median drove the exposure down
while the sky was already underexposed.

**Regulator.** Velocity form, with u the EV last commanded:

    ε  = r − u_prev                           remaining distance (EV)
    P  = kp · (r − r_prev)                    reacts to the scene changing
    I  = ki · ε                               closes the remaining distance
    D  = −kd · (Δr − Δr_prev)                 off by default (kd = 0)
    u  = u_prev + P + I + D

P acts on the *required* EV rather than on ε, so the loop's own previous
command never kicks it back the other way. Within `deadband_ev` of r
nothing moves. While the output is pinned at a preset limit and ε pushes
further out, nothing integrates — the controller holds and reacts as soon
as the scene changes.

**Split.** Each cycle's ΔEV is applied to the *current* exposure and gain,
by direction:

- more light (ΔEV > 0): exposure up first, up to the preset's maximum, and
  only the rest goes to gain;
- less light (ΔEV < 0): gain down first, down to the preset's minimum, and
  only then exposure.

The preset's bounds are soft: a value outside them (after a switch to the
next sky period's preset, or a manual override) is never forced back in one
jump — it may only move toward the range, in the order above. So when the
sky brightens at dawn and the twilight preset allows far less exposure than
the night one, gain still comes down first and the long exposure is only
shortened once gain is at its floor.
"""

from __future__ import annotations

import math
import threading
from dataclasses import dataclass
from typing import Literal

from caelum.capture.brightness import BrightnessSample
from caelum.config.schema import ExposurePolicyConfig, ExposurePreset, adu_to_ev

# A median this close to full scale is saturated — its real error is unknown.
_SATURATED_MEDIAN_EV = adu_to_ev(250.0)

_EPS = 1e-9

Limited = Literal["none", "upper", "lower"]


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


@dataclass(frozen=True)
class ExposureTarget:
    exposure_us: int
    analogue_gain: float


def exposure_to_ev(exposure_us: float) -> float:
    return math.log2(max(exposure_us, 1.0) / 1_000_000.0)


def gain_to_ev(gain: float) -> float:
    return math.log2(max(gain, 1e-6))


def target_to_ev(target: ExposureTarget) -> float:
    return exposure_to_ev(target.exposure_us) + gain_to_ev(target.analogue_gain)


@dataclass(frozen=True)
class EvLimits:
    exposure_min: float
    exposure_max: float
    gain_min: float
    gain_max: float

    @classmethod
    def from_preset(cls, preset: ExposurePreset) -> EvLimits:
        return cls(
            exposure_min=exposure_to_ev(preset.exposure_us_min),
            exposure_max=exposure_to_ev(max(preset.exposure_us_max, preset.exposure_us_min)),
            gain_min=gain_to_ev(preset.gain_min),
            gain_max=gain_to_ev(max(preset.gain_max, preset.gain_min)),
        )

    @property
    def total_min(self) -> float:
        return self.exposure_min + self.gain_min

    @property
    def total_max(self) -> float:
        return self.exposure_max + self.gain_max


def split_ev(ev: float, limits: EvLimits) -> tuple[float, float]:
    """Total EV -> (exposure EV, gain EV) from scratch, exposure first —
    only for a starting point; regulation moves the current split instead
    (see `move_split`)."""
    ev_exposure = _clamp(ev - limits.gain_min, limits.exposure_min, limits.exposure_max)
    ev_gain = _clamp(ev - ev_exposure, limits.gain_min, limits.gain_max)
    return ev_exposure, ev_gain


def move_split(ev_exposure: float, ev_gain: float, delta: float, limits: EvLimits) -> tuple[float, float]:
    """Apply a ΔEV to the current (exposure, gain), gain-down-first /
    exposure-up-first — see the module docstring. A value already outside
    the preset's bounds is only ever moved toward them."""
    if delta < 0:
        gain = ev_gain if ev_gain <= limits.gain_min else max(ev_gain + delta, limits.gain_min)
        rest = delta - (gain - ev_gain)
        exposure = ev_exposure if ev_exposure <= limits.exposure_min else max(ev_exposure + rest, limits.exposure_min)
        return exposure, gain
    if delta > 0:
        exposure = ev_exposure if ev_exposure >= limits.exposure_max else min(ev_exposure + delta, limits.exposure_max)
        rest = delta - (exposure - ev_exposure)
        gain = ev_gain if ev_gain >= limits.gain_max else min(ev_gain + rest, limits.gain_max)
        return exposure, gain
    return ev_exposure, ev_gain


def target_from_split(ev_exposure: float, ev_gain: float) -> ExposureTarget:
    return ExposureTarget(
        exposure_us=max(1, int(round(2.0**ev_exposure * 1_000_000.0))), analogue_gain=float(2.0**ev_gain)
    )


def target_from_ev(ev: float, preset: ExposurePreset) -> ExposureTarget:
    return target_from_split(*split_ev(ev, EvLimits.from_preset(preset)))


@dataclass(frozen=True)
class ExposureDiagnostics:
    """The regulator's last cycle, all in EV — exposed read-only via
    `GET /api/status` and stored per frame (`exposure_control_snapshot`)."""

    sky_period: str
    target_ev: float
    deadband_ev: float
    ev_min: float
    ev_max: float
    kp: float
    ki: float
    kd: float
    #: Y — the frame's circle median relative to full scale. None until the
    #: first frame has been measured.
    measured_ev: float | None = None
    #: The p99 on the same scale (informational).
    p99_ev: float | None = None
    #: target_ev − Y: how far the frame's brightness was off.
    error_ev: float | None = None
    #: c: the exposure*gain change that frame needed (after gamma, caps).
    correction_ev: float | None = None
    #: EV the frame was actually taken with.
    applied_ev: float | None = None
    #: r = applied + c.
    required_ev: float | None = None
    #: ε = r − previous output.
    remaining_ev: float | None = None
    p_term_ev: float | None = None
    i_term_ev: float | None = None
    d_term_ev: float | None = None
    #: The EV commanded for the next frame, and its split.
    output_ev: float | None = None
    change_ev: float | None = None
    ev_exposure: float | None = None
    ev_gain: float | None = None
    limited: Limited = "none"
    integrating: bool = False
    within_deadband: bool = False
    saturated: bool = False
    manual: bool = False


def idle_diagnostics(period: str, policy: ExposurePolicyConfig) -> ExposureDiagnostics:
    """Diagnostics for before the first frame has been measured."""
    preset = policy.preset_for(period)
    limits = EvLimits.from_preset(preset)
    return ExposureDiagnostics(
        sky_period=period,
        target_ev=preset.target_ev,
        deadband_ev=preset.deadband_ev,
        ev_min=limits.total_min,
        ev_max=limits.total_max,
        kp=preset.kp,
        ki=preset.ki,
        kd=preset.kd,
    )


@dataclass(frozen=True)
class _Measurement:
    measured_ev: float
    p99_ev: float
    error_ev: float
    correction_ev: float
    applied_ev: float
    required_ev: float
    saturated: bool


def _measure(
    sample: BrightnessSample, applied: ExposureTarget, preset: ExposurePreset, policy: ExposurePolicyConfig
) -> _Measurement:
    measured_ev = adu_to_ev(sample.median)
    p99_ev = adu_to_ev(sample.p99)
    error_ev = preset.target_ev - measured_ev
    correction = error_ev / policy.response_gamma
    saturated = measured_ev >= _SATURATED_MEDIAN_EV
    if saturated:
        correction = min(correction, -policy.saturated_step_ev)
    correction = _clamp(correction, -policy.max_correction_ev, policy.max_correction_ev)
    applied_ev = target_to_ev(applied)
    return _Measurement(
        measured_ev=measured_ev,
        p99_ev=p99_ev,
        error_ev=error_ev,
        correction_ev=correction,
        applied_ev=applied_ev,
        required_ev=applied_ev + correction,
        saturated=saturated,
    )


class ExposureController:
    """Stateful — one instance per capture loop, driven only from the
    capture thread. `diagnostics` may be read from any thread."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._diagnostics: ExposureDiagnostics | None = None
        self.reset()

    def clone(self) -> ExposureController:
        """An independent copy with the same state (for test runs that must
        not disturb the production regulator)."""
        other = ExposureController()
        with self._lock:
            state = {k: v for k, v in self.__dict__.items() if k != "_lock"}
        other.__dict__.update(state)
        return other

    def reset(self) -> None:
        """Forget all loop state; the next `step` starts from whatever the
        measured frame was actually taken with."""
        self._period: str | None = None
        # What was last commanded, split: EV of exposure seconds, EV of gain.
        self._ev_exposure: float | None = None
        self._ev_gain: float | None = None
        self._r_prev: float | None = None
        self._dr_prev = 0.0

    @property
    def diagnostics(self) -> ExposureDiagnostics | None:
        with self._lock:
            return self._diagnostics

    def initial_target(self, period: str, policy: ExposurePolicyConfig) -> ExposureTarget:
        """Where to start with no feedback at all: the middle of the
        preset's EV range, split exposure-first."""
        preset = policy.preset_for(period)
        limits = EvLimits.from_preset(preset)
        return target_from_ev((limits.total_min + limits.total_max) / 2.0, preset)

    def _set_state(self, target: ExposureTarget) -> None:
        self._ev_exposure = exposure_to_ev(target.exposure_us)
        self._ev_gain = gain_to_ev(target.analogue_gain)

    def prime(self, commanded: ExposureTarget, period: str) -> None:
        """The loop has just (re)started and sent `commanded` to a fresh
        camera: regulate from there rather than from whatever defaults the
        camera's first frames still carry."""
        self.reset()
        self._period = period
        self._set_state(commanded)

    def track(
        self,
        commanded: ExposureTarget,
        sample: BrightnessSample | None,
        applied: ExposureTarget | None,
        period: str,
        policy: ExposurePolicyConfig,
    ) -> None:
        """Manual override is active: follow it without regulating, so that
        when it is cleared the loop continues from exactly there."""
        preset = policy.preset_for(period)
        self.reset()
        self._period = period
        self._set_state(commanded)
        fields: dict = {}
        if sample is not None and applied is not None:
            m = _measure(sample, applied, preset, policy)
            fields = {
                "measured_ev": m.measured_ev,
                "p99_ev": m.p99_ev,
                "error_ev": m.error_ev,
                "correction_ev": m.correction_ev,
                "applied_ev": m.applied_ev,
                "required_ev": m.required_ev,
                "saturated": m.saturated,
            }
        self._publish(
            ExposureDiagnostics(
                **{
                    **idle_diagnostics(period, policy).__dict__,
                    **fields,
                    "output_ev": target_to_ev(commanded),
                    "change_ev": 0.0,
                    "ev_exposure": self._ev_exposure,
                    "ev_gain": self._ev_gain,
                    "manual": True,
                }
            )
        )

    def step(
        self,
        sample: BrightnessSample,
        applied: ExposureTarget,
        period: str,
        policy: ExposurePolicyConfig,
    ) -> ExposureTarget:
        """One regulation cycle on one frame. `sample` was measured on a
        frame taken with `applied` (from the frame's own metadata, not what
        was requested). Returns the target for the next frame."""
        preset = policy.preset_for(period)
        limits = EvLimits.from_preset(preset)
        m = _measure(sample, applied, preset, policy)

        if self._ev_exposure is None or self._ev_gain is None:
            self._set_state(applied)
        if self._period != period:
            # New sky period (and preset): keep the exposure/gain as they are
            # — the new bounds are approached gradually, in split order — but
            # restart the regulator's own history.
            self._period = period
            self._r_prev = None
            self._dr_prev = 0.0
        assert self._ev_exposure is not None and self._ev_gain is not None
        ev_exposure, ev_gain = self._ev_exposure, self._ev_gain
        prev_output = ev_exposure + ev_gain

        remaining = m.required_ev - prev_output
        dr = 0.0 if self._r_prev is None else m.required_ev - self._r_prev
        within_deadband = abs(remaining) < preset.deadband_ev
        at_upper = remaining > 0 and ev_exposure >= limits.exposure_max - _EPS and ev_gain >= limits.gain_max - _EPS
        at_lower = remaining < 0 and ev_exposure <= limits.exposure_min + _EPS and ev_gain <= limits.gain_min + _EPS

        p = i = d = 0.0
        limited: Limited = "none"
        integrating = False
        if within_deadband:
            pass
        elif at_upper or at_lower:
            # Pinned at a limit with the error pushing further out: hold, and
            # above all don't integrate — nothing accumulates that would have
            # to be unwound once the scene changes.
            limited = "upper" if at_upper else "lower"
        else:
            integrating = True
            p = preset.kp * dr
            i = preset.ki * remaining
            d = -preset.kd * (dr - self._dr_prev) if preset.kd > 0 else 0.0
            delta = p + i + d
            ev_exposure, ev_gain = move_split(ev_exposure, ev_gain, delta, limits)
            moved = ev_exposure + ev_gain - prev_output
            if delta > 0 and moved < delta - _EPS:
                limited = "upper"
            elif delta < 0 and moved > delta + _EPS:
                limited = "lower"

        self._ev_exposure, self._ev_gain = ev_exposure, ev_gain
        self._r_prev, self._dr_prev = m.required_ev, dr
        output = ev_exposure + ev_gain

        self._publish(
            ExposureDiagnostics(
                **{
                    **idle_diagnostics(period, policy).__dict__,
                    "measured_ev": m.measured_ev,
                    "p99_ev": m.p99_ev,
                    "error_ev": m.error_ev,
                    "correction_ev": m.correction_ev,
                    "applied_ev": m.applied_ev,
                    "required_ev": m.required_ev,
                    "remaining_ev": remaining,
                    "p_term_ev": p,
                    "i_term_ev": i,
                    "d_term_ev": d,
                    "output_ev": output,
                    "change_ev": output - prev_output,
                    "ev_exposure": ev_exposure,
                    "ev_gain": ev_gain,
                    "limited": limited,
                    "integrating": integrating,
                    "within_deadband": within_deadband,
                    "saturated": m.saturated,
                }
            )
        )
        return target_from_split(ev_exposure, ev_gain)

    def _publish(self, diagnostics: ExposureDiagnostics) -> None:
        with self._lock:
            self._diagnostics = diagnostics


_SNAPSHOT_FIELDS = (
    "target_ev",
    "measured_ev",
    "p99_ev",
    "error_ev",
    "correction_ev",
    "applied_ev",
    "required_ev",
    "remaining_ev",
    "p_term_ev",
    "i_term_ev",
    "d_term_ev",
    "output_ev",
    "change_ev",
    "ev_exposure",
    "ev_gain",
    "limited",
    "integrating",
    "within_deadband",
    "saturated",
    "manual",
)


def exposure_control_snapshot(diagnostics: ExposureDiagnostics | None) -> dict | None:
    """The compact per-frame record stored in `FrameMetadata.exposure_control`
    — enough to plot the loop's behaviour over a night."""
    if diagnostics is None:
        return None
    snapshot = {name: getattr(diagnostics, name) for name in _SNAPSHOT_FIELDS}
    return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in snapshot.items()}
