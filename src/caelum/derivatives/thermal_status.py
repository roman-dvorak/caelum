"""Overlay label for the thermal status of the camera management board.

The values come from the frame's own metadata (`annotations["thermal"]`,
attached at capture from `caelum.telemetry.thermal.ThermalStatusPoller`), so
the overlay always shows exactly what is stored with the frame.
"""

from __future__ import annotations

from typing import Any

from caelum.capture.frame_store import ProcessedFrame
from caelum.capture.metadata import OverlayElement
from caelum.derivatives.thermal_format import format_thermal
from caelum.plugins.base import Plugin
from caelum.telemetry.thermal import ANNOTATION_KEY, ThermalStatusSettings


class ThermalStatusWorker(Plugin):
    id = "thermal_status"
    config_schema = ThermalStatusSettings

    def __init__(self, settings: dict[str, Any] | None = None) -> None:
        super().__init__(settings or {})
        self._settings = ThermalStatusSettings.model_validate(self.settings)

    @property
    def thermal_settings(self) -> ThermalStatusSettings:
        return self._settings

    def provide_overlay_elements(self, frame: ProcessedFrame) -> list[OverlayElement]:
        overlay = self._settings.overlay
        thermal = (frame.metadata.annotations or {}).get(ANNOTATION_KEY)
        if not overlay.enabled or not thermal:
            return []
        text = format_thermal(overlay.template, thermal)
        return [
            OverlayElement(
                type="custom_label",
                source=self.id,
                payload={
                    "x": overlay.x,
                    "y": overlay.y,
                    "text": text,
                    "align": overlay.align,
                    "valign": overlay.valign,
                    "font_size_px": overlay.font_size_px,
                    "color": overlay.color,
                    "background": overlay.background,
                },
            )
        ]
