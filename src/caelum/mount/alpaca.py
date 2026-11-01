"""ASCOM Alpaca (HTTP/JSON) telescope client — works against any Alpaca server,
e.g. ASCOM Remote or a driver exposing Alpaca on another PC."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from .state import MountState

_NOT_IMPLEMENTED = 0x400


class AlpacaError(RuntimeError):
    pass


class AlpacaTelescope:
    def __init__(self, host: str, port: int = 11111, device_number: int = 0, timeout_s: float = 3.0) -> None:
        self._base = f"http://{host}:{port}/api/v1/telescope/{device_number}"
        self._timeout = timeout_s
        self._txn = 0

    def _get(self, prop: str, optional: bool = False) -> Any:
        self._txn += 1
        query = urllib.parse.urlencode({"ClientID": 1, "ClientTransactionID": self._txn})
        try:
            with urllib.request.urlopen(f"{self._base}/{prop}?{query}", timeout=self._timeout) as resp:
                body = json.load(resp)
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise AlpacaError(f"{prop}: {exc}") from exc
        number = int(body.get("ErrorNumber", 0))
        if number:
            if optional or number == _NOT_IMPLEMENTED:
                return None
            raise AlpacaError(f"{prop}: {body.get('ErrorMessage') or number}")
        return body.get("Value")

    def read(self) -> MountState:
        now = time.time()
        if not self._get("connected"):
            return MountState(status="disconnected", timestamp=now)
        ra_h, dec = self._get("rightascension"), self._get("declination")
        parked = bool(self._get("atpark", optional=True))
        slewing = bool(self._get("slewing", optional=True))
        tracking = bool(self._get("tracking", optional=True))
        pier = self._get("sideofpier", optional=True)
        if parked:
            status = "slewing" if slewing else "parked"
        elif slewing:
            status = "slewing"
        elif tracking:
            status = "tracking"
        else:
            status = "idle"
        return MountState(
            status=status,
            ra_deg=None if ra_h is None else float(ra_h) * 15.0,
            dec_deg=None if dec is None else float(dec),
            epoch="jnow",
            alt_deg=_opt_float(self._get("altitude", optional=True)),
            az_deg=_opt_float(self._get("azimuth", optional=True)),
            pier_side={0: "east", 1: "west"}.get(pier) if isinstance(pier, int) else None,
            timestamp=now,
        )

    def close(self) -> None:
        pass


def _opt_float(value: Any) -> float | None:
    return None if value is None else float(value)
