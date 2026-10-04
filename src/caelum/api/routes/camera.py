from __future__ import annotations

import glob

import numpy as np
from fastapi import APIRouter, Depends, HTTPException

from caelum.api.deps import get_capture_worker, get_config_manager, get_frame_store, get_settings
from caelum.api.schemas import (
    CameraModeRequest,
    CameraOptionsResponse,
    ExposureOverrideRequest,
    WhiteBalanceAutoCalibrateRequest,
    WhiteBalanceRequest,
    WhiteBalanceResponse,
)
from caelum.capture.frame_store import FrameStore
from caelum.capture.worker import CaptureWorker
from caelum.config.manager import ConfigManager
from caelum.control.exposure import ExposureTarget
from caelum.settings import Settings

router = APIRouter()


@router.get("/camera/options", response_model=CameraOptionsResponse)
def get_camera_options(
    worker: CaptureWorker = Depends(get_capture_worker),
    config_manager: ConfigManager = Depends(get_config_manager),
    settings: Settings = Depends(get_settings),
) -> CameraOptionsResponse:
    """What can this host actually be pointed at?

    Exists so choosing a camera in the web UI is a menu rather than a guess
    at a device path. `active` is what the capture thread currently holds
    open (already resolved through any `CAELUM_CAMERA_BACKEND` override —
    see `CaptureWorker._ensure_camera`), which lags `config.camera` by up to
    one cycle after a change — the difference is how the UI can tell
    "applied" from "requested".
    """
    active = worker.camera_config
    return CameraOptionsResponse(
        backends=["mock", "picamera2", "opencv"],
        v4l2_devices=sorted(glob.glob("/dev/video*")),
        configured=config_manager.current.camera,
        active=active,
        active_backend_class=worker.camera_backend_name,
        applied=active is not None and active == config_manager.current.camera,
        backend_override=settings.camera_backend_override,
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


@router.post("/camera/white-balance", response_model=WhiteBalanceResponse)
async def set_white_balance(
    body: WhiteBalanceRequest,
    worker: CaptureWorker = Depends(get_capture_worker),
    config_manager: ConfigManager = Depends(get_config_manager),
) -> WhiteBalanceResponse:
    """Live-apply manual gains and persist them as the camera's default."""
    worker.white_balance_override.request(body.red_gain, body.blue_gain, auto=False)
    try:
        updated = await config_manager.update(
            {"camera": {"wb_auto": False, "wb_red_gain": body.red_gain, "wb_blue_gain": body.blue_gain}}
        )
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return WhiteBalanceResponse(red_gain=updated.camera.wb_red_gain, blue_gain=updated.camera.wb_blue_gain, auto=False)


@router.post("/camera/white-balance/auto-calibrate", response_model=WhiteBalanceResponse)
async def auto_calibrate_white_balance(
    body: WhiteBalanceAutoCalibrateRequest,
    worker: CaptureWorker = Depends(get_capture_worker),
    frame_store: FrameStore = Depends(get_frame_store),
    config_manager: ConfigManager = Depends(get_config_manager),
) -> WhiteBalanceResponse:
    """Derive gains that make a selected patch of the latest frame neutral
    gray, by scaling red/blue up (or down) to match green — the classic
    "gray world" white-balance calibration, limited to a user-picked patch
    so a colorful scene doesn't get treated as gray."""
    latest = frame_store.get_latest()
    if latest is None:
        raise HTTPException(status_code=409, detail="No captured frame available yet")

    image = latest.image
    height, width = image.shape[0], image.shape[1]
    x0 = int(body.x * width)
    y0 = int(body.y * height)
    x1 = min(width, x0 + max(1, int(body.w * width)))
    y1 = min(height, y0 + max(1, int(body.h * height)))
    patch = image[y0:y1, x0:x1]
    if patch.size == 0:
        raise HTTPException(status_code=422, detail="Selected patch is empty")

    mean = patch.reshape(-1, patch.shape[-1]).mean(axis=0) if patch.ndim == 3 else np.array([patch.mean()] * 3)
    mean_r, mean_g, mean_b = (float(mean[0]), float(mean[1]), float(mean[2])) if len(mean) >= 3 else (1.0, 1.0, 1.0)
    if mean_r <= 0.0 or mean_b <= 0.0:
        raise HTTPException(status_code=422, detail="Selected patch is too dark to calibrate from")

    red_gain = min(8.0, max(0.1, mean_g / mean_r))
    blue_gain = min(8.0, max(0.1, mean_g / mean_b))

    worker.white_balance_override.request(red_gain, blue_gain, auto=False)
    try:
        updated = await config_manager.update(
            {"camera": {"wb_auto": False, "wb_red_gain": red_gain, "wb_blue_gain": blue_gain}}
        )
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return WhiteBalanceResponse(red_gain=updated.camera.wb_red_gain, blue_gain=updated.camera.wb_blue_gain, auto=False)
