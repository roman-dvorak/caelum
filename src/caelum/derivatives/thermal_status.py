"""Thermal status of the AMRPI4HAT01 board — configuration of the feed.

The plugin draws nothing itself. Its settings (`ThermalStatusSettings`)
configure `caelum.telemetry.thermal.ThermalStatusPoller`; while the plugin
is enabled, every frame carries the reading in `annotations["thermal"]`
(sidecar JSON, DNG XMP), and the values are `{placeholders}` in the overlay
editor's templates — the overlay is the editor's business, not the plugin's.
"""

from __future__ import annotations

from typing import Any

from caelum.plugins.base import Plugin
from caelum.telemetry.thermal import ThermalStatusSettings


class ThermalStatusWorker(Plugin):
    id = "thermal_status"
    config_schema = ThermalStatusSettings

    def __init__(self, settings: dict[str, Any] | None = None) -> None:
        super().__init__(settings or {})
        self._settings = ThermalStatusSettings.model_validate(self.settings)

    @property
    def thermal_settings(self) -> ThermalStatusSettings:
        return self._settings
