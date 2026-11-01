"""Where the telescope points right now, for the live view's crosshair.

`GET /mount/state` — the latest state held by the `telescope_position` plugin's
background reader (no request ever talks to the mount). The browser works out
alt/az and the pixel itself from RA/Dec, the lens and the site, like the rest
of the live sky, so the cross moves between frames.
"""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from starlette.requests import HTTPConnection

from caelum.derivatives.telescope_position import TelescopePositionWorker
from caelum.mount.state import Epoch, MountStatus

router = APIRouter()


class MountStateResponse(BaseModel):
    #: False when the plugin is off or has no state yet — draw nothing.
    enabled: bool
    label: str = "Telescope"
    status: MountStatus | None = None
    ra_deg: float | None = None
    dec_deg: float | None = None
    epoch: Epoch = "jnow"
    alt_deg: float | None = None
    az_deg: float | None = None
    pier_side: str | None = None
    error: str | None = None
    #: Seconds since the mount last reported.
    age_s: float | None = None


def _worker(conn: HTTPConnection) -> TelescopePositionWorker | None:
    for loaded in conn.app.state.plugin_loader.loaded:
        if isinstance(loaded.plugin, TelescopePositionWorker):
            return loaded.plugin
    return None


@router.get("/mount/state", response_model=MountStateResponse)
def get_mount_state(worker: TelescopePositionWorker | None = Depends(_worker)) -> MountStateResponse:
    state = worker.current_state() if worker else None
    if worker is None or state is None:
        return MountStateResponse(enabled=False)
    return MountStateResponse(
        enabled=True,
        label=worker.label,
        status=state.status,
        ra_deg=state.ra_deg,
        dec_deg=state.dec_deg,
        epoch=state.epoch,
        alt_deg=state.alt_deg,
        az_deg=state.az_deg,
        pier_side=state.pier_side,
        error=state.error,
        age_s=round(max(0.0, time.time() - state.timestamp), 1) if state.timestamp else None,
    )
