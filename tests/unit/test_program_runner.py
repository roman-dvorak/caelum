"""Running programs through CaptureContext/run_once, with a fake driver."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import numpy as np
import pytest

from caelum.cameras.base import RawFrame
from caelum.capture_runtime import CaptureContext, CaptureProgramError, ProgramTimeout, TooManyCaptures, load_program
from caelum.capture_runtime.context import Overrides
from caelum.capture_runtime.errors import ProgramStopped
from caelum.capture_runtime.runner import run_once, timeout_for
from caelum.config.schema import AppConfig
from caelum.control.exposure import ExposureController, ExposureTarget
from caelum.control.skystate import SkyState


def _sky() -> SkyState:
    return SkyState(
        timestamp=datetime.now(UTC),
        sun_altitude_deg=-30.0,
        sun_azimuth_deg=0.0,
        moon_altitude_deg=-10.0,
        moon_azimuth_deg=0.0,
        moon_illumination=0.0,
        period="night",
    )


class FakeDriver:
    def __init__(self, fail_at: int | None = None) -> None:
        self.calls: list[tuple[ExposureTarget, bool]] = []
        self.fail_at = fail_at
        self.stop = False

    def capture_for_program(self, target, align_to_slot):
        if self.fail_at is not None and len(self.calls) == self.fail_at:
            raise OSError("camera gone")
        self.calls.append((target, align_to_slot))
        raw = RawFrame(
            image=np.full((40, 60, 3), 51, dtype=np.uint8),
            exposure_us=target.exposure_us,
            analogue_gain=target.analogue_gain,
            sensor_timestamp_ns=0,
            captured_at=datetime.now(UTC),
        )
        return raw, _sky()

    def stop_requested(self):
        return self.stop


def _ctx(driver, state=None, max_captures=16) -> CaptureContext:
    return CaptureContext(
        driver=driver,
        config=AppConfig(),
        sky=_sky(),
        program_name="t.py",
        state={} if state is None else state,
        params={"n": 3},
        exposure_controller=ExposureController(),
        commanded=ExposureTarget(exposure_us=1000, analogue_gain=1.0),
        camera_fresh=True,
        overrides=Overrides(),
        stream_mode=False,
        interval_s=1.0,
        slot=0,
        max_captures=max_captures,
    )


@pytest.fixture
def loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


def _run(loop, source, driver=None, **kw):
    driver = driver or FakeDriver()
    ctx = _ctx(driver, **kw)
    return run_once(loop, load_program("t.py", source), ctx, 5.0), ctx, driver


def test_multiple_captures_only_first_aligned_and_selection_returned(loop):
    source = '''
async def capture(ctx):
    frames = [await ctx.capture(exposure_us=1000 * (i + 1)) for i in range(ctx.params["n"])]
    return frames[1:]
'''
    result, ctx, driver = _run(loop, source)
    assert [align for _, align in driver.calls] == [True, False, False]
    assert [f.index for f in result.frames] == [1, 2]
    assert result.kind == "series" and result.representative == 0
    assert result.frames[0].requested.exposure_us == 2000
    assert result.frames[0].brightness.median == pytest.approx(51.0)
    assert ctx.captures == 3


def test_single_frame_is_a_set_of_one(loop):
    result, _, _ = _run(loop, "async def capture(ctx):\n    return await ctx.capture(exposure_us=100)\n")
    assert result.kind == "single" and len(result.frames) == 1


def test_capture_set_with_representative_and_annotations(loop):
    source = '''
async def capture(ctx):
    frames = [await ctx.capture(exposure_us=e) for e in (100, 1000, 10000)]
    return ctx.capture_set(frames, kind="hdr", representative=frames[1], ev_step=2)
'''
    result, _, _ = _run(loop, source)
    assert result.kind == "hdr"
    assert result.representative == 1
    assert result.primary.requested.exposure_us == 1000
    assert result.annotations == {"ev_step": 2}


def test_bad_representative_is_program_error(loop):
    source = '''
async def capture(ctx):
    frame = await ctx.capture(exposure_us=100)
    return ctx.capture_set([frame], representative=5)
'''
    with pytest.raises(CaptureProgramError, match="representative"):
        _run(loop, source)


def test_state_survives_between_runs(loop):
    source = '''
async def capture(ctx):
    ctx.state["runs"] = ctx.state.get("runs", 0) + 1
'''
    state: dict = {}
    for _ in range(3):
        result, _, _ = _run(loop, source, state=state)
        assert result is None
    assert state["runs"] == 3


def test_program_exception_becomes_program_error(loop):
    with pytest.raises(CaptureProgramError, match="ZeroDivisionError"):
        _run(loop, "async def capture(ctx):\n    1 / 0\n")


def test_bad_return_value_is_program_error(loop):
    with pytest.raises(CaptureProgramError, match="returned int"):
        _run(loop, "async def capture(ctx):\n    return 5\n")


def test_too_many_captures(loop):
    source = '''
async def capture(ctx):
    while True:
        await ctx.capture(exposure_us=100)
'''
    with pytest.raises(TooManyCaptures):
        _run(loop, source, max_captures=4)


def test_timeout(loop):
    program = load_program("slow.py", "import asyncio\nasync def capture(ctx):\n    await asyncio.sleep(10)\n")
    with pytest.raises(ProgramTimeout):
        run_once(loop, program, _ctx(FakeDriver()), 0.1)


def test_camera_error_propagates_even_if_program_swallows_it(loop):
    source = '''
async def capture(ctx):
    try:
        await ctx.capture(exposure_us=100)
    except Exception:
        pass
'''
    with pytest.raises(OSError, match="camera gone"):
        _run(loop, source, driver=FakeDriver(fail_at=0))


def test_stop_unwinds_quietly(loop):
    driver = FakeDriver()
    driver.stop = True
    with pytest.raises(ProgramStopped):
        _run(loop, "async def capture(ctx):\n    await ctx.capture(exposure_us=100)\n", driver=driver)


def test_timeout_budget():
    program = load_program("p.py", "async def capture(ctx):\n    pass\n")
    assert timeout_for(program, 60.0, 20.0) == 240.0
    assert timeout_for(program, 1.0, 60.0) == 150.0
    explicit = load_program("p.py", "PROGRAM = {'timeout_s': 7}\nasync def capture(ctx):\n    pass\n")
    assert timeout_for(explicit, 60.0, 20.0) == 7.0
