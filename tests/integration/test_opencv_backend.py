"""Exercises the real OpenCV/V4L2 backend against whatever camera is
plugged into the machine running the tests — skips gracefully if none is
available, since CI/dev machines without a webcam shouldn't fail here."""

from __future__ import annotations

import pytest

from caelum.cameras.opencv_backend import OpenCVBackend
from caelum.config.schema import CameraConfig


@pytest.fixture
def backend():
    cfg = CameraConfig(backend="opencv", sensor_id="0", resolution=(640, 480))
    backend = OpenCVBackend(cfg)
    try:
        backend.open()
    except RuntimeError:
        pytest.skip("no V4L2 camera available in this environment")
    yield backend
    backend.close()


def test_capture_frame_returns_a_real_rgb_image(backend):
    backend.set_controls(exposure_us=10_000, analogue_gain=1.0)
    frame = backend.capture_frame()

    assert frame.image.ndim == 3
    assert frame.image.shape[2] == 3
    assert frame.exposure_us == 10_000
    assert frame.analogue_gain == 1.0


def test_capabilities_reflect_the_negotiated_resolution(backend):
    width, height = backend.capabilities.max_resolution
    frame = backend.capture_frame()
    assert frame.image.shape[:2] == (height, width)


def test_close_then_reopen_works(backend):
    backend.close()
    backend.open()
    frame = backend.capture_frame()
    assert frame.image.ndim == 3
