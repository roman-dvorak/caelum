from __future__ import annotations

import json
import time
from dataclasses import replace

from caelum.events import FRAME_CAPTURED, EventBus
from caelum.storage import paths
from caelum.storage.writer import StorageWriter
from tests.factories import make_processed_frame


def _wait_until(predicate, timeout: float = 2.0, interval: float = 0.01) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


def test_thumbnail_and_sidecar_are_always_written(tmp_path):
    bus = EventBus()
    writer = StorageWriter(bus, tmp_path)
    try:
        frame = replace(make_processed_frame(), thumbnail_jpeg=b"\xff\xd8fake-jpeg", save_raw=False)
        bus.publish(FRAME_CAPTURED, frame)

        thumb_path = paths.thumbnail_path(tmp_path, frame.metadata.captured_at)
        assert _wait_until(lambda: thumb_path.exists())
        assert thumb_path.read_bytes() == b"\xff\xd8fake-jpeg"

        sidecar = paths.sidecar_path(thumb_path)
        assert sidecar.exists()
        assert json.loads(sidecar.read_text())["exposure_us"] == frame.metadata.exposure_us

        raw_path = paths.raw_path(tmp_path, frame.metadata.captured_at)
        assert not raw_path.exists()
    finally:
        writer.shutdown()


def test_raw_is_only_written_when_save_raw_is_true(tmp_path):
    bus = EventBus()
    writer = StorageWriter(bus, tmp_path)
    try:
        frame = replace(make_processed_frame(), save_raw=True)
        bus.publish(FRAME_CAPTURED, frame)

        raw_path = paths.raw_path(tmp_path, frame.metadata.captured_at)
        assert _wait_until(lambda: raw_path.exists())
        assert paths.sidecar_path(raw_path).exists()
    finally:
        writer.shutdown()
