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

import numpy as np
from pydantic import BaseModel, Field

from caelum.capture.frame_store import ProcessedFrame
from caelum.capture.metadata import OverlayElement
from caelum.derivatives.projection import project_altaz_to_pixel
from caelum.plugins.base import Plugin
from caelum.sky.positions import sky_objects


class SkyOverlaySettings(BaseModel):
    show_stars: bool = True
    #: Dimmest star drawn. Every star is stored in the frame's sidecar (and
    #: uploaded with it), so each magnitude roughly doubles that.
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


def _polyline(points: list[tuple[float, float] | None]) -> list[list[list[float]]]:
    """Split at the gaps (directions the lens cannot see) into drawable runs."""
    runs: list[list[list[float]]] = []
    current: list[list[float]] = []
    for point in points:
        if point is None:
            if len(current) > 1:
                runs.append(current)
            current = []
        else:
            current.append([round(point[0], 4), round(point[1], 4)])
    if len(current) > 1:
        runs.append(current)
    return runs


class SkyOverlayWorker(Plugin):
    id = "sky_overlay"
    config_schema = SkyOverlaySettings

    def __init__(self, settings: dict[str, Any] | None = None) -> None:
        super().__init__(settings or {})
        self._settings = SkyOverlaySettings.model_validate(self.settings)

    def provide_overlay_elements(self, frame: ProcessedFrame) -> list[OverlayElement]:
        if self.config_manager is None:
            return []
        cfg = self.config_manager.current
        lens = cfg.camera.lens
        height, width = frame.image.shape[:2]
        aspect = width / height
        s = self._settings
        horizon = 90.0 - lens.fov_deg / 2.0

        def where(alt: float, az: float) -> tuple[float, float] | None:
            point = project_altaz_to_pixel(alt, az, lens, aspect)
            return None if point is None else (point.x, point.y)

        elements: list[OverlayElement] = []
        if s.show_grid or s.show_compass:
            grid: dict[str, Any] = {"color": s.grid_color, "lines": [], "labels": []}
            if s.show_grid:
                azimuths = np.arange(0.0, 360.5, 5.0)
                for alt in (0.0, 30.0, 60.0):
                    if alt >= horizon:
                        grid["lines"] += _polyline([where(alt, az) for az in azimuths])
                for az in (0.0, 90.0, 180.0, 270.0):
                    grid["lines"] += _polyline([where(alt, az) for alt in np.arange(max(0.0, horizon), 90.1, 5.0)])
            if s.show_compass:
                for letter, az in (("N", 0.0), ("E", 90.0), ("S", 180.0), ("W", 270.0)):
                    point = where(max(0.0, horizon) + 6.0, az)
                    if point is not None:
                        grid["labels"].append({"text": letter, "x": round(point[0], 4), "y": round(point[1], 4),
                                               "north": letter == "N"})
            elements.append(OverlayElement(type="sky_grid", source=self.id, payload=grid))

        if s.show_stars or s.show_planets:
            location = cfg.location
            found = sky_objects(
                frame.metadata.captured_at, location.lat, location.lon, location.elevation_m,
                max_mag=s.max_magnitude if s.show_stars else -99.0, min_alt_deg=max(0.0, horizon),
                bodies=s.show_planets,
            )
            stars, bodies, labels = [], [], []
            for obj in found:
                point = where(obj.alt_deg, obj.az_deg)
                if point is None or not (0.0 <= point[0] <= 1.0 and 0.0 <= point[1] <= 1.0):
                    continue
                x, y = round(point[0], 4), round(point[1], 4)
                if obj.kind == "star":
                    if not s.show_stars:
                        continue
                    stars.append([x, y, round(obj.mag, 1)])
                    if obj.mag <= s.label_magnitude:
                        labels.append({"text": obj.name, "x": x, "y": y})
                else:
                    bodies.append({"kind": obj.kind, "name": obj.name, "x": x, "y": y})
            elements.append(
                OverlayElement(
                    type="sky_map", source=self.id,
                    payload={"stars": stars, "bodies": bodies, "labels": labels, "color": s.star_color},
                )
            )
        return elements
