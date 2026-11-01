"""Thermal status of the AMRPI4HAT01 camera management board.

The board's own control software writes `/var/run/thermal-control-status.json`
(flat dict: temperatures, humidity, pressure, dew points, PWM, flags).
`ThermalStatusPoller` re-reads it on its own thread, so capture never waits
on the file: the capture thread only calls `snapshot()`, which returns the
last good reading from memory.

The poller is owned by `main.py` (one instance for the process) rather than
by the `thermal_status` plugin, because plugins are rebuilt on every config
change and would leak a thread each time. The plugin's settings are handed
to `configure()` instead.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

#: Keys of the status file that can be stored with a frame or used as
#: `{placeholders}` in overlay templates.
THERMAL_FIELDS: tuple[str, ...] = (
    "dome_temp",
    "body_temp",
    "envi_temp",
    "dome_humidity",
    "body_humidity",
    "envi_humidity",
    "body_pressure",
    "dome_dew_point",
    "body_dew_point",
    "envi_dew_point",
    "heater_pwm",
    "fan_pwm",
    "cpu_fan_state",
    "target_temp",
    "cooling_min",
    "cooling_max",
    "fan_override",
    "heater_override",
    "error_count",
    "cpu_temp",
    "cpu_fan_threshold",
    "body_fan_threshold",
    "failsafe_mode",
    "dome_available",
    "body_available",
    "envi_available",
)

#: Annotation key under which a frame carries the reading.
ANNOTATION_KEY = "thermal"


class ThermalStatusSettings(BaseModel):
    path: str = "/var/run/thermal-control-status.json"
    poll_interval_s: float = Field(default=5.0, gt=0.0)
    #: A reading whose file is older than this is not attached to frames.
    max_age_s: float = Field(default=60.0, gt=0.0)
    #: Fields stored in the frame metadata (sidecar JSON and DNG XMP).
    metadata_fields: list[str] = Field(
        default_factory=lambda: [
            "dome_temp",
            "body_temp",
            "envi_temp",
            "dome_humidity",
            "body_humidity",
            "envi_humidity",
            "body_pressure",
            "dome_dew_point",
            "heater_pwm",
            "fan_pwm",
            "failsafe_mode",
        ]
    )


class ThermalStatusPoller(threading.Thread):
    def __init__(self) -> None:
        super().__init__(name="ThermalStatusPoller", daemon=True)
        self._lock = threading.Lock()
        self._settings: ThermalStatusSettings | None = None
        self._reading: dict[str, Any] | None = None
        self._mtime: float = 0.0
        self._stop_event = threading.Event()
        self._wake = threading.Event()

    def configure(self, settings: ThermalStatusSettings | None) -> None:
        """`None` pauses polling (plugin disabled or removed)."""
        with self._lock:
            self._settings = settings
            if settings is None:
                self._reading = None
        self._wake.set()

    def request_stop(self) -> None:
        self._stop_event.set()
        self._wake.set()

    def snapshot(self) -> dict[str, Any] | None:
        """The last reading restricted to the configured `metadata_fields`,
        plus `age_s`; None when polling is off, nothing was read yet, or
        the status file has not been updated for `max_age_s`."""
        with self._lock:
            settings, reading, mtime = self._settings, self._reading, self._mtime
        if settings is None or reading is None:
            return None
        age = time.time() - mtime
        if age > settings.max_age_s:
            return None
        values = {k: reading[k] for k in settings.metadata_fields if k in reading}
        return {**values, "age_s": round(age, 1)}

    def poll_once(self) -> None:
        with self._lock:
            settings = self._settings
        if settings is None:
            return
        try:
            path = Path(settings.path)
            mtime = os.stat(path).st_mtime
            data = json.loads(path.read_text())
        except (OSError, ValueError) as exc:
            logger.debug("Thermal status unreadable (%s): %s", settings.path, exc)
            return
        if not isinstance(data, dict):
            return
        reading = {k: data[k] for k in THERMAL_FIELDS if k in data}
        with self._lock:
            self._reading, self._mtime = reading, mtime

    def run(self) -> None:
        while not self._stop_event.is_set():
            self._wake.clear()
            try:
                self.poll_once()
            except Exception:
                logger.exception("Thermal status poll failed")
            with self._lock:
                interval = self._settings.poll_interval_s if self._settings else 1.0
            self._wake.wait(interval)
