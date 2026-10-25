"""A `Picamera2()` constructor that fails (camera busy) must not leak its
notification pipe — retried every cycle, that used to exhaust the process's
file descriptors and take the HTTP server down with it."""

from __future__ import annotations

import os

import numpy as np
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


# ---- copying the frame out of the camera buffers ----------------------------


class _FakeMappedArray:
    """picamera2's MappedArray with reshape=False: the flat mapped buffer."""

    def __init__(self, request, stream, reshape=True, write=True) -> None:
        assert reshape is False
        self.array = request.buffers[stream]

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        pass


class _FakeRequest:
    """Buffers as the ISP lays them out: rows padded to the stride."""

    def __init__(self, main_cfg, raw_cfg, rng) -> None:
        self.cfg = {"main": main_cfg, "raw": raw_cfg}
        self.buffers = {
            name: rng.integers(0, 256, cfg["size"][1] * cfg["stride"] + 4096, dtype=np.uint8)
            for name, cfg in self.cfg.items()
        }

    def make_array(self, name):
        # What picamera2's helpers.make_array does.
        cfg = self.cfg[name]
        width, height = cfg["size"]
        rows = np.array(self.buffers[name][: height * cfg["stride"]]).reshape(height, cfg["stride"])
        if name == "raw":
            return rows
        return np.ascontiguousarray(rows[:, : width * 3]).reshape(height, width, 3)


def test_direct_copy_matches_picamera2s_own_copy(monkeypatch):
    monkeypatch.setattr(picamera2_backend, "MappedArray", _FakeMappedArray)
    backend = object.__new__(picamera2_backend.Picamera2Backend)
    # IMX477 full resolution: 4056*3 isn't a multiple of 64, so rows are padded.
    backend._main_config = {"format": "BGR888", "size": (4056, 30), "stride": 12224}
    backend._raw_config = {"format": "SBGGR12_CSI2P", "size": [4056, 30], "stride": 6112}
    backend._direct_copy = None
    request = _FakeRequest(
        dict(backend._main_config), {"size": (4056, 30), "stride": 6112}, np.random.default_rng(1)
    )
    rgb_shape, raw_shape = backend.frame_layout()
    rgb, raw = np.empty(rgb_shape, np.uint8), np.empty(raw_shape, np.uint8)

    image, raw_out = backend._copy_out(request, (rgb, raw))

    assert image is rgb and raw_out is raw
    assert backend._direct_copy is True  # checked against make_array on the first frame
    np.testing.assert_array_equal(rgb, request.make_array("main"))
    np.testing.assert_array_equal(raw, request.make_array("raw"))
