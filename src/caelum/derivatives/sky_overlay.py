"""Plugin: the sky drawn over the frame — stars, planets, Sun, Moon, a compass
and an altitude grid — through the calibrated lens.

What is drawn follows the clock: it is recomputed for every frame from the
catalog (`caelum.sky`) and `camera.lens`, so it stays correct all night and
sits exactly where the real stars are once the lens is calibrated (web UI →
Lens, which also fills in `camera.lens`). With a wrong or default lens the
overlay is a plausible-looking sky in the wrong place: calibrate first.

It contributes two elements, rendered by `overlay_render`:
`sky_map` (objects, with labels for the bright ones) and `sky_grid` (altitude
rings, the meridian/east-west lines and the N/E/S/W letters).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from caelum.capture.frame_store import ProcessedFrame
from caelum.capture.metadata import OverlayElement
from caelum.plugins.base import Plugin


class SkyOverlaySettings(BaseModel):
    show_stars: bool = True
    #: Dimmest star drawn. Only affects render time: the sidecar stores
    #: parameters, not the stars.
    max_magnitude: float = Field(default=3.5, ge=-1.0, le=6.0)
    #: Stars up to this magnitude also get their name.
    label_magnitude: float = Field(default=1.5, ge=-2.0, le=6.0)
    show_planets: bool = True
    show_compass: bool = True
    #: Altitude rings (30 and 60 degrees) and the cardinal lines.
    show_grid: bool = True
    #: Hex colours of the stars/labels and of the grid.
    star_color: str = "#e8f1ff"
    grid_color: str = "#50c8dc"


class SkyOverlayWorker(Plugin):
    id = "sky_overlay"
    config_schema = SkyOverlaySettings

    def __init__(self, settings: dict[str, Any] | None = None) -> None:
        super().__init__(settings or {})
        self._settings = SkyOverlaySettings.model_validate(self.settings)

    def provide_overlay_elements(self, frame: ProcessedFrame) -> list[OverlayElement]:
        """Elements carry parameters, not coordinates (see `caelum.sky.overlay_geometry`):
        the sidecar stays a few hundred bytes and the renderer works the
        positions out when it draws."""
        if self.config_manager is None:
            return []
        cfg = self.config_manager.current
        s = self._settings
        params: dict[str, Any] = {"lens": cfg.camera.lens.model_dump()}
        elements: list[OverlayElement] = []
        if s.show_grid or s.show_compass:
            grid = {**params, "show_grid": s.show_grid, "show_compass": s.show_compass, "grid_color": s.grid_color}
            elements.append(OverlayElement(type="sky_grid", source=self.id, payload={"params": grid}))
        if s.show_stars or s.show_planets:
            location = cfg.location
            sky = {
                **params,
                "captured_at": frame.metadata.captured_at.isoformat(),
                "lat": location.lat, "lon": location.lon, "elevation_m": location.elevation_m,
                "show_stars": s.show_stars, "show_planets": s.show_planets,
                "max_magnitude": s.max_magnitude, "label_magnitude": s.label_magnitude,
                "star_color": s.star_color,
            }
            elements.append(OverlayElement(type="sky_map", source=self.id, payload={"params": sky}))
        return elements
