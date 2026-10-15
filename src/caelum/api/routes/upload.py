"""Upload status and a manual "sync now" (admin)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from caelum.api.deps import get_upload_worker
from caelum.upload.uploader import UploadWorker

router = APIRouter()


@router.get("/upload/status")
def upload_status(worker: UploadWorker = Depends(get_upload_worker)) -> dict[str, Any]:
    return worker.status


@router.post("/upload/sync")
def upload_sync(worker: UploadWorker = Depends(get_upload_worker)) -> dict[str, Any]:
    """Run the full reconciliation pass now (it also re-sends anything the
    regular passes missed)."""
    if not worker.status["enabled"]:
        raise HTTPException(status_code=409, detail="Upload is disabled (upload.enabled)")
    worker.request_sync()
    return worker.status
