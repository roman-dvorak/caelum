"""Captures are evenly spaced on a wall-clock grid `capture_interval_s`
apart, with the middle of each exposure on a grid slot — however long each
capture takes and however much the exposure changes."""

from __future__ import annotations

import threading
import time
from datetime import UTC, datetime

import pytest

from caelum.cameras.mock_backend import MockCameraBackend
from caelum.capture.worker import CaptureWorker
from caelum.config.schema import AppConfig
from caelum.control.exposure import ExposureController, ExposureTarget
from caelum.control.skystate import SkyState
from caelum.control.storage_policy import StoragePolicy


class _Config:
    def __init__(self, cfg: AppConfig) -> None:
        self.current = cfg


class _Sky:
    def compute(self, when=None) -> SkyState:
        return SkyState(
            timestamp=when or datetime.now(UTC),
            sun_altitude_deg=-30.0,
            sun_azimuth_deg=0.0,
            moon_altitude_deg=-10.0,
            moon_azimuth_deg=0.0,
            moon_illumination=0.0,
            period="night",
        )


class _RecordingSink:
    def __init__(self) -> None:
        self.times: list[float] = []
        self.captured: list[datetime] = []
        self.lock = threading.Lock()

    def start(self) -> None: ...

    def stop(self) -> None: ...

    stats: dict = {}

    def submit(self, submission) -> bool:
        with self.lock:
            self.times.append(time.monotonic())
            self.captured.append(submission.raw.captured_at)
        return True


def _config(interval_s: float) -> AppConfig:
    cfg = AppConfig()
    # Short exposures, so the period isn't stretched by them (that case is
    # tested on its own below).
    night = cfg.exposure_policy.presets["night"].model_copy(update={"exposure_us_min": 100, "exposure_us_max": 10_000})
    return cfg.model_copy(
        update={
            "storage_policy": cfg.storage_policy.model_copy(
                update={"night_capture_interval_s": interval_s, "day_capture_interval_s": interval_s}
            ),
            "exposure_policy": cfg.exposure_policy.model_copy(
                update={"presets": {**cfg.exposure_policy.presets, "night": night}}
            ),
        }
    )


def _worker(camera, cfg: AppConfig, sink) -> CaptureWorker:
    return CaptureWorker(
        camera_factory=lambda _cfg: camera,
        config_manager=_Config(cfg),
        skystate_calculator=_Sky(),
        exposure_controller=ExposureController(),
        storage_policy=StoragePolicy(),
        frame_sink=sink,
    )


@pytest.mark.parametrize(
    "exposure_s,expected",
    [(0.001, 30.0), (10.0, 30.0), (29.6, 30.0), (29.9, 60.0), (58.0, 60.0), (61.0, 90.0)],
)
def test_long_exposures_stretch_the_period_to_a_multiple_of_the_interval(exposure_s, expected):
    worker = _worker(MockCameraBackend(), _config(30.0), _RecordingSink())
    target = ExposureTarget(exposure_us=int(exposure_s * 1e6), analogue_gain=1.0)
    assert worker._frame_period(_config(30.0), _Sky().compute(), target) == pytest.approx(expected)


class _SlowMock(MockCameraBackend):
    """A camera whose captures take a varying, substantial share of the
    interval — "capture, then wait the interval" would drift by exactly that
    much every cycle."""

    def __init__(self) -> None:
        super().__init__()
        self._delays = iter([0.05, 0.12, 0.02, 0.15, 0.08, 0.11, 0.01, 0.14, 0.06, 0.1] * 3)

    def capture_frame(self):
        time.sleep(next(self._delays))
        return super().capture_frame()


def _collect(camera, interval_s: float, frames: int) -> _RecordingSink:
    sink = _RecordingSink()
    worker = _worker(camera, _config(interval_s), sink)
    worker.start()
    try:
        deadline = time.monotonic() + 15
        while len(sink.times) < frames and time.monotonic() < deadline:
            time.sleep(0.02)
    finally:
        worker.request_stop()
        worker.join(2)
    return sink


def test_captures_land_on_a_wall_clock_grid_without_drift():
    interval = 0.25
    sink = _collect(_SlowMock(), interval, 9)
    starts = [t.timestamp() for t in sink.captured[:9]]
    # Each capture starts the default start latency (0.1 s) before its slot
    # and the mock stamps it after its own delay (0.01–0.15 s) — so within
    # that window of a slot, every time: no accumulation.
    for t in starts:
        offset = t - round(t / interval) * interval
        assert -0.1 <= offset <= 0.07
    slots = [round(t / interval) for t in starts]
    assert slots == list(range(slots[0], slots[0] + len(slots)))  # consecutive, none skipped


class _LongExposureMock(MockCameraBackend):
    """Pretends each capture takes as long as its exposure."""

    def capture_frame(self):
        time.sleep(self._exposure_us / 1e6)
        return super().capture_frame()


def test_a_capture_that_cannot_make_the_next_slot_skips_it():
    interval = 0.2
    camera = _LongExposureMock()
    cfg = _config(interval)
    night = cfg.exposure_policy.presets["night"].model_copy(
        update={"exposure_us_min": 300_000, "exposure_us_max": 300_000}  # 0.3 s > one interval
    )
    cfg = cfg.model_copy(
        update={"exposure_policy": cfg.exposure_policy.model_copy(
            update={"presets": {**cfg.exposure_policy.presets, "night": night}})}
    )
    sink = _RecordingSink()
    worker = _worker(camera, cfg, sink)
    worker.start()
    try:
        deadline = time.monotonic() + 10
        while len(sink.times) < 5 and time.monotonic() < deadline:
            time.sleep(0.02)
    finally:
        worker.request_stop()
        worker.join(2)
    gaps = [b - a for a, b in zip(sink.times[1:5], sink.times[2:5], strict=False)]
    # Every other slot: 0.4 s apart, still on the 0.2 s grid.
    assert all(g == pytest.approx(0.4, abs=0.08) for g in gaps)
