from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pytest

from caelum.derivatives.meteor_detection import MeteorDetectionWorker, detect_streak
from tests.factories import make_processed_frame


@pytest.fixture
def executor():
    with ThreadPoolExecutor(max_workers=1) as ex:
        yield ex


def _blank(size: int = 100) -> np.ndarray:
    return np.zeros((size, size), dtype=np.uint8)


def test_detect_streak_finds_an_injected_elongated_bright_line():
    prev = _blank()
    curr = _blank()
    curr[40:42, 10:90] = 255  # a long thin bright streak
    bbox = detect_streak(prev, curr, threshold=40.0)
    assert bbox is not None
    x, y, w, h = bbox
    assert w / h >= 3.0


def test_detect_streak_ignores_a_static_pair():
    prev = _blank()
    curr = _blank()
    assert detect_streak(prev, curr, threshold=40.0) is None


def test_detect_streak_ignores_a_compact_round_blob():
    prev = _blank()
    curr = _blank()
    curr[45:55, 45:55] = 255  # roughly square, not elongated
    assert detect_streak(prev, curr, threshold=40.0) is None


def test_worker_emits_overlay_and_derivative_once_per_detection(executor):
    worker = MeteorDetectionWorker({"diff_threshold": 40.0, "max_dim": 100})
    # Injected the way DerivativePool.register() does it in production.
    worker.process_pool = executor

    blank_image = np.zeros((100, 100, 3), dtype=np.uint8)
    streak_image = np.zeros((100, 100, 3), dtype=np.uint8)
    streak_image[40:42, 10:90, :] = 255

    frame1 = make_processed_frame(image=blank_image)
    worker.on_frame(frame1)
    assert worker.provide_overlay_elements(frame1) == []
    assert worker.create_derivative({"frame": frame1}) is None

    frame2 = make_processed_frame(image=streak_image)
    worker.on_frame(frame2)
    elements = worker.provide_overlay_elements(frame2)
    assert len(elements) == 1
    assert elements[0].type == "detection_box"
    assert elements[0].source == "meteor_detection"

    derivative = worker.create_derivative({"frame": frame2})
    assert derivative is not None
    assert derivative.kind == "meteor_crop"
    assert "bbox" in derivative.metadata

    # the detection is consumed — a third, unchanged frame should be quiet
    frame3 = make_processed_frame(image=streak_image)
    worker.on_frame(frame3)
    assert worker.provide_overlay_elements(frame3) == []
    assert worker.create_derivative({"frame": frame3}) is None
