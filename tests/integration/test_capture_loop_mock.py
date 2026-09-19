from __future__ import annotations

import threading
import time
from datetime import UTC, datetime

from caelum.cameras.mock_backend import MockCameraBackend
from caelum.capture.calibration import DarkLibrary
from caelum.capture.frame_store import FrameStore, ProcessedFrame
from caelum.capture.worker import CaptureWorker
from caelum.config.manager import ConfigManager
from caelum.control.exposure import ExposureController
from caelum.control.skystate import SkyState
from caelum.control.storage_policy import StoragePolicy
from caelum.events import FRAME_CAPTURED, EventBus


class _FakeSkyStateCalculator:
    """Lets the test flip day/night on demand instead of waiting for real
    dusk — the same need the project plan flags for on-hardware QA (a
    `skystate.override_period` debug config flag serves this in production;
    here we just swap the calculator)."""

    def __init__(self, period: str = "day") -> None:
        self.period = period

    def compute(self, when: datetime | None = None) -> SkyState:
        sun_alt = 30.0 if self.period == "day" else -30.0
        return SkyState(
            timestamp=when or datetime.now(UTC),
            sun_altitude_deg=sun_alt,
            sun_azimuth_deg=180.0,
            moon_altitude_deg=10.0,
            moon_azimuth_deg=90.0,
            moon_illumination=0.5,
            period=self.period,
        )


def _wait_until(predicate, timeout: float = 3.0, interval: float = 0.01) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


async def test_capture_worker_switches_storage_decision_with_sky_state(tmp_path, redis_url):
    config_manager = ConfigManager(
        disk_path=tmp_path / "config.json",
        default_path=None,
        redis_url=redis_url,
        key_prefix="captureloop",
    )
    await config_manager.start()
    try:
        await config_manager.update(
            {
                "storage_policy": {
                    "night_capture_interval_s": 0.02,
                    "day_capture_interval_s": 0.02,
                    "raw_periods": ["night"],
                }
            }
        )

        camera = MockCameraBackend()
        fake_sky = _FakeSkyStateCalculator(period="day")
        event_bus = EventBus()
        captured: list[ProcessedFrame] = []
        lock = threading.Lock()

        def on_frame(frame: ProcessedFrame) -> None:
            with lock:
                captured.append(frame)

        event_bus.subscribe(FRAME_CAPTURED, on_frame)

        worker = CaptureWorker(
            camera_factory=lambda _cfg: camera,
            config_manager=config_manager,
            skystate_calculator=fake_sky,
            exposure_controller=ExposureController(),
            storage_policy=StoragePolicy(),
            dark_library=DarkLibrary(darks_dir=None),
            frame_store=FrameStore(),
            event_bus=event_bus,
            sky_state_refresh_interval_s=0.0,  # pick up period flips every cycle
        )
        worker.start()
        try:
            assert _wait_until(lambda: len(captured) >= 3), "worker never produced frames"
            with lock:
                day_frames = list(captured)
            assert all(f.save_raw is False for f in day_frames)
            assert all(f.metadata.sky_state.period == "day" for f in day_frames)

            fake_sky.period = "night"
            with lock:
                seen_before_switch = len(captured)
            assert _wait_until(lambda: len(captured) >= seen_before_switch + 3)
            with lock:
                new_frames = captured[seen_before_switch:]
            assert all(f.save_raw is True for f in new_frames)
            assert all(f.metadata.sky_state.period == "night" for f in new_frames)
        finally:
            worker.request_stop()
            worker.join(timeout=2.0)
            assert not worker.is_alive()
    finally:
        await config_manager.stop()


async def test_capture_worker_updates_frame_store(tmp_path, redis_url):
    config_manager = ConfigManager(
        disk_path=tmp_path / "config.json", default_path=None, redis_url=redis_url, key_prefix="captureloop2"
    )
    await config_manager.start()
    try:
        await config_manager.update(
            {"storage_policy": {"night_capture_interval_s": 0.02, "day_capture_interval_s": 0.02}}
        )
        frame_store = FrameStore()
        worker = CaptureWorker(
            camera_factory=lambda _cfg: MockCameraBackend(),
            config_manager=config_manager,
            skystate_calculator=_FakeSkyStateCalculator(period="day"),
            exposure_controller=ExposureController(),
            storage_policy=StoragePolicy(),
            dark_library=DarkLibrary(darks_dir=None),
            frame_store=frame_store,
            event_bus=EventBus(),
        )
        worker.start()
        try:
            assert _wait_until(lambda: frame_store.get_latest() is not None)
            latest = frame_store.get_latest()
            assert latest is not None
            assert latest.thumbnail_jpeg[:2] == b"\xff\xd8"  # JPEG magic bytes
            assert frame_store.get_latest_stats() is not None
        finally:
            worker.request_stop()
            worker.join(timeout=2.0)
    finally:
        await config_manager.stop()
