from __future__ import annotations

from fastapi import APIRouter, Depends

from caelum.api.deps import get_capture_worker, get_config_manager, get_frame_store, get_skystate_calculator
from caelum.api.schemas import ExposureDiagnosticsResponse, SkyStateResponse, StatusResponse
from caelum.capture.frame_store import FrameStore
from caelum.capture.worker import CaptureWorker
from caelum.config.manager import ConfigManager
from caelum.control.exposure import ExposureController
from caelum.control.skystate import SkyStateCalculator

router = APIRouter()

# Stateless (no instance fields) — safe to build fresh per request rather
# than threading the capture loop's own instance through here, and keeps
# this read-only reporting path fully independent of the capture loop.
_diagnostics_controller = ExposureController()


@router.get("/status", response_model=StatusResponse)
def get_status(
    frame_store: FrameStore = Depends(get_frame_store),
    worker: CaptureWorker = Depends(get_capture_worker),
    config_manager: ConfigManager = Depends(get_config_manager),
    skystate_calculator: SkyStateCalculator = Depends(get_skystate_calculator),
) -> StatusResponse:
    latest = frame_store.get_latest()
    target = worker.current_target
    sky_state = skystate_calculator.compute()
    diagnostics = _diagnostics_controller.diagnose(
        sky_state, latest.stats if latest else None, config_manager.current.exposure_policy
    )
    return StatusResponse(
        camera_backend=worker.camera_backend_name,
        capturing=worker.is_alive(),
        exposure_us=target.exposure_us,
        analogue_gain=target.analogue_gain,
        stream_mode=worker.stream_mode.enabled,
        manual_exposure_override=worker.manual_exposure.get() is not None,
        last_capture_at=latest.metadata.captured_at.isoformat() if latest else None,
        last_stats=latest.stats if latest else None,
        last_save_raw=latest.save_raw if latest else None,
        exposure_diagnostics=ExposureDiagnosticsResponse(**diagnostics.__dict__),
        timezone=config_manager.current.location.timezone,
    )


@router.get("/skystate", response_model=SkyStateResponse)
def get_skystate(calculator: SkyStateCalculator = Depends(get_skystate_calculator)) -> SkyStateResponse:
    state = calculator.compute()
    return SkyStateResponse(
        sun_altitude_deg=state.sun_altitude_deg,
        sun_azimuth_deg=state.sun_azimuth_deg,
        moon_altitude_deg=state.moon_altitude_deg,
        moon_azimuth_deg=state.moon_azimuth_deg,
        moon_illumination=state.moon_illumination,
        period=state.period,
    )
