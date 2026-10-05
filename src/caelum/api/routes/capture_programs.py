"""Capture programs: list, edit, check, test once on the camera, activate.

Admin only, and only while `capture.editing_enabled` for anything that
writes or runs code — a capture program is arbitrary Python running with
the service's rights (like the web terminal). Every save, test and
activation is logged with the user's name.

Saving never changes what runs: production runs the archived version that
was last *activated* (after passing Check).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from caelum.api.deps import get_capture_worker, get_config_manager, get_program_store, get_settings
from caelum.api.security import Principal, require_admin
from caelum.capture.worker import CaptureWorker
from caelum.capture_runtime import ProgramLoadError, testrun
from caelum.capture_runtime.check import check
from caelum.capture_runtime.program import load_program, source_sha256
from caelum.capture_runtime.store import MAX_SOURCE_BYTES, ProgramNotFound, ProgramStore, ProgramStoreError
from caelum.config.manager import ConfigManager
from caelum.settings import Settings
from caelum.storage import browse

router = APIRouter()
audit = logging.getLogger("caelum.audit")


class SourceBody(BaseModel):
    source: str


class CheckBody(BaseModel):
    source: str
    name: str = "unsaved.py"
    simulate: bool = True


class ActivateBody(BaseModel):
    #: The version expected to be activated — refused if the file changed
    #: since (so what was checked/tested is what runs).
    sha256: str | None = None


def _store_error(exc: ProgramStoreError) -> HTTPException:
    return HTTPException(status_code=404 if isinstance(exc, ProgramNotFound) else 400, detail=str(exc))


def _require_editing(config_manager: ConfigManager) -> None:
    if not config_manager.current.capture.editing_enabled:
        raise HTTPException(status_code=403, detail="Editing capture programs is disabled (capture.editing_enabled)")


def _active(config_manager: ConfigManager) -> dict[str, Any]:
    capture = config_manager.current.capture
    return {"name": capture.active_program, "sha256": capture.active_sha256}


async def _check(name: str, source: str, worker: CaptureWorker, config_manager: ConfigManager,
                 simulate: bool = True) -> dict[str, Any]:
    # The check runs in a child process; keep the event loop free meanwhile.
    return await asyncio.to_thread(
        check, name, source, config_manager.current, worker.camera_capabilities, simulate
    )


@router.get("/capture-programs")
def list_programs(
    store: ProgramStore = Depends(get_program_store),
    worker: CaptureWorker = Depends(get_capture_worker),
    config_manager: ConfigManager = Depends(get_config_manager),
) -> dict[str, Any]:
    return {
        "programs": [p.to_dict() for p in store.list()],
        "active": _active(config_manager),
        "status": worker.program_status,
        "editing_enabled": config_manager.current.capture.editing_enabled,
        "directory": str(store.directory),
    }


@router.get("/capture-programs/status")
def program_status(
    worker: CaptureWorker = Depends(get_capture_worker),
    config_manager: ConfigManager = Depends(get_config_manager),
) -> dict[str, Any]:
    return {"active": _active(config_manager), "status": worker.program_status}


@router.post("/capture-programs/check")
async def check_source(
    body: CheckBody,
    worker: CaptureWorker = Depends(get_capture_worker),
    config_manager: ConfigManager = Depends(get_config_manager),
) -> dict[str, Any]:
    _require_editing(config_manager)
    return await _check(body.name, body.source, worker, config_manager, body.simulate)


@router.post("/capture-programs/upload")
async def upload_program(
    file: UploadFile = File(...),
    principal: Principal = Depends(require_admin),
    store: ProgramStore = Depends(get_program_store),
    config_manager: ConfigManager = Depends(get_config_manager),
) -> dict[str, Any]:
    _require_editing(config_manager)
    data = await file.read(MAX_SOURCE_BYTES + 1)
    try:
        source = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail="not a UTF-8 text file") from exc
    name = (file.filename or "").rsplit("/", 1)[-1].lower()
    try:
        sha = store.save(name, source)
    except ProgramStoreError as exc:
        raise _store_error(exc) from exc
    audit.info("%s uploaded capture program %s (%s)", principal.username, name, sha[:12])
    return {"name": name, "sha256": sha}


@router.get("/capture-programs/test-runs/{run_id}")
def get_test_run(run_id: str, settings: Settings = Depends(get_settings)) -> dict[str, Any]:
    run_dir = testrun.run_dir_for(settings.data_dir, run_id)
    if run_dir is None:
        raise HTTPException(status_code=404, detail="No such test run")
    return testrun.read_report(run_dir)


_TEST_FILE_TYPES = {".webp": "image/webp", ".dng": "image/x-adobe-dng", ".json": "application/json"}


@router.get("/capture-programs/test-runs/{run_id}/{path:path}")
def get_test_file(run_id: str, path: str, settings: Settings = Depends(get_settings)) -> FileResponse:
    """A file the test run stored (same layout as the data directory:
    `thumbnails/…`, `raw/…`)."""
    run_dir = testrun.run_dir_for(settings.data_dir, run_id)
    if run_dir is None:
        raise HTTPException(status_code=404, detail="Not found")
    try:
        target = browse.resolve_within(run_dir, path)
    except browse.PathOutsideRoot as exc:
        raise HTTPException(status_code=404, detail="Not found") from exc
    media_type = _TEST_FILE_TYPES.get(target.suffix.lower())
    if media_type is None or not target.is_file() or target.name == "report.json":
        raise HTTPException(status_code=404, detail="Not found")
    if target.suffix.lower() == ".dng":
        return FileResponse(target, media_type=media_type, filename=f"test-{run_id}-{target.name}")
    return FileResponse(target, media_type=media_type)


@router.get("/capture-programs/{name}")
def get_program(name: str, store: ProgramStore = Depends(get_program_store)) -> dict[str, Any]:
    try:
        source, origin = store.get(name)
    except ProgramStoreError as exc:
        raise _store_error(exc) from exc
    info = next((p for p in store.list() if p.name == name), None)
    return {"name": name, "origin": origin, "source": source, "sha256": source_sha256(source),
            "meta": info.meta if info else {}}


@router.put("/capture-programs/{name}")
def save_program(
    name: str,
    body: SourceBody,
    principal: Principal = Depends(require_admin),
    store: ProgramStore = Depends(get_program_store),
    config_manager: ConfigManager = Depends(get_config_manager),
) -> dict[str, Any]:
    _require_editing(config_manager)
    try:
        sha = store.save(name, body.source)
    except ProgramStoreError as exc:
        raise _store_error(exc) from exc
    audit.info("%s saved capture program %s (%s)", principal.username, name, sha[:12])
    return {"name": name, "sha256": sha}


@router.delete("/capture-programs/{name}")
def delete_program(
    name: str,
    principal: Principal = Depends(require_admin),
    store: ProgramStore = Depends(get_program_store),
    config_manager: ConfigManager = Depends(get_config_manager),
) -> dict[str, Any]:
    _require_editing(config_manager)
    if config_manager.current.capture.active_program == name:
        raise HTTPException(status_code=409, detail="The active program can't be deleted — activate another first")
    try:
        store.delete(name)
    except ProgramStoreError as exc:
        raise _store_error(exc) from exc
    audit.info("%s deleted capture program %s", principal.username, name)
    return {"name": name, "deleted": True}


@router.post("/capture-programs/{name}/test")
async def test_program(
    name: str,
    principal: Principal = Depends(require_admin),
    store: ProgramStore = Depends(get_program_store),
    worker: CaptureWorker = Depends(get_capture_worker),
    config_manager: ConfigManager = Depends(get_config_manager),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """Run the saved program once on the camera, after the next slot."""
    _require_editing(config_manager)
    try:
        source, origin = store.get(name)
    except ProgramStoreError as exc:
        raise _store_error(exc) from exc
    try:
        program = load_program(name, source, origin=origin)
    except ProgramLoadError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if origin == "user":
        store.archive(source)
    request = testrun.new_request(settings.data_dir, program, principal.username)
    try:
        worker.request_program_test(request)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    audit.info("%s queued a test run %s of %s (%s)", principal.username, request.run_id, name, program.sha256[:12])
    return {"run_id": request.run_id, "sha256": program.sha256}


@router.post("/capture-programs/{name}/activate")
async def activate_program(
    name: str,
    body: ActivateBody,
    principal: Principal = Depends(require_admin),
    store: ProgramStore = Depends(get_program_store),
    worker: CaptureWorker = Depends(get_capture_worker),
    config_manager: ConfigManager = Depends(get_config_manager),
) -> dict[str, Any]:
    """Check, archive and switch production to this program (from the
    next slot on)."""
    _require_editing(config_manager)
    try:
        source, origin = store.get(name)
    except ProgramStoreError as exc:
        raise _store_error(exc) from exc
    sha = source_sha256(source)
    if body.sha256 is not None and body.sha256 != sha:
        raise HTTPException(status_code=409, detail="The program changed since — check it again")
    report = await _check(name, source, worker, config_manager)
    if not report["ok"]:
        raise HTTPException(status_code=422, detail={"message": "Check failed", "report": report})
    active_sha = None
    if origin == "user":
        active_sha = store.archive(source)
    await config_manager.update({"capture": {"active_program": name, "active_sha256": active_sha}})
    audit.info("%s activated capture program %s (%s)", principal.username, name, sha[:12])
    return {"active": _active(config_manager), "report": report}
