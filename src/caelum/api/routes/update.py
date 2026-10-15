"""Software update, admin-only — see `caelum/update/`.

`managed` is false outside an install made by scripts/install-system.sh;
every action then answers 409 and the UI shows the status only.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, WebSocket, WebSocketDisconnect

from caelum import __version__
from caelum.api.deps import get_config_manager, get_updater
from caelum.api.schemas import UpdateAvailable, UpdateStartRequest, UpdateStatusResponse
from caelum.api.security import authorize_websocket
from caelum.config.manager import ConfigManager
from caelum.update import releases
from caelum.update.job import MAX_WHEEL_BYTES, UpdateBusyError, Updater

logger = logging.getLogger(__name__)

router = APIRouter()
# Mounted without the admin dependency: a websocket authorizes inside its
# handler (see api/app.py).
ws_router = APIRouter()


def _require_managed(updater: Updater | None) -> Updater:
    if updater is None:
        raise HTTPException(status_code=409, detail="Not a managed install — updates are done by hand here")
    return updater


def _status(updater: Updater | None, config_manager: ConfigManager) -> UpdateStatusResponse:
    status = UpdateStatusResponse(
        current_version=__version__,
        managed=updater is not None,
        manifest_url=config_manager.current.update.manifest_url,
    )
    if updater is not None:
        available = updater.available
        status.available = (
            UpdateAvailable(version=available.version, notes=available.notes) if available is not None else None
        )
        status.checked_at = updater.checked_at
        status.check_error = updater.check_error
        status.job_state = updater.state
        status.job_target = updater.target
        status.job_error = updater.error
        status.last_result = releases.read_result(updater.layout)
    return status


@router.get("/update/status", response_model=UpdateStatusResponse)
def get_update_status(
    updater: Updater | None = Depends(get_updater),
    config_manager: ConfigManager = Depends(get_config_manager),
) -> UpdateStatusResponse:
    return _status(updater, config_manager)


@router.post("/update/check", response_model=UpdateStatusResponse)
def post_update_check(
    updater: Updater | None = Depends(get_updater),
    config_manager: ConfigManager = Depends(get_config_manager),
) -> UpdateStatusResponse:
    _require_managed(updater).check(config_manager.current.update.manifest_url)
    return _status(updater, config_manager)


@router.post("/update/start", response_model=UpdateStatusResponse)
def post_update_start(
    body: UpdateStartRequest,
    updater: Updater | None = Depends(get_updater),
    config_manager: ConfigManager = Depends(get_config_manager),
) -> UpdateStatusResponse:
    updater = _require_managed(updater)
    if updater.available is None or updater.available.version != body.version:
        raise HTTPException(status_code=409, detail=f"{body.version} is not the available update — check again")
    try:
        updater.start_release(updater.available)
    except UpdateBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _status(updater, config_manager)


@router.post("/update/upload", response_model=UpdateStatusResponse)
async def post_update_upload(
    file: UploadFile,
    updater: Updater | None = Depends(get_updater),
    config_manager: ConfigManager = Depends(get_config_manager),
) -> UpdateStatusResponse:
    updater = _require_managed(updater)
    if updater.busy:
        raise HTTPException(status_code=409, detail=f"An update to {updater.target} is already {updater.state}")
    filename = file.filename or ""
    try:
        releases.wheel_version(Path(filename))
    except releases.UpdateError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    path = updater.incoming_path(filename)
    size = 0
    with path.open("wb") as f:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_WHEEL_BYTES:
                f.close()
                path.unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail="Wheel is larger than the upload limit")
            f.write(chunk)
    logger.info("Update wheel uploaded: %s (%d bytes)", path.name, size)
    try:
        updater.start_wheel(path)
    except UpdateBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _status(updater, config_manager)


@ws_router.websocket("/ws/update")
async def update_ws(websocket: WebSocket) -> None:
    """The install log: backlog on connect, then each line live — the same
    frame protocol as /ws/logs."""
    if await authorize_websocket(websocket, admin=True) is None:
        return
    updater = get_updater(websocket)
    await websocket.accept()
    if updater is None:
        await websocket.close()
        return

    log_buffer = updater.log_buffer
    queue = log_buffer.subscribe(asyncio.get_running_loop())
    try:
        await websocket.send_json({"type": "backlog", "entries": [e.to_dict() for e in log_buffer.snapshot()]})
        while True:
            entry = await queue.get()
            await websocket.send_json({"type": "line", "entry": entry.to_dict()})
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("Error serving /ws/update")
    finally:
        log_buffer.unsubscribe(queue)
