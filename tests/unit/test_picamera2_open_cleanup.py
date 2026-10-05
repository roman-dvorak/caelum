"""A `Picamera2()` constructor that fails (camera busy) must not leak its
notification pipe — retried every cycle, that used to exhaust the process's
file descriptors and take the HTTP server down with it."""

from __future__ import annotations

import os

import pytest

from caelum.cameras import picamera2_backend
from caelum.config.schema import CameraConfig


class _FakeManager:
    def __init__(self) -> None:
        self.cameras: dict[int, object] = {}

    def add(self, index: int, camera: object) -> None:
        self.cameras[index] = camera

    def cleanup(self, index: int) -> None:
        del self.cameras[index]


class _BusyPicamera2:
    """Mimics the order of operations in picamera2's real constructor up to
    the failing camera acquire."""

    _cm = _FakeManager()

    def __init__(self) -> None:
        self.notifyme_r, self.notifyme_w = os.pipe2(os.O_NONBLOCK)
        self.notifymeread = os.fdopen(self.notifyme_r, "rb")
        self._preview = None
        self.is_open = False
        self._cm.add(0, self)
        self.camera_idx = 0
        raise RuntimeError("Failed to acquire camera: Device or resource busy")

    def close(self) -> None:
        if not self.is_open:
            return


def _open_fds() -> int:
    return len(os.listdir("/proc/self/fd"))


@pytest.fixture
def busy_camera(monkeypatch):
    monkeypatch.setattr(picamera2_backend, "Picamera2", _BusyPicamera2)
    monkeypatch.setattr(picamera2_backend, "_manager_suspect", False)
    _BusyPicamera2._cm = _FakeManager()
    return _BusyPicamera2


def test_failed_open_does_not_leak_file_descriptors(busy_camera):
    backend = picamera2_backend.Picamera2Backend(CameraConfig(backend="picamera2"))
    before = _open_fds()
    for _ in range(50):
        with pytest.raises(RuntimeError, match="busy"):
            backend.open()
    assert _open_fds() == before
    assert busy_camera._cm.cameras == {}  # nor a dangling camera-manager entry


def test_failed_open_resets_the_camera_manager_before_the_next_attempt(busy_camera):
    resets = []
    busy_camera._cm.reset = lambda: resets.append(True)
    backend = picamera2_backend.Picamera2Backend(CameraConfig(backend="picamera2"))
    with pytest.raises(RuntimeError):
        backend.open()
    assert resets == []
    with pytest.raises(RuntimeError):
        backend.open()  # the second attempt starts from a fresh manager
    assert resets == [True]
