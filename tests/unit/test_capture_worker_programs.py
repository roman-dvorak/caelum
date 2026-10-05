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


class _SetSink(_RecordingSink):
    def __init__(self) -> None:
        super().__init__()
        self.sets: list[list] = []
        self.submissions: list = []

    def submit(self, submission) -> bool:
        self.submissions.append(submission)
        return super().submit(submission)

    def submit_set(self, submissions) -> bool:
        self.sets.append(list(submissions))
        for submission in submissions:
            super().submit(submission)
        return True


def _run(program, frames: int, timeout: float = 10.0):
    sink = _SetSink()
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
    members = sink.sets[0]
    assert [m.capture_set["role"] for m in members] == ["representative", "member"]
    assert members[0].capture_set["count"] == 2
    assert [m["exposure_us"] for m in members[0].capture_set["members"]] == [1000, 2000]
    assert members[1].capture_set["representative_captured_at"] == members[0].raw.captured_at.isoformat()
    assert members[0].provenance["capture_program"] == "pair.py"
    assert members[0].provenance["capture_program_sha256"] == program.sha256
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
    provenance = sink.submissions[-1].provenance
    assert provenance["capture_program"] == "default.py"
    assert provenance["capture_program_fallback"] is True
    assert provenance["camera_capabilities"]["model"] == "mock"
    assert sink.submissions[-1].capture_set is None
