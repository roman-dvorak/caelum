"""The one shape every mount source reports, whatever protocol it speaks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

#: What the telescope is doing, as far as the marker is concerned.
#:
#: * ``offline``      — the server cannot be reached, or its last report is too old;
#: * ``disconnected`` — the server answers but the mount driver is not connected to the mount;
#: * ``parked``       — parked (or parking finished);
#: * ``slewing``      — moving to a target (including parking/unparking);
#: * ``tracking``     — following the sky;
#: * ``idle``         — connected, not moving and not tracking;
#: * ``error``        — the driver reports an alert / error.
MountStatus = Literal["offline", "disconnected", "parked", "slewing", "tracking", "idle", "error"]
Epoch = Literal["jnow", "j2000"]


@dataclass(frozen=True)
class MountState:
    status: MountStatus
    #: Pointing as the mount reports it. Either RA/Dec (with `epoch`) or, for
    #: simulated/alt-az mounts, `alt_deg`/`az_deg` alone.
    ra_deg: float | None = None
    dec_deg: float | None = None
    epoch: Epoch = "jnow"
    #: The mount's own horizontal coordinates, when it reports them. Only used
    #: when there is no RA/Dec; otherwise alt/az is computed for the camera's site.
    alt_deg: float | None = None
    az_deg: float | None = None
    pier_side: str | None = None
    #: Unix time of the report.
    timestamp: float = 0.0
    error: str | None = None

    @property
    def has_pointing(self) -> bool:
        return (self.ra_deg is not None and self.dec_deg is not None) or (
            self.alt_deg is not None and self.az_deg is not None
        )


class MountSource(Protocol):
    def read(self) -> MountState:
        """One poll. Raise on any communication failure; the poller backs off and retries."""

    def close(self) -> None: ...
