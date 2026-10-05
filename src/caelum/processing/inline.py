"""Synchronous `FrameSink`: runs the processing pipeline on the submitting
(capture) thread. For tests and debugging — `processing.mode: "inline"`."""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any

from caelum.capture.calibration import DarkLibrary
from caelum.capture.frame_store import FrameStore, ProcessedFrame
from caelum.events import FRAME_CAPTURED, EventBus

from . import pipeline
from .jobs import FrameInfo, FrameSubmission

logger = logging.getLogger(__name__)


class InlineFrameSink:
    def __init__(
        self,
        frame_store: FrameStore,
        event_bus: EventBus,
        data_dir: Path | None = None,
        dark_library: DarkLibrary | None = None,
    ) -> None:
        self._frame_store = frame_store
        self._event_bus = event_bus
        self._data_dir = data_dir
        self._dark_library = dark_library or DarkLibrary(darks_dir=None)
        self._lock = threading.Lock()
        self._processed = 0
        self._failed = 0
        self._last_timings: dict[str, float] = {}

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    @property
    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "mode": "inline",
                "processed": self._processed,
                "failed": self._failed,
                "dropped": 0,
                "in_flight": 0,
                "last_timings_ms": dict(self._last_timings),
            }

    def submit(self, submission: FrameSubmission) -> bool:
        info = FrameInfo.from_submission(submission)
        timer = pipeline.Timer()
        try:
            calibrated, stats, live_jpeg, webp = pipeline.analyze(
                submission.raw.image, info, self._dark_library, timer
            )
            metadata = pipeline.build_metadata(info, stats)
            if self._data_dir is not None:
                pipeline.persist_thumbnail(self._data_dir, metadata, webp, info)
                timer.lap("write_thumbnail")
        except Exception:
            logger.exception("Processing frame captured at %s failed", info.captured_at)
            with self._lock:
                self._failed += 1
            return True

        if not info.is_hidden_member:  # only a set's representative is published
            processed = ProcessedFrame(
                image=calibrated,
                thumbnail_jpeg=live_jpeg,
                stats=stats,
                metadata=metadata,
                save_raw=submission.save_raw,
            )
            self._frame_store.update(processed)
            self._event_bus.publish(FRAME_CAPTURED, processed)

        raw = submission.raw.raw_bayer
        if submission.save_raw and raw is not None and info.raw_config is not None and self._data_dir is not None:
            try:
                pipeline.persist_raw(self._data_dir, info, metadata, stats, raw)
                timer.lap("write_raw")
            except Exception:
                logger.exception("Writing raw DNG for %s failed", info.captured_at)
        with self._lock:
            self._processed += 1
            self._last_timings = timer.timings_ms
        return True

    def submit_set(self, submissions: list[FrameSubmission]) -> bool:
        for submission in submissions:
            self.submit(submission)
        return True
