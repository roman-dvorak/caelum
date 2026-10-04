"""End-to-end proof that a real sky-period transition, dispatched through
the real DerivativePool, produces a real .mp4 via a real ffmpeg subprocess
— the strongest available verification short of a running camera process."""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta

import pytest

from caelum.capture.frame_store import FrameStore
from caelum.config.schema import AppConfig, PluginConfig
from caelum.derivatives.pool import DerivativePool
from caelum.derivatives.timelapse import TimelapseWorker
from caelum.derivatives.video_encode import ffmpeg_available
from caelum.events import FRAME_CAPTURED, EventBus
from caelum.storage import paths
from tests.factories import make_processed_frame


class _StubConfigManager:
    def __init__(self, config: AppConfig) -> None:
        self.current = config


@pytest.mark.skipif(not ffmpeg_available(), reason="ffmpeg not installed")
def test_period_transition_produces_a_real_timelapse_file(tmp_path):
    import cv2
    import numpy as np

    data_dir = tmp_path
    start = datetime(2026, 9, 20, 18, 0, tzinfo=UTC)

    # Seed 12 real, decodable thumbnail JPEGs + sidecars across the night window.
    timestamps = [start + timedelta(minutes=i * 10) for i in range(12)]
    for when in timestamps:
        thumb_path = paths.thumbnail_path(data_dir, when)
        thumb_path.parent.mkdir(parents=True, exist_ok=True)
        image = np.full((24, 32, 3), 50, dtype=np.uint8)
        cv2.imwrite(str(thumb_path), image)
        frame = make_processed_frame(captured_at=when, period="night")
        paths.sidecar_path(thumb_path).write_text(frame.metadata.model_dump_json())

    config = AppConfig()
    config.plugins["timelapse"] = PluginConfig(
        enabled=True,
        order=50,
        settings={"generate_clean": True, "generate_with_overlay": False, "fps": 10, "min_frames": 5},
    )

    event_bus = EventBus()
    frame_store = FrameStore()
    pool = DerivativePool(event_bus, frame_store, data_dir, config_manager=_StubConfigManager(config))
    pool.register(TimelapseWorker(config.plugins["timelapse"].settings))

    # Feed the real frames, then one frame past the period boundary to
    # trigger the "night just ended" transition.
    for when in timestamps:
        event_bus.publish(FRAME_CAPTURED, make_processed_frame(captured_at=when, period="night"))
    transition_at = timestamps[-1] + timedelta(minutes=10)
    event_bus.publish(FRAME_CAPTURED, make_processed_frame(captured_at=transition_at, period="astronomical_twilight"))

    # Dispatch runs off-thread on the pool's own ThreadPoolExecutor — poll
    # for the encoded output rather than pool.shutdown(), which cancels
    # not-yet-started queued futures instead of waiting for them.
    timelapse_dir = data_dir / "timelapses"
    deadline = time.monotonic() + 30.0
    produced: list = []
    while time.monotonic() < deadline:
        produced = list(timelapse_dir.rglob("*_night_clean.mp4"))
        if produced:
            break
        time.sleep(0.1)

    pool.shutdown()

    assert len(produced) == 1
    assert produced[0].stat().st_size > 0
