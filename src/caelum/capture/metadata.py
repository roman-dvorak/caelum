"""The single JSON representation of "everything needed to render an
overlay for this frame" — pushed live over the WebSocket, written as a
`<HHMMSS>.json` sidecar next to every stored image, and mirrored to the
remote server by the uploader. `packages/ui/OverlayRenderer.tsx` on the web
side renders exactly this shape, whichever source it came from.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from caelum.config.schema import SkyPeriod
from caelum.control.skystate import SkyState


class SkyStateModel(BaseModel):
    sun_altitude_deg: float
    sun_azimuth_deg: float
    moon_altitude_deg: float
    moon_azimuth_deg: float
    moon_illumination: float
    period: SkyPeriod

    @classmethod
    def from_skystate(cls, sky_state: SkyState) -> SkyStateModel:
        return cls(
            sun_altitude_deg=sky_state.sun_altitude_deg,
            sun_azimuth_deg=sky_state.sun_azimuth_deg,
            moon_altitude_deg=sky_state.moon_altitude_deg,
            moon_azimuth_deg=sky_state.moon_azimuth_deg,
            moon_illumination=sky_state.moon_illumination,
            period=sky_state.period,
        )


class OverlayElement(BaseModel):
    """Open-ended by design: `type` is not an enum so plugins can introduce
    their own kinds without a schema change here. `source` identifies who
    contributed it — "system" for the built-ins added below, or a plugin id."""

    type: str
    source: str = "system"
    payload: dict[str, Any] = Field(default_factory=dict)


class FrameMetadata(BaseModel):
    captured_at: datetime
    exposure_us: int
    analogue_gain: float
    sky_state: SkyStateModel
    focus_score: float
    overlay_elements: list[OverlayElement] = Field(default_factory=list)


def default_overlay_elements(metadata_without_elements: FrameMetadata) -> list[OverlayElement]:
    """The handful of overlay elements every frame gets regardless of
    plugins — timestamp, exposure/gain readout, sky-state badge."""
    m = metadata_without_elements
    return [
        OverlayElement(type="timestamp", payload={"text": m.captured_at.isoformat()}),
        OverlayElement(
            type="exposure_readout",
            payload={"exposure_us": m.exposure_us, "analogue_gain": m.analogue_gain},
        ),
        OverlayElement(
            type="sky_state_badge",
            payload={
                "period": m.sky_state.period,
                "sun_altitude_deg": round(m.sky_state.sun_altitude_deg, 1),
                "moon_illumination": round(m.sky_state.moon_illumination, 2),
            },
        ),
    ]
