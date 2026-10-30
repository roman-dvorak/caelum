"""The geometry of the sky overlay, computed from a handful of parameters.

A frame's sidecar stores only these parameters (time, place, lens, what to
show) in its `sky_grid` / `sky_map` elements, not the hundreds of star
positions they produce — the renderer (`derivatives/overlay_render`) expands
them when it draws, with the same code the camera used at capture time. The
result is the explicit payload (`lines`/`labels`, `stars`/`bodies`) that
those elements also accept directly, which is what older sidecars hold.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import numpy as np

from caelum.config.schema import LensConfig
from caelum.derivatives.projection import project_altaz_to_pixel
from caelum.sky.positions import sky_objects


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


class _Projector:
    def __init__(self, params: dict[str, Any], aspect: float) -> None:
        self.lens = LensConfig.model_validate(params["lens"])
        self.aspect = aspect
        self.horizon = 90.0 - self.lens.fov_deg / 2.0

    def __call__(self, alt: float, az: float) -> tuple[float, float] | None:
        point = project_altaz_to_pixel(alt, az, self.lens, self.aspect)
        return None if point is None else (point.x, point.y)


def grid_payload(params: dict[str, Any], aspect: float) -> dict[str, Any]:
    where = _Projector(params, aspect)
    horizon = where.horizon
    grid: dict[str, Any] = {"color": params.get("grid_color"), "lines": [], "labels": []}
    if params.get("show_grid", True):
        azimuths = np.arange(0.0, 360.5, 5.0)
        for alt in (0.0, 30.0, 60.0):
            if alt >= horizon:
                grid["lines"] += _polyline([where(alt, az) for az in azimuths])
        for az in (0.0, 90.0, 180.0, 270.0):
            grid["lines"] += _polyline([where(alt, az) for alt in np.arange(max(0.0, horizon), 90.1, 5.0)])
    if params.get("show_compass", True):
        for letter, az in (("N", 0.0), ("E", 90.0), ("S", 180.0), ("W", 270.0)):
            point = where(max(0.0, horizon) + 6.0, az)
            if point is not None:
                grid["labels"].append(
                    {"text": letter, "x": round(point[0], 4), "y": round(point[1], 4), "north": letter == "N"}
                )
    return grid


def map_payload(params: dict[str, Any], aspect: float) -> dict[str, Any]:
    where = _Projector(params, aspect)
    show_stars = params.get("show_stars", True)
    found = sky_objects(
        datetime.fromisoformat(params["captured_at"]),
        params["lat"], params["lon"], params.get("elevation_m", 0.0),
        max_mag=params.get("max_magnitude", 3.5) if show_stars else -99.0,
        min_alt_deg=max(0.0, where.horizon),
        bodies=params.get("show_planets", True),
    )
    label_magnitude = params.get("label_magnitude", 1.5)
    stars, bodies, labels = [], [], []
    for obj in found:
        point = where(obj.alt_deg, obj.az_deg)
        if point is None or not (0.0 <= point[0] <= 1.0 and 0.0 <= point[1] <= 1.0):
            continue
        x, y = round(point[0], 4), round(point[1], 4)
        if obj.kind == "star":
            if not show_stars:
                continue
            stars.append([x, y, round(obj.mag, 1)])
            if obj.mag <= label_magnitude:
                labels.append({"text": obj.name, "x": x, "y": y})
        else:
            bodies.append({"kind": obj.kind, "name": obj.name, "x": x, "y": y})
    return {"stars": stars, "bodies": bodies, "labels": labels, "color": params.get("star_color")}
