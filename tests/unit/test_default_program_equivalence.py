"""The built-in default program steers the exposure exactly as the capture
loop did before capture programs existed (reimplemented here as `_legacy`)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import numpy as np

from caelum.cameras.base import RawFrame
from caelum.capture.brightness import measure
from caelum.capture_runtime import CaptureContext, builtin_program
from caelum.capture_runtime.context import Overrides
from caelum.capture_runtime.runner import run_once
from caelum.config.schema import AppConfig
from caelum.control.exposure import ExposureController, ExposureTarget, exposure_control_snapshot
from caelum.control.skystate import SkyState

SKY = SkyState(
    timestamp=datetime(2026, 10, 5, tzinfo=UTC),
    sun_altitude_deg=-8.0,
    sun_azimuth_deg=0.0,
    moon_altitude_deg=-10.0,
    moon_azimuth_deg=0.0,
    moon_illumination=0.0,
    period="civil_twilight",
)

#: Scene luminance per slot (falling, as at dusk) and the manual override.
SCENE = [np.exp(-0.2 * i) for i in range(30)]
MANUAL = {12: ExposureTarget(20_000, 2.0), 13: ExposureTarget(20_000, 2.0), 14: ExposureTarget(50_000, 1.0)}


def _frame(target: ExposureTarget, slot: int) -> RawFrame:
    value = min(255, 4e-3 * SCENE[slot] * target.exposure_us * target.analogue_gain)
    return RawFrame(
        image=np.full((30, 40, 3), value, dtype=np.float32),
        exposure_us=target.exposure_us,
        analogue_gain=target.analogue_gain,
        sensor_timestamp_ns=0,
        captured_at=SKY.timestamp,
    )


def _legacy(cfg: AppConfig) -> list[tuple[ExposureTarget, dict | None]]:
    controller = ExposureController()
    policy = cfg.exposure_policy
    current = ExposureTarget(exposure_us=1000, analogue_gain=1.0)
    was_manual = False
    out = []
    for slot in range(len(SCENE)):
        manual = MANUAL.get(slot)
        if slot == 0:
            start = manual or controller.initial_target(SKY.period, policy)
            current = start
            controller.prime(start, SKY.period)
        raw = _frame(current, slot)
        applied = ExposureTarget(exposure_us=raw.exposure_us, analogue_gain=raw.analogue_gain)
        sample = measure(raw.image, policy.brightness_roi_diameter_frac)
        if manual is not None:
            nxt = manual
            controller.track(manual, sample, applied, SKY.period, policy)
        else:
            if was_manual:
                controller.reset()
            nxt = controller.step(sample, applied, SKY.period, policy)
        was_manual = manual is not None
        current = nxt
        out.append((nxt, exposure_control_snapshot(controller.diagnostics)))
    return out


class _Driver:
    slot = 0

    def capture_for_program(self, target, align_to_slot):
        return _frame(target, self.slot), SKY

    def stop_requested(self):
        return False


def _program(cfg: AppConfig) -> list[tuple[ExposureTarget, dict | None]]:
    program = builtin_program()
    controller = ExposureController()
    driver = _Driver()
    loop = asyncio.new_event_loop()
    state: dict = {}
    commanded = ExposureTarget(exposure_us=1000, analogue_gain=1.0)
    out = []
    try:
        for slot in range(len(SCENE)):
            driver.slot = slot
            ctx = CaptureContext(
                driver=driver, config=cfg, sky=SKY, program_name=program.name, state=state, params={},
                exposure_controller=controller, commanded=commanded, camera_fresh=slot == 0,
                overrides=Overrides(manual_exposure=MANUAL.get(slot)), stream_mode=False, interval_s=60.0,
                slot=slot, max_captures=16,
            )
            [frame] = run_once(loop, program, ctx, 5.0)
            commanded = ctx.commanded
            out.append((commanded, frame.exposure_control))
    finally:
        loop.close()
    return out


def test_default_program_matches_legacy_loop():
    cfg = AppConfig()
    legacy = _legacy(cfg)
    assert _program(cfg) == legacy
    # The scenario actually moved the exposure around.
    assert len({t for t, _ in legacy}) > 5
