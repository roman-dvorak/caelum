from __future__ import annotations

import asyncio
import threading
from datetime import UTC, datetime, timedelta

from caelum.capture.frame_store import FrameStore
from caelum.capture.metadata import OverlayElement
from caelum.events import FRAME_METADATA_UPDATED, EventBus
from tests.factories import make_processed_frame


def test_get_latest_and_stats_reflect_the_last_update():
    store = FrameStore()
    assert store.get_latest() is None
    assert store.get_latest_stats() is None

    frame = make_processed_frame()
    store.update(frame)

    assert store.get_latest() is frame
    assert store.get_latest_stats() == frame.stats


async def test_subscribers_receive_frames_pushed_from_another_thread():
    loop = asyncio.get_running_loop()
    store = FrameStore(loop=loop)
    queue = store.subscribe()

    frame = make_processed_frame()
    threading.Thread(target=store.update, args=(frame,)).start()

    received = await asyncio.wait_for(queue.get(), timeout=2.0)
    assert received is frame


async def test_unsubscribe_stops_further_delivery():
    loop = asyncio.get_running_loop()
    store = FrameStore(loop=loop)
    queue = store.subscribe()
    store.unsubscribe(queue)

    store.update(make_processed_frame())
    await asyncio.sleep(0.05)
    assert queue.empty()


def test_set_overlay_replaces_elements_of_latest_frame_and_returns_it():
    store = FrameStore()
    frame = make_processed_frame()
    store.update(frame)

    elements = [OverlayElement(type="detection_box", source="meteor_detection", payload={"x": 0.1})]
    updated = store.set_overlay(frame.metadata.captured_at, elements, "file", b"png")

    assert updated is not None
    assert updated.metadata.overlay_elements == elements
    assert updated.metadata.overlay == "file"
    assert store.get_latest().overlay_png == b"png"


def test_set_overlay_with_no_frame_yet_is_a_noop():
    store = FrameStore()
    assert store.set_overlay(datetime.now(UTC), [], None, None) is None


def test_set_overlay_ignores_a_frame_that_is_no_longer_latest():
    store = FrameStore()
    frame = make_processed_frame()
    store.update(frame)
    stale = frame.metadata.captured_at - timedelta(seconds=30)
    assert store.set_overlay(stale, [OverlayElement(type="x", payload={})], "file", b"png") is None
    assert store.get_latest().overlay_png is None


def test_set_overlay_publishes_frame_metadata_updated_event():
    bus = EventBus()
    received = []
    bus.subscribe(FRAME_METADATA_UPDATED, received.append)

    store = FrameStore(event_bus=bus)
    frame = make_processed_frame()
    store.update(frame)
    store.set_overlay(frame.metadata.captured_at, [OverlayElement(type="x", payload={})], None, None)

    assert len(received) == 1
    assert received[0].metadata.overlay_elements[-1].type == "x"
