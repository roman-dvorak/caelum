"""Plugin: a crosshair on the allsky image showing where a telescope is pointed.

The position comes from a mount driver on another computer — INDI or ASCOM
Alpaca — read by a background thread (`caelum.mount`), so it never delays a
frame; each frame just takes the latest state. RA/Dec is turned into alt/az for
the camera's own site and then into a pixel through the calibrated lens
(`camera.lens`), exactly like the sky overlay, so the cross sits on the same
stars. `source="simulated"` sweeps a fake alt/az for trying the overlay out.

The overlay element is a `telescope_marker` (a crosshair, not a field of view)
whose colour and caption follow the mount's status: tracking, slewing, parked,
idle, disconnected, error, or offline (the last known pointing, greyed out).
It also stores RA/Dec and alt/az, so a viewer can redraw it from the metadata.
"""

from __future__ import annotations

import math
import time
from typing import Any, Literal

from pydantic import BaseModel, Field

from caelum.capture.frame_store import ProcessedFrame
from caelum.capture.metadata import OverlayElement
from caelum.config.schema import LensConfig
from caelum.derivatives.projection import Point, project_altaz_to_pixel
from caelum.mount import MountPoller, MountState
from caelum.plugins.base import Plugin
from caelum.sky.positions import radec_to_altaz

#: One full simulated sweep takes this long.
_SWEEP_PERIOD_S = 600.0


class TelescopePositionSettings(BaseModel):
    source: Literal["simulated", "indi", "alpaca"] = "simulated"
    #: Host of the INDI / Alpaca server (another PC on the network).
    host: str = ""
    #: TCP port; 0 means the protocol default (INDI 7624, Alpaca 11111).
    port: int = Field(default=0, ge=0, le=65535)
    #: INDI device name; empty = the first telescope found on the server.
    device: str = ""
    #: Alpaca device number.
    device_number: int = Field(default=0, ge=0)
    #: How often the mount is polled, in seconds.
    poll_interval_s: float = Field(default=1.0, ge=0.2, le=60.0)
    #: A report older than this makes the telescope count as offline.
    stale_after_s: float = Field(default=10.0, ge=1.0, le=3600.0)
    #: Keep drawing the last known pointing, greyed out, while offline.
    show_stale: bool = True
    label: str = "Telescope"


def _simulated_state(t: float) -> MountState:
    phase = (t % _SWEEP_PERIOD_S) / _SWEEP_PERIOD_S
    return MountState(
        status="slewing" if phase % 0.25 < 0.04 else "tracking",
        alt_deg=45.0 + 35.0 * math.sin(2 * math.pi * phase),
        az_deg=(360.0 * phase) % 360.0,
        timestamp=t,
    )


class _SimulatedPoller:
    def start(self) -> None: ...
    def close(self) -> None: ...

    def latest(self) -> MountState:
        return _simulated_state(time.time())


def build_poller(s: TelescopePositionSettings) -> MountPoller | _SimulatedPoller:
    if s.source == "simulated":
        return _SimulatedPoller()
    if not s.host:
        raise ValueError("telescope_position: `host` is required for the INDI / Alpaca source")
    if s.source == "indi":
        from caelum.mount.indi import IndiTelescope

        source: Any = IndiTelescope(s.host, s.port or 7624, s.device)
    else:
        from caelum.mount.alpaca import AlpacaTelescope

        source = AlpacaTelescope(s.host, s.port or 11111, s.device_number)
    return MountPoller(source, s.poll_interval_s, s.stale_after_s)


def marker_payload(
    state: MountState,
    *,
    lens: LensConfig,
    lat_deg: float,
    lon_deg: float,
    when: Any,
    aspect: float,
    label: str,
    now: float | None = None,
) -> dict[str, Any] | None:
    """The marker's payload, or None when there is no pointing to show.

    Alt/az is computed for `when` (the frame time) from RA/Dec for the camera's
    site; a state with only alt/az uses it as is. `x`/`y` are left out when the
    direction is outside what the lens sees (below the horizon, off the circle)
    — the element is still stored so the pointing is in the metadata."""
    if not state.has_pointing:
        return None
    payload: dict[str, Any] = {"label": label, "status": state.status}
    if state.error:
        payload["error"] = state.error
    if state.pier_side:
        payload["pier_side"] = state.pier_side
    if now is not None and state.timestamp:
        payload["age_s"] = round(max(0.0, now - state.timestamp), 1)
    if state.ra_deg is not None and state.dec_deg is not None:
        payload.update(ra_deg=round(state.ra_deg, 5), dec_deg=round(state.dec_deg, 5), epoch=state.epoch)
        alt, az = radec_to_altaz(state.ra_deg, state.dec_deg, when, lat_deg, lon_deg, state.epoch)
    else:
        alt, az = state.alt_deg, state.az_deg  # type: ignore[assignment]
    payload.update(alt_deg=round(alt, 3), az_deg=round(az, 3))
    point: Point | None = project_altaz_to_pixel(alt, az, lens, aspect)
    if point is not None and 0.0 <= point.x <= 1.0 and 0.0 <= point.y <= 1.0:
        payload.update(x=round(point.x, 5), y=round(point.y, 5))
    return payload


class TelescopePositionWorker(Plugin):
    """Contributes a `telescope_marker` overlay element from the latest mount
    state. Ships disabled (see `_default_plugins()`): without a telescope
    configured there is nothing to show."""

    id = "telescope_position"
    config_schema = TelescopePositionSettings

    def __init__(self, settings: dict[str, Any] | None = None) -> None:
        super().__init__(settings or {})
        self._settings = TelescopePositionSettings.model_validate(self.settings)
        self._poller = build_poller(self._settings)
        self._poller.start()

    def close(self) -> None:
        self._poller.close()

    @property
    def label(self) -> str:
        return self._settings.label

    def current_state(self) -> MountState | None:
        """The latest mount state (``offline`` once stale) — what the live view polls."""
        state = self._poller.latest()
        if state is not None and state.status == "offline" and not self._settings.show_stale:
            return None
        return state

    def provide_overlay_elements(self, frame: ProcessedFrame) -> list[OverlayElement]:
        if self.config_manager is None:
            return []
        state = self._poller.latest()
        if state is None:
            return []
        if state.status == "offline" and not self._settings.show_stale:
            return []
        cfg = self.config_manager.current
        height, width = frame.image.shape[:2]
        # A stale report is where the mount *was*: evaluate it at its own time, not the frame's.
        when = frame.metadata.captured_at
        if state.status == "offline" and state.timestamp:
            from datetime import UTC, datetime

            when = datetime.fromtimestamp(state.timestamp, UTC)
        payload = marker_payload(
            state,
            lens=cfg.camera.lens,
            lat_deg=cfg.location.lat,
            lon_deg=cfg.location.lon,
            when=when,
            aspect=width / height,
            label=self._settings.label,
            now=time.time(),
        )
        if payload is None:
            return []
        return [OverlayElement(type="telescope_marker", source=self.id, payload=payload)]
