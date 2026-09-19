"""Discovers, validates, and orders configured plugins.

For this MVP, "discovers" means "matches `AppConfig.plugins` keys against a
list of Plugin classes the caller already knows about" (`main.py` passes in
whatever's importable) rather than scanning a directory or entry-points —
there are zero real third-party plugins yet to discover, so that machinery
would be speculative complexity. A `plugins/installed/`-directory or
entry-point based scan is a natural extension of `register_class` later,
once there's an actual plugin to discover.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass

from caelum.config.schema import AppConfig

from .base import Plugin

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LoadedPlugin:
    id: str
    plugin: Plugin
    order: int


class PluginLoader:
    def __init__(self, available_classes: Sequence[type[Plugin]] = ()) -> None:
        self._available: dict[str, type[Plugin]] = {cls.id: cls for cls in available_classes}
        self._loaded: list[LoadedPlugin] = []

    def register_class(self, plugin_cls: type[Plugin]) -> None:
        self._available[plugin_cls.id] = plugin_cls

    def load(self, config: AppConfig) -> list[LoadedPlugin]:
        """(Re)build the loaded-plugin list from `config.plugins`, sorted by
        `order` ascending (lower runs first) — the same order that governs
        `modify_image` chaining, overlay-element append order, and
        on_frame/create_derivative invocation order in DerivativePool."""
        loaded: list[LoadedPlugin] = []
        for plugin_id, plugin_cfg in config.plugins.items():
            if not plugin_cfg.enabled:
                continue
            plugin_cls = self._available.get(plugin_id)
            if plugin_cls is None:
                logger.warning("No plugin class registered for id %r — skipping", plugin_id)
                continue

            settings = plugin_cfg.settings
            if plugin_cls.config_schema is not None:
                try:
                    settings = plugin_cls.config_schema.model_validate(settings).model_dump()
                except Exception:
                    logger.exception("Plugin %r has invalid config — skipping", plugin_id)
                    continue

            loaded.append(LoadedPlugin(id=plugin_id, plugin=plugin_cls(settings), order=plugin_cfg.order))

        loaded.sort(key=lambda lp: lp.order)
        self._loaded = loaded
        return loaded

    @property
    def loaded(self) -> list[LoadedPlugin]:
        return list(self._loaded)
