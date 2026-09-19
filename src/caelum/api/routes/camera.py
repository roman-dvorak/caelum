from __future__ import annotations

import glob

from fastapi import APIRouter, Depends

from caelum.api.deps import get_capture_worker, get_config_manager
from caelum.api.schemas import CameraModeRequest, CameraOptionsResponse, ExposureOverrideRequest
from caelum.capture.worker import CaptureWorker
from caelum.config.manager import ConfigManager
from caelum.control.exposure import ExposureTarget

router = APIRouter()


@router.get("/camera/options", response_model=CameraOptionsResponse)
def get_camera_options(
    worker: CaptureWorker = Depends(get_capture_worker),
    config_manager: ConfigManager = Depends(get_config_manager),
) -> CameraOptionsResponse:
    """What can this host actually be pointed at?

    Exists so choosing a camera in the web UI is a menu rather than a guess
    at a device path. `active` is what the capture thread currently holds
    open, which lags `config.camera` by up to one cycle after a change — the
    difference is how the UI can tell "applied" from "requested".
    """
    active = worker.camera_config
    return CameraOptionsResponse(
        backends=["mock", "picamera2", "opencv"],
        v4l2_devices=sorted(glob.glob("/dev/video*")),
        configured=config_manager.current.camera,
        active=active,
        active_backend_class=worker.camera_backend_name,
        applied=active is not None and active == config_manager.current.camera,
    )


@router.post("/camera/mode")
def set_camera_mode(body: CameraModeRequest, worker: CaptureWorker = Depends(get_capture_worker)) -> dict:
    worker.stream_mode.set(body.stream_mode)
    return {"stream_mode": worker.stream_mode.enabled}


@router.post("/camera/exposure-override")
def set_exposure_override(
    body: ExposureOverrideRequest, worker: CaptureWorker = Depends(get_capture_worker)
) -> dict:
    if body.clear or (body.exposure_us is None and body.analogue_gain is None):
        worker.manual_exposure.set(None)
        return {"override": None}

    current = worker.current_target
    target = ExposureTarget(
        exposure_us=body.exposure_us if body.exposure_us is not None else current.exposure_us,
        analogue_gain=body.analogue_gain if body.analogue_gain is not None else current.analogue_gain,
    )
    worker.manual_exposure.set(target)
    return {"override": {"exposure_us": target.exposure_us, "analogue_gain": target.analogue_gain}}
