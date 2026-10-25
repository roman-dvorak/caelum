"""Captures are evenly spaced on a wall-clock grid `capture_interval_s`
apart, with the start of each exposure on a grid slot — however long each
capture takes and however much the exposure changes."""

from __future__ import annotations

import dataclasses
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
        self.settings: list[dict | None] = []
        self.lock = threading.Lock()

    def start(self) -> None: ...

    def stop(self) -> None: ...

    stats: dict = {}

    def reserve(self, rgb_shape, raw_shape):
        return None

    def release(self, slot) -> None: ...

    def submit(self, submission) -> bool:
        with self.lock:
            self.times.append(time.monotonic())
            self.captured.append(submission.raw.captured_at)
            self.settings.append(submission.raw.capture_settings)
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
    """Pretends each capture takes as long as its exposure, and stamps the
    frame with the exposure's start — as the real camera backend does."""

    def capture_frame(self):
        started = datetime.now(UTC)
        time.sleep(self._exposure_us / 1e6)
        return dataclasses.replace(super().capture_frame(), captured_at=started)


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
    slots: list[float] = []
    wait_for_slot = worker._wait_for_slot

    def recording_wait(interval_s):
        due = wait_for_slot(interval_s)
        if due is not None:
            slots.append(due)
        return due

    worker._wait_for_slot = recording_wait
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
    # The exposure *starts* on the slot it was aimed at (within the start
    # latency) — not half an exposure earlier — though it outlasts the
    # interval. The frame is stamped with the slot; the measured start is
    # in its metadata.
    for slot, captured, settings in zip(slots[1:5], sink.captured[1:5], sink.settings[1:5], strict=False):
        assert captured.timestamp() == pytest.approx(slot)
        timing = settings["timing"]
        started = datetime.fromisoformat(timing["exposure_started_at"]).timestamp()
        assert -0.12 <= started - slot <= 0.05
        assert timing["start_offset_s"] == pytest.approx(started - slot, abs=1e-3)
        assert datetime.fromisoformat(timing["scheduled_at"]).timestamp() == pytest.approx(slot)


def test_a_start_far_from_its_slot_keeps_its_own_time():
    from caelum.capture.worker import stamp_slot

    raw = MockCameraBackend()
    raw.open()
    frame = raw.capture_frame()
    late = stamp_slot(frame, frame.captured_at.timestamp() - 5.0)
    assert late.captured_at == frame.captured_at
    assert late.capture_settings["timing"]["start_offset_s"] == pytest.approx(5.0)
    near = stamp_slot(frame, frame.captured_at.timestamp() - 0.3)
    assert near.captured_at.timestamp() == pytest.approx(frame.captured_at.timestamp() - 0.3)


def test_stream_mode_cuts_a_long_slot_wait_short():
    """Turning stream mode on while waiting for a far-off slot captures on
    the new, fast grid straight away — not after the old interval."""
    cfg = _config(30.0)
    cfg = cfg.model_copy(
        update={"storage_policy": cfg.storage_policy.model_copy(update={"realtime_stream_fps": 4.0})}
    )
    sink = _RecordingSink()
    worker = _worker(MockCameraBackend(), cfg, sink)
    worker.start()
    try:
        deadline = time.monotonic() + 35
        while len(sink.times) < 1 and time.monotonic() < deadline:
            time.sleep(0.02)
        assert sink.times, "no first frame"
        time.sleep(0.3)  # now waiting for a slot up to 30 s away
        switched = time.monotonic()
        worker.stream_mode.set(True)
        while len(sink.times) < 3 and time.monotonic() - switched < 5:
            time.sleep(0.02)
        assert len(sink.times) >= 3
        assert sink.times[1] - switched < 1.0  # next capture on the 0.25 s grid
    finally:
        worker.request_stop()
        worker.join(2)
    assert not worker.is_alive()  # the stop also cut the wait short
