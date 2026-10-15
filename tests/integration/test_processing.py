"""Both FrameSinks end-to-end: what lands on disk, what gets published, and
— for the separate-process one — slot back-pressure, crash recovery and
shared-memory cleanup."""

from __future__ import annotations

import json
import os
import signal
import threading
import time
from datetime import timedelta
from pathlib import Path

import pytest

from caelum.capture.frame_store import FrameStore, ProcessedFrame
from caelum.events import FRAME_CAPTURED, EventBus
from caelum.processing.client import ProcessingClient
from caelum.processing.inline import InlineFrameSink
from caelum.storage import paths
from tests.factories import make_image, make_raw_frame, make_submission
from tests.tiff_tags import read_ifd0


def _wait_until(predicate, timeout: float = 30.0, interval: float = 0.02) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


class _Collector:
    def __init__(self, bus: EventBus) -> None:
        self.frames: list[ProcessedFrame] = []
        self._lock = threading.Lock()
        bus.subscribe(FRAME_CAPTURED, self._on_frame)

    def _on_frame(self, frame: ProcessedFrame) -> None:
        with self._lock:
            self.frames.append(frame)

    def __len__(self) -> int:
        with self._lock:
            return len(self.frames)


def _our_segments() -> list[Path]:
    return list(Path("/dev/shm").glob(f"caelum-{os.getpid()}-*"))


def _assert_thumbnail_written(data_dir: Path, submission) -> Path:
    thumb = paths.thumbnail_path(data_dir, submission.raw.captured_at)
    assert thumb.suffix == ".webp"
    assert thumb.read_bytes()[:4] == b"RIFF" and thumb.read_bytes()[8:12] == b"WEBP"
    sidecar = json.loads(paths.sidecar_path(thumb).read_text())
    assert sidecar["exposure_us"] == submission.raw.exposure_us
    assert sidecar["sky_state"]["period"] == "night"
    return thumb


# ---- inline -----------------------------------------------------------------


def test_inline_sink_publishes_and_writes_webp_thumbnail(tmp_path):
    bus, store = EventBus(), FrameStore()
    collected = _Collector(bus)
    sink = InlineFrameSink(store, bus, tmp_path)
    submission = make_submission(save_raw=False)

    assert sink.submit(submission) is True

    assert len(collected) == 1
    frame = collected.frames[0]
    assert frame.thumbnail_jpeg[:2] == b"\xff\xd8"  # live stream stays JPEG
    assert frame.stats.median == pytest.approx(60.0)
    assert store.get_latest() is frame
    _assert_thumbnail_written(tmp_path, submission)
    assert not paths.raw_path(tmp_path, submission.raw.captured_at).exists()


def test_inline_sink_writes_dng_only_when_asked_and_raw_exists(tmp_path):
    pytest.importorskip("pidng")
    sink = InlineFrameSink(FrameStore(), EventBus(), tmp_path)

    with_raw = make_submission(save_raw=True)
    sink.submit(with_raw)
    raw_path = paths.raw_path(tmp_path, with_raw.raw.captured_at)
    assert raw_path.suffix == ".dng"
    tags = read_ifd0(raw_path.read_bytes())
    assert tags[33434] == [(10_000_000, 1_000_000)]
    assert b'caelum:sky_period="night"' in tags[700]
    assert json.loads(paths.sidecar_path(raw_path).read_text())["analogue_gain"] == 2.0

    # A backend without a raw stream (mock/opencv): nothing to write.
    later = with_raw.raw.captured_at + timedelta(seconds=30)
    no_raw = make_submission(raw_frame=make_raw_frame(captured_at=later, with_raw=False), save_raw=True)
    sink.submit(no_raw)
    assert not paths.raw_path(tmp_path, no_raw.raw.captured_at).exists()


# ---- separate process -------------------------------------------------------


@pytest.fixture
def client(tmp_path):
    bus, store = EventBus(), FrameStore()
    collected = _Collector(bus)
    processing = ProcessingClient(store, bus, tmp_path, slots=2, job_timeout_s=60.0)
    processing.start()
    try:
        yield processing, collected, store
    finally:
        processing.stop()


def test_process_sink_processes_in_a_separate_process(client, tmp_path):
    pytest.importorskip("pidng")
    processing, collected, store = client
    submission = make_submission(save_raw=True)

    assert processing.submit(submission) is True
    assert _wait_until(lambda: processing.stats["processed"] == 1)

    assert len(collected) == 1
    frame = collected.frames[0]
    assert frame.thumbnail_jpeg[:2] == b"\xff\xd8"
    assert frame.image.shape == submission.raw.image.shape
    assert frame.image.mean() == pytest.approx(60.0)
    assert frame.save_raw is True
    _assert_thumbnail_written(tmp_path, submission)
    assert paths.raw_path(tmp_path, submission.raw.captured_at).read_bytes()[:4] == b"II*\x00"

    stats = processing.stats
    assert stats["worker_alive"] and stats["worker_pid"] != os.getpid()
    assert stats["in_flight"] == 0 and stats["dropped"] == 0


def test_frames_are_dropped_not_queued_when_all_slots_are_busy(client):
    processing, _collected, _store = client
    big = make_raw_frame(image=make_image(width=1600, height=1200, fill=40))
    results = [processing.submit(make_submission(raw_frame=big, save_raw=True)) for _ in range(6)]
    assert results[:2] == [True, True]
    assert False in results
    assert processing.stats["dropped"] >= 1
    assert _wait_until(lambda: processing.stats["in_flight"] == 0)
    # Slots come back: a later frame goes through again.
    assert processing.submit(make_submission()) is True


def test_a_killed_worker_is_restarted(client):
    processing, collected, _store = client
    assert processing.submit(make_submission()) is True
    assert _wait_until(lambda: len(collected) == 1)
    old_pid = processing.stats["worker_pid"]

    os.kill(old_pid, signal.SIGKILL)
    assert _wait_until(
        lambda: processing.stats["worker_alive"] and processing.stats["worker_pid"] != old_pid
    )
    assert processing.stats["restarts"] == 1
    assert processing.submit(make_submission()) is True
    assert _wait_until(lambda: len(collected) == 2)


def test_resolution_change_reallocates_slots(client):
    processing, collected, _store = client
    processing.submit(make_submission())
    assert _wait_until(lambda: len(collected) == 1)
    bigger = make_raw_frame(image=make_image(width=320, height=240))
    processing.submit(make_submission(raw_frame=bigger))
    assert _wait_until(lambda: len(collected) == 2)
    assert collected.frames[1].image.shape == (240, 320, 3)


def test_stop_leaves_no_shared_memory_behind(tmp_path):
    processing = ProcessingClient(FrameStore(), EventBus(), tmp_path, slots=2)
    processing.start()
    processing.submit(make_submission())
    assert _our_segments()
    processing.stop()
    assert _our_segments() == []
    assert processing.stats["worker_alive"] is False
