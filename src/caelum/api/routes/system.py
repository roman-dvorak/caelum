from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from caelum.api.deps import get_settings
from caelum.api.schemas import (
    DiskUsageInfo,
    NetworkInterfaceInfo,
    SystemActionResponse,
    SystemInfoResponse,
)
from caelum.control import system_info
from caelum.settings import Settings

router = APIRouter()


@router.get("/system/info", response_model=SystemInfoResponse)
def get_system_info(settings: Settings = Depends(get_settings)) -> SystemInfoResponse:
    info = system_info.collect(data_dir=str(settings.data_dir))
    return SystemInfoResponse(
        hostname=info.hostname,
        uptime_s=info.uptime_s,
        cpu_percent=info.cpu_percent,
        cpu_count=info.cpu_count,
        load_avg=info.load_avg,
        mem_total_bytes=info.mem_total_bytes,
        mem_used_bytes=info.mem_used_bytes,
        mem_percent=info.mem_percent,
        disks=[DiskUsageInfo(**vars(d)) for d in info.disks],
        temperatures_c=info.temperatures_c,
        network=[NetworkInterfaceInfo(**vars(n)) for n in info.network],
    )


@router.post("/system/shutdown", response_model=SystemActionResponse)
def post_shutdown() -> SystemActionResponse:
    try:
        system_info.shutdown()
    except system_info.PowerActionError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return SystemActionResponse(ok=True, message="Shutting down now.")


@router.post("/system/reboot", response_model=SystemActionResponse)
def post_reboot() -> SystemActionResponse:
    try:
        system_info.reboot()
    except system_info.PowerActionError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return SystemActionResponse(ok=True, message="Rebooting now.")
