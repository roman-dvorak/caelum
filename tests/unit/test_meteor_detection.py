from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import cv2
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


def test_detect_streak_finds_a_diagonal_streak():
    # The bounding box of a 45 degree line is square — elongation must come
    # from the rotated rectangle, not from it.
    prev = _blank()
    curr = _blank()
    cv2.line(curr, (10, 10), (90, 90), 255, 1)
    assert detect_streak(prev, curr, threshold=40.0) is not None


def test_detect_streak_reports_a_trail_only_when_it_appears_not_when_it_goes():
    with_trail = _blank()
    with_trail[40:42, 10:90] = 255
    assert detect_streak(_blank(), with_trail, threshold=40.0) is not None
    assert detect_streak(with_trail, _blank(), threshold=40.0) is None


def test_detect_streak_ignores_a_global_brightness_step():
    # An auto-exposure change raises everything at once.
    prev = np.full((100, 100), 20, dtype=np.uint8)
    curr = np.full((100, 100), 120, dtype=np.uint8)
    assert detect_streak(prev, curr, threshold=40.0) is None


def test_detect_streak_ignores_a_cloud_lighting_up_part_of_the_frame():
    prev = _blank()
    curr = _blank()
    curr[:, :50] = 150
    curr[40:42, 60:95] = 255  # even with something streak-like next to it
    assert detect_streak(prev, curr, threshold=40.0) is None


def test_detect_streak_ignores_pure_noise():
    rng = np.random.default_rng(1)
    prev = rng.normal(30, 6, (100, 100)).clip(0, 255).astype(np.uint8)
    curr = rng.normal(30, 6, (100, 100)).clip(0, 255).astype(np.uint8)
    assert detect_streak(prev, curr, threshold=10.0) is None


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
