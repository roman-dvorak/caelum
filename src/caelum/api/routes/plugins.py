from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from caelum.api.deps import get_config_manager
from caelum.api.schemas import PluginUpdateRequest
from caelum.config.manager import ConfigManager
from caelum.config.schema import PluginConfig
from caelum.derivatives.overlay import OverlaySettings

router = APIRouter()


@router.get("/plugins", response_model=dict[str, PluginConfig])
def list_plugins(config_manager: ConfigManager = Depends(get_config_manager)) -> dict[str, PluginConfig]:
    """Sorted by `order` ascending — the same order DerivativePool/PluginLoader
    apply when chaining hooks."""
    plugins = dict(config_manager.current.plugins)
    overlay = plugins.get("overlay")
    if overlay is not None:
        # As the camera reads it (older shapes migrated, the default template
        # filled in) — so the editor shows exactly what gets rendered.
        try:
            settings = OverlaySettings.model_validate(overlay.settings).model_dump()
            plugins["overlay"] = overlay.model_copy(update={"settings": settings})
        except ValueError:
            pass
    return dict(sorted(plugins.items(), key=lambda item: item[1].order))


@router.put("/plugins/{plugin_id}", response_model=PluginConfig)
async def update_plugin(
    plugin_id: str, body: PluginUpdateRequest, config_manager: ConfigManager = Depends(get_config_manager)
) -> PluginConfig:
    plugin_patch: dict = {}
    if body.enabled is not None:
        plugin_patch["enabled"] = body.enabled
    if body.order is not None:
        plugin_patch["order"] = body.order
    if body.settings is not None:
        plugin_patch["settings"] = body.settings

    try:
        updated = await config_manager.update({"plugins": {plugin_id: plugin_patch}})
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return updated.plugins[plugin_id]
