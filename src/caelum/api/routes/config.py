from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response

from caelum.api.deps import get_config_manager
from caelum.api.schemas import ConfigChange, ConfigImportRequest, ConfigImportResponse, ConfigPatchRequest
from caelum.config.manager import ConfigManager
from caelum.config.schema import AppConfig

router = APIRouter()

#: Never exported or imported: `config_version` is the server's own, and
#: `redis` is how this install reaches its Redis — not something to carry
#: over from another camera.
_NOT_PORTABLE = ("config_version", "redis")


@router.get("/config", response_model=AppConfig)
def get_config(config_manager: ConfigManager = Depends(get_config_manager)) -> AppConfig:
    return config_manager.current


@router.put("/config", response_model=AppConfig)
async def patch_config(
    body: ConfigPatchRequest, config_manager: ConfigManager = Depends(get_config_manager)
) -> AppConfig:
    try:
        return await config_manager.update(body.patch)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/config/export")
def export_config(config_manager: ConfigManager = Depends(get_config_manager)) -> Response:
    """The configuration as a JSON file, ready for `POST /config/import`
    here or on another camera."""
    cfg = config_manager.current
    data = cfg.model_dump(mode="json", exclude=set(_NOT_PORTABLE))
    camera = re.sub(r"[^A-Za-z0-9_-]+", "-", cfg.upload.camera_name).strip("-") or "camera"
    name = f"caelum-config-{camera}-{datetime.now(UTC):%Y%m%d-%H%M%S}.json"
    return Response(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@router.post("/config/import", response_model=ConfigImportResponse)
async def import_config(
    body: ConfigImportRequest, config_manager: ConfigManager = Depends(get_config_manager)
) -> ConfigImportResponse:
    """Merge a whole exported config, or just some of its values, into the
    current one: what the file has replaces what is set (lists whole),
    everything else stays. With `dry_run` only the changes are reported."""
    patch = {key: value for key, value in body.config.items() if key not in _NOT_PORTABLE}
    ignored = sorted(key for key in body.config if key in _NOT_PORTABLE)
    current = config_manager.current
    try:
        result = config_manager.preview(patch)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    changes = _diff(current.model_dump(mode="json"), result.model_dump(mode="json"))
    changes = [c for c in changes if c.path != "config_version"]
    applied = False
    if not body.dry_run and changes:
        result = await config_manager.update(patch)
        applied = True
    return ConfigImportResponse(
        changes=changes, ignored=ignored, applied=applied, config=result if applied else current
    )


def _diff(old: Any, new: Any, path: str = "") -> list[ConfigChange]:
    if isinstance(old, dict) and isinstance(new, dict):
        changes = []
        for key in [*old, *(k for k in new if k not in old)]:
            changes += _diff(old.get(key), new.get(key), f"{path}.{key}" if path else str(key))
        return changes
    return [] if old == new else [ConfigChange(path=path, old=old, new=new)]
