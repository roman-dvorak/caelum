"""Host machine vitals for the web UI's System page — CPU/RAM/disk/temperature/
network readouts, plus shutdown/reboot. Everything here reads live state on
each call; there is nothing to cache and nothing persisted.

Sensor availability varies by platform (a dev laptop has no
`/sys/class/thermal` and often no `psutil.sensors_temperatures()` at all), so
every reading that can be missing degrades to `None`/`[]` rather than raising
— matching the existing convention in `cameras/picamera2_backend.py` of
failing soft on hardware that isn't there instead of gating on a Pi-detection
flag.
"""

from __future__ import annotations

import logging
import socket
import subprocess
from dataclasses import dataclass, field

import psutil

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DiskUsage:
    path: str
    total_bytes: int
    used_bytes: int
    free_bytes: int
    percent: float


@dataclass(frozen=True)
class NetworkInterface:
    name: str
    is_up: bool
    speed_mbps: int | None
    addresses: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SystemInfo:
    hostname: str
    uptime_s: float
    cpu_percent: float
    cpu_count: int
    load_avg: tuple[float, float, float] | None
    mem_total_bytes: int
    mem_used_bytes: int
    mem_percent: float
    disks: list[DiskUsage]
    temperatures_c: dict[str, float]
    network: list[NetworkInterface]


#: Paths worth reporting disk usage for: the root filesystem (what a Pi's SD
#: card actually fills up on) and wherever caelum itself is writing data.
_DISK_PATHS = ("/",)


def collect(data_dir: str | None = None) -> SystemInfo:
    paths = list(_DISK_PATHS)
    if data_dir and data_dir not in paths:
        paths.append(data_dir)

    return SystemInfo(
        hostname=socket.gethostname(),
        uptime_s=_uptime_s(),
        cpu_percent=psutil.cpu_percent(interval=0.1),
        cpu_count=psutil.cpu_count() or 1,
        load_avg=_load_avg(),
        mem_total_bytes=psutil.virtual_memory().total,
        mem_used_bytes=psutil.virtual_memory().used,
        mem_percent=psutil.virtual_memory().percent,
        disks=[_disk_usage(p) for p in paths],
        temperatures_c=_temperatures(),
        network=_network_interfaces(),
    )


def _uptime_s() -> float:
    import time

    return time.time() - psutil.boot_time()


def _load_avg() -> tuple[float, float, float] | None:
    # Windows has no notion of a load average; getloadavg() raises there.
    try:
        one, five, fifteen = psutil.getloadavg()
        return (one, five, fifteen)
    except (AttributeError, OSError):
        return None


def _disk_usage(path: str) -> DiskUsage:
    usage = psutil.disk_usage(path)
    return DiskUsage(
        path=path, total_bytes=usage.total, used_bytes=usage.used, free_bytes=usage.free, percent=usage.percent
    )


def _temperatures() -> dict[str, float]:
    # Only implemented on Linux; absent entirely on macOS/Windows, and often
    # empty even on Linux inside a container without sensor passthrough.
    reader = getattr(psutil, "sensors_temperatures", None)
    if reader is None:
        return {}
    try:
        sensors = reader()
    except OSError:
        return {}

    readings: dict[str, float] = {}
    for name, entries in sensors.items():
        for entry in entries:
            label = entry.label or name
            key = label if label not in readings else f"{name}:{label}"
            readings[key] = entry.current
    return readings


def _network_interfaces() -> list[NetworkInterface]:
    stats = psutil.net_if_stats()
    addrs = psutil.net_if_addrs()
    interfaces = []
    for name, family_addrs in addrs.items():
        stat = stats.get(name)
        interfaces.append(
            NetworkInterface(
                name=name,
                is_up=stat.isup if stat else False,
                speed_mbps=stat.speed if stat and stat.speed > 0 else None,
                addresses=[a.address for a in family_addrs if a.address],
            )
        )
    return sorted(interfaces, key=lambda i: i.name)


class PowerActionError(Exception):
    """Raised when the host refuses or fails to execute a shutdown/reboot."""


def shutdown() -> None:
    _run_power_command(["systemctl", "poweroff"])


def reboot() -> None:
    _run_power_command(["systemctl", "reboot"])


def _run_power_command(command: list[str]) -> None:
    logger.warning("System power action requested: %s", " ".join(command))
    try:
        subprocess.run(command, check=True, timeout=10, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise PowerActionError(f"{command[0]} is not available on this host") from exc
    except subprocess.CalledProcessError as exc:
        raise PowerActionError(exc.stderr.strip() or f"{' '.join(command)} exited with {exc.returncode}") from exc
    except subprocess.TimeoutExpired as exc:
        raise PowerActionError(f"{' '.join(command)} did not respond within 10s") from exc
