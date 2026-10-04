"""Example widget plugin: a marker showing where a telescope is currently
pointed, projected onto the allsky image.

`source="simulated"` is the only mode implemented — a slow deterministic
sweep standing in for a real mount. Swap `_simulated_position()` for a query
against an INDI server (or ASCOM/Alpaca) to point this at real hardware;
everything else — the projection math, the overlay element, the config
shape — stays the same, which is the whole point of proving the "widget"
extension point with a working example rather than leaving it speculative.
"""

from __future__ import annotations

import math
import time
from typing import Any, Literal

from pydantic import BaseModel, Field

from caelum.capture.frame_store import ProcessedFrame
from caelum.capture.metadata import OverlayElement
from caelum.derivatives.projection import Point, altaz_to_fraction
from caelum.plugins.base import Plugin

#: One full simulated sweep takes this long — slow enough to look like a
#: real telescope tracking/slewing, fast enough to see move in the editor.
_SWEEP_PERIOD_S = 600.0


class TelescopePositionSettings(BaseModel):
    #: Only "simulated" is implemented; reserved for a future "indi" mode.
    source: Literal["simulated"] = "simulated"
    #: Fractional (0..1) zenith pixel — where straight up lands in the frame.
    center_x: float = Field(default=0.5, ge=0.0, le=1.0)
    center_y: float = Field(default=0.5, ge=0.0, le=1.0)
    #: Fractional (0..1) radius from zenith to the horizon.
    radius: float = Field(default=0.48, ge=0.0, le=1.0)
    #: Corrects for the camera's rotation relative to true north.
    azimuth_offset_deg: float = 0.0
    #: Flip east/west — needed when the lens/mirror mirrors the sky.
    mirror: bool = False
    label: str = "Telescope"


def _simulated_position(t: float) -> tuple[float, float]:
    """A slow, deterministic alt/az sweep — not real telemetry, just enough
    motion to demonstrate the overlay updating over time."""
    phase = (t % _SWEEP_PERIOD_S) / _SWEEP_PERIOD_S
    altitude_deg = 45.0 + 35.0 * math.sin(2 * math.pi * phase)
    azimuth_deg = (360.0 * phase) % 360.0
    return altitude_deg, azimuth_deg


def project_altaz_to_fraction(alt_deg: float, az_deg: float, settings: TelescopePositionSettings) -> Point | None:
    """Standard allsky equidistant-fisheye projection — see
    `caelum.derivatives.projection` for the shared math."""
    return altaz_to_fraction(
        alt_deg,
        az_deg,
        center_x=settings.center_x,
        center_y=settings.center_y,
        radius=settings.radius,
        azimuth_offset_deg=settings.azimuth_offset_deg,
        mirror=settings.mirror,
    )


class TelescopePositionWorker(Plugin):
    """Demo/example plugin proving the overlay "widget" extension point:
    contributes a `telescope_marker` overlay element from a simulated
    position feed. Shipped disabled by default (see `_default_plugins()`)
    since a fake marker showing up unasked would be a bad default."""

    id = "telescope_position"
    config_schema = TelescopePositionSettings

    def __init__(self, settings: dict[str, Any] | None = None) -> None:
        super().__init__(settings or {})
        self._settings = TelescopePositionSettings.model_validate(self.settings)

    def provide_overlay_elements(self, frame: ProcessedFrame) -> list[OverlayElement]:
        alt_deg, az_deg = _simulated_position(time.time())
        point = project_altaz_to_fraction(alt_deg, az_deg, self._settings)
        if point is None:
            return []
        return [
            OverlayElement(
                type="telescope_marker",
                source=self.id,
                payload={
                    "x": point.x,
                    "y": point.y,
                    "alt_deg": alt_deg,
                    "az_deg": az_deg,
                    "label": self._settings.label,
                },
            )
        ]
