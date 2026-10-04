"""`CaptureWorker._ensure_camera` must record the *resolved* camera config
(after `resolve_camera_config`, e.g. a `CAELUM_CAMERA_BACKEND` override) —
not the raw requested one — so `camera_config` (and therefore
`GET /api/camera/options`'s `active`/`applied` fields) never claims a
backend is open that isn't. See main.py's `resolve_camera_config`."""

from __future__ import annotations

from caelum.cameras.mock_backend import MockCameraBackend
from caelum.capture.calibration import DarkLibrary
from caelum.capture.frame_store import FrameStore
from caelum.capture.worker import CaptureWorker
from caelum.config.schema import CameraConfig
from caelum.control.exposure import ExposureController
from caelum.control.storage_policy import StoragePolicy
from caelum.events import EventBus


def _make_worker(resolve_camera_config=None, opens=None) -> CaptureWorker:
    opens = opens if opens is not None else []

    def camera_factory(cfg: CameraConfig) -> MockCameraBackend:
        opens.append(cfg)
        return MockCameraBackend()

    return CaptureWorker(
        camera_factory=camera_factory,
        config_manager=None,
        skystate_calculator=None,
        exposure_controller=ExposureController(),
        storage_policy=StoragePolicy(),
        dark_library=DarkLibrary(darks_dir=None),
        frame_store=FrameStore(),
        event_bus=EventBus(),
        resolve_camera_config=resolve_camera_config,
    )


def test_camera_config_reflects_the_override_not_the_request():
    requested = CameraConfig(backend="opencv", sensor_id="/dev/video0", resolution=(640, 480))
    worker = _make_worker(resolve_camera_config=lambda cfg: cfg.model_copy(update={"backend": "mock"}))

    worker._ensure_camera(requested)

    assert worker.camera_config.backend == "mock"
    assert worker.camera_backend_name == "MockCameraBackend"


def test_camera_is_not_reopened_when_the_resolved_config_is_unchanged():
    opens: list[CameraConfig] = []
    # Two different requested backends that both resolve to "mock" — an
    # override pinning the backend regardless of what the config asks for.
    worker = _make_worker(resolve_camera_config=lambda cfg: cfg.model_copy(update={"backend": "mock"}), opens=opens)

    worker._ensure_camera(CameraConfig(backend="opencv", sensor_id="0", resolution=(640, 480)))
    worker._ensure_camera(CameraConfig(backend="picamera2", sensor_id="0", resolution=(640, 480)))

    assert len(opens) == 1  # no needless reopen — the resolved config never actually changed
