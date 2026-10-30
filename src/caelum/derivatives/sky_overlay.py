"""Plugin: the sky drawn over the frame — stars, planets, Sun, Moon, a compass
and an altitude grid — through the calibrated lens.

What is drawn follows the clock: it is recomputed for every frame from the
catalog (`caelum.sky`) and `camera.lens`, so it stays correct all night and
sits exactly where the real stars are once the lens is calibrated (web UI →
Lens, which also fills in `camera.lens`). With a wrong or default lens the
overlay is a plausible-looking sky in the wrong place: calibrate first.

Each of its layers — grid, constellations, stars, planets, compass — is a
separate element with its own `layer` tag, rendered by `overlay_render`
(`sky_grid`, `sky_lines`, `sky_map`); with `overlay_mode = "file"` each layer
is stored as its own PNG so viewers can toggle it.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from caelum.capture.frame_store import ProcessedFrame
from caelum.capture.metadata import OverlayElement
from caelum.plugins.base import Plugin
from caelum.sky.layers import sky_overlay_layers


class SkyOverlaySettings(BaseModel):
    show_stars: bool = True
    #: Dimmest star drawn. Only affects render time: the sidecar stores
    #: parameters, not the stars.
    max_magnitude: float = Field(default=3.5, ge=-1.0, le=6.0)
    #: Stars up to this magnitude also get their name.
    label_magnitude: float = Field(default=1.5, ge=-2.0, le=6.0)
    show_planets: bool = True
    #: Constellation stick figures.
    show_constellations: bool = True
    show_compass: bool = True
    #: Altitude rings (30 and 60 degrees) and the cardinal lines.
    show_grid: bool = True
    #: Hex colours of the stars/labels and of the grid.
    star_color: str = "#e8f1ff"
    grid_color: str = "#50c8dc"
    constellation_color: str = "#8caaff"


class SkyOverlayWorker(Plugin):
    id = "sky_overlay"
    config_schema = SkyOverlaySettings

    def __init__(self, settings: dict[str, Any] | None = None) -> None:
        super().__init__(settings or {})
        self._settings = SkyOverlaySettings.model_validate(self.settings)

    def provide_overlay_elements(self, frame: ProcessedFrame) -> list[OverlayElement]:
        """One element per layer (`payload["layer"]`, see `caelum.sky.layers`),
        so a viewer can switch each on or off. Elements carry parameters, not
        coordinates (see `caelum.sky.overlay_geometry`): the sidecar stays a
        few hundred bytes and the renderer works the positions out when it draws."""
        if self.config_manager is None:
            return []
        cfg = self.config_manager.current
        s = self._settings
        lens = cfg.camera.lens.model_dump()
        location = cfg.location
        when = {
            "captured_at": frame.metadata.captured_at.isoformat(),
            "lat": location.lat, "lon": location.lon, "elevation_m": location.elevation_m,
        }

        def element(kind: str, layer: str, params: dict[str, Any]) -> OverlayElement:
            return OverlayElement(
                type=kind, source=self.id, payload={"layer": layer, "params": {"lens": lens, **params}}
            )

        grid = {"grid_color": s.grid_color}
        sky = {**when, "max_magnitude": s.max_magnitude, "label_magnitude": s.label_magnitude,
               "star_color": s.star_color}
        wanted = set(sky_overlay_layers(s.model_dump()))
        elements = []
        if "grid" in wanted:
            elements.append(element("sky_grid", "grid", {**grid, "show_grid": True, "show_compass": False}))
        if "constellations" in wanted:
            lines = {**when, "constellation_color": s.constellation_color}
            elements.append(element("sky_lines", "constellations", lines))
        if "stars" in wanted:
            elements.append(element("sky_map", "stars", {**sky, "show_stars": True, "show_planets": False}))
        if "planets" in wanted:
            elements.append(element("sky_map", "planets", {**sky, "show_stars": False, "show_planets": True}))
        if "compass" in wanted:
            elements.append(element("sky_grid", "compass", {**grid, "show_grid": False, "show_compass": True}))
        return elements
