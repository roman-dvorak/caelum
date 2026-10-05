"""CaptureWorker running capture programs: frames returned are submitted,
a failing user program falls back to the built-in default."""

from __future__ import annotations

import time

from caelum.cameras.mock_backend import MockCameraBackend
from caelum.capture.worker import CaptureWorker
from caelum.capture_runtime import load_program
from caelum.control.exposure import ExposureController
from caelum.control.storage_policy import StoragePolicy

from .test_capture_timing import _Config, _config, _RecordingSink, _Sky


def _run(program, frames: int, timeout: float = 10.0):
    sink = _RecordingSink()
    worker = CaptureWorker(
        camera_factory=lambda _cfg: MockCameraBackend(),
        config_manager=_Config(_config(0.1)),
        skystate_calculator=_Sky(),
        exposure_controller=ExposureController(),
        storage_policy=StoragePolicy(),
        frame_sink=sink,
        program_provider=lambda _cfg: program,
    )
    worker.start()
    try:
        deadline = time.monotonic() + timeout
        while len(sink.times) < frames and time.monotonic() < deadline:
            time.sleep(0.02)
    finally:
        worker.request_stop()
        worker.join(2)
    return worker, sink


def test_user_program_frames_are_submitted():
    program = load_program(
        "pair.py",
        "async def capture(ctx):\n"
        "    a = await ctx.capture(exposure_us=1000)\n"
        "    b = await ctx.capture(exposure_us=2000, analogue_gain=2.0)\n"
        "    return [a, b]\n",
    )
    worker, sink = _run(program, 4)
    assert len(sink.times) >= 4
    status = worker.program_status
    assert status["name"] == "pair.py" and status["origin"] == "user"
    assert not status["fallback_active"]


def test_failing_program_falls_back_to_default():
    program = load_program("broken.py", "async def capture(ctx):\n    raise RuntimeError('nope')\n")
    worker, sink = _run(program, 2)
    assert len(sink.times) >= 2
    status = worker.program_status
    assert status["fallback_active"]
    assert status["name"] == "default.py"
    assert "nope" in status["last_error"]
