"""Minimal INDI client: just enough of the XML protocol to follow one telescope.

Connects to an INDI server (default port 7624), asks for the properties and
keeps the few that matter — equatorial coordinates, tracking, park and the
connection switch — up to date from the stream. BLOBs are switched off.
"""

from __future__ import annotations

import socket
import time
import xml.etree.ElementTree as ET
from typing import Any

from .state import MountState

#: Properties, in order of preference, that carry the pointing.
_COORD_PROPS = (("EQUATORIAL_EOD_COORD", "jnow"), ("EQUATORIAL_COORD", "j2000"))


class IndiError(RuntimeError):
    pass


def parse_indi_number(text: str | None) -> float | None:
    """INDI numbers may be plain or sexagesimal ("12:30:15.5", "-5 20 10")."""
    if not text:
        return None
    text = text.strip()
    try:
        return float(text)
    except ValueError:
        pass
    parts = text.replace(":", " ").split()
    try:
        values = [float(p) for p in parts]
    except ValueError:
        return None
    if not values:
        return None
    sign = -1.0 if parts[0].startswith("-") else 1.0
    total = sum(abs(v) / 60.0**i for i, v in enumerate(values))
    return sign * total


class IndiTelescope:
    def __init__(self, host: str, port: int = 7624, device: str = "", timeout_s: float = 3.0, startup_s: float = 3.0):
        self._host, self._port, self._device = host, port, device
        self._timeout, self._startup = timeout_s, startup_s
        self._sock: socket.socket | None = None
        self._parser: ET.XMLPullParser | None = None
        self._root: ET.Element | None = None
        self._depth = 0
        #: (device, property) -> {"state": str, "values": {element: text}}
        self._props: dict[tuple[str, str], dict[str, Any]] = {}

    # -- connection -------------------------------------------------------
    def _connect(self) -> None:
        self.close()
        try:
            sock = socket.create_connection((self._host, self._port), timeout=self._timeout)
        except OSError as exc:
            raise IndiError(f"cannot connect to {self._host}:{self._port}: {exc}") from exc
        self._sock = sock
        self._props = {}
        self._parser = ET.XMLPullParser(events=("start", "end"))
        self._parser.feed("<indi>")
        self._depth = 0
        self._root = None
        dev = f' device="{self._device}"' if self._device else ""
        sock.sendall(f'<getProperties version="1.7"{dev}/><enableBLOB{dev}>Never</enableBLOB>'.encode())
        deadline = time.monotonic() + self._startup
        while time.monotonic() < deadline:
            self._pump(0.2)
            if self._find_device() is not None:
                return
        raise IndiError("no telescope device with equatorial coordinates found on the INDI server")

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
        self._sock = None

    # -- stream -----------------------------------------------------------
    def _pump(self, wait_s: float = 0.05) -> None:
        sock = self._sock
        if sock is None or self._parser is None:
            raise IndiError("not connected")
        sock.settimeout(wait_s)
        while True:
            try:
                data = sock.recv(65536)
            except (TimeoutError, BlockingIOError):
                return
            except OSError as exc:
                raise IndiError(f"connection lost: {exc}") from exc
            if not data:
                raise IndiError("INDI server closed the connection")
            self._parser.feed(data)
            self._consume()
            sock.settimeout(0.01)

    def _consume(self) -> None:
        assert self._parser is not None
        for event, elem in self._parser.read_events():
            if event == "start":
                self._depth += 1
                if self._depth == 1:
                    self._root = elem
            else:
                self._depth -= 1
                if self._depth == 1:  # a complete top-level message
                    self._handle(elem)
                    if self._root is not None:
                        self._root.remove(elem)

    def _handle(self, elem: ET.Element) -> None:
        tag, device, name = elem.tag, elem.get("device"), elem.get("name")
        if tag == "delProperty" and device:
            for key in [k for k in self._props if k[0] == device and (name is None or k[1] == name)]:
                del self._props[key]
            return
        if not device or not name:
            return
        if tag.endswith("NumberVector") or tag.endswith("SwitchVector") or tag.endswith("TextVector"):
            entry = self._props.setdefault((device, name), {"state": "Idle", "values": {}})
            if elem.get("state"):
                entry["state"] = elem.get("state")
            for child in elem:
                if child.get("name"):
                    entry["values"][child.get("name")] = (child.text or "").strip()

    # -- interpretation ---------------------------------------------------
    def _find_device(self) -> str | None:
        for device, name in self._props:
            if self._device and device != self._device:
                continue
            if any(name == prop for prop, _ in _COORD_PROPS):
                return device
        return None

    def _switch(self, device: str, prop: str, element: str) -> bool | None:
        entry = self._props.get((device, prop))
        if entry is None or element not in entry["values"]:
            return None
        return entry["values"][element].lower() == "on"

    def read(self) -> MountState:
        now = time.time()
        if self._sock is None:
            self._connect()
        try:
            self._pump()
        except IndiError:
            self.close()
            raise
        device = self._find_device()
        if device is None:
            self.close()
            raise IndiError("telescope device disappeared from the INDI server")
        connected = self._switch(device, "CONNECTION", "CONNECT")
        if connected is False:
            return MountState(status="disconnected", timestamp=now)
        coords, epoch = None, "jnow"
        for prop, ep in _COORD_PROPS:
            if (device, prop) in self._props:
                coords, epoch = self._props[(device, prop)], ep
                break
        assert coords is not None
        ra_h = parse_indi_number(coords["values"].get("RA"))
        dec = parse_indi_number(coords["values"].get("DEC"))
        horiz = self._props.get((device, "HORIZONTAL_COORD"), {"values": {}})["values"]
        parked = self._switch(device, "TELESCOPE_PARK", "PARK")
        tracking = self._switch(device, "TELESCOPE_TRACK_STATE", "TRACK_ON")
        vector_state = coords["state"]
        if vector_state == "Alert":
            status = "error"
        elif vector_state == "Busy":
            status = "slewing"
        elif parked:
            status = "parked"
        elif tracking:
            status = "tracking"
        else:
            status = "idle"
        return MountState(
            status=status,
            ra_deg=None if ra_h is None else ra_h * 15.0,
            dec_deg=dec,
            epoch=epoch,  # type: ignore[arg-type]
            alt_deg=parse_indi_number(horiz.get("ALT")),
            az_deg=parse_indi_number(horiz.get("AZ")),
            timestamp=now,
            error="driver reports an alert" if status == "error" else None,
        )
