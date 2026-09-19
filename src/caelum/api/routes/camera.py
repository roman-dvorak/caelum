from __future__ import annotations

from fastapi import APIRouter, Depends

from caelum.api.deps import get_capture_worker
from caelum.api.schemas import CameraModeRequest, ExposureOverrideRequest
from caelum.capture.worker import CaptureWorker
from caelum.control.exposure import ExposureTarget

router = APIRouter()


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
