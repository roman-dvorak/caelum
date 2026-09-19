from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from caelum.api.deps import get_config_manager
from caelum.api.schemas import ConfigPatchRequest
from caelum.config.manager import ConfigManager
from caelum.config.schema import AppConfig

router = APIRouter()


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
