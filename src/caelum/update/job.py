"""The one update that may be in flight, driven from the web UI.

Runs on its own thread (pip can take minutes on a Pi) and narrates through
the `caelum.update` logger: a dedicated `LogBuffer` on that logger backs the
UI's install log (`/ws/update`), and the lines propagate into the main log as
well.
"""

from __future__ import annotations

import hashlib
import logging
import shutil
import threading
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from caelum import __version__
from caelum.logging_conf import LogBuffer

from . import manifest, releases
from .releases import ReleaseLayout, UpdateError

logger = logging.getLogger("caelum.update")

JobState = Literal["idle", "downloading", "installing", "restarting", "failed"]

_DOWNLOAD_TIMEOUT_S = 60
MAX_WHEEL_BYTES = 100 * 1024 * 1024


class UpdateBusyError(Exception):
    pass


class Updater:
    def __init__(
        self,
        layout: ReleaseLayout,
        request_restart: Callable[[], None],
        make_room: Callable[[Path, float], None] | None = None,
    ) -> None:
        """`make_room(path, mb)`: try to get `mb` MB free on `path`'s
        filesystem (retention deleting already-uploaded frames early)."""
        self.layout = layout
        self._request_restart = request_restart
        self._make_room = make_room
        self._lock = threading.Lock()
        self.state: JobState = "idle"
        self.target: str | None = None
        self.error: str | None = None
        self.available: manifest.Release | None = None
        self.checked_at: str | None = None
        self.check_error: str | None = None

        self.log_buffer = LogBuffer(capacity=1000)
        logger.addHandler(self.log_buffer)

    # -- checking ------------------------------------------------------------

    def check(self, manifest_url: str) -> None:
        self.checked_at = datetime.now(UTC).isoformat(timespec="seconds")
        try:
            self.available = manifest.latest_newer(manifest.fetch_manifest(manifest_url), __version__)
            self.check_error = None
        except manifest.ManifestError as exc:
            self.available = None
            self.check_error = str(exc)

    # -- running -------------------------------------------------------------

    @property
    def busy(self) -> bool:
        return self.state in ("downloading", "installing", "restarting")

    def _begin(self, target: str | None) -> None:
        with self._lock:
            if self.busy:
                raise UpdateBusyError(f"An update to {self.target} is already {self.state}")
            self.state = "downloading"
            self.target = target
            self.error = None

    def start_release(self, release: manifest.Release) -> None:
        self._begin(release.version)
        threading.Thread(target=self._run, args=(release, None), name="update", daemon=True).start()

    def start_wheel(self, wheel: Path) -> None:
        self._begin(releases.wheel_version(wheel))
        threading.Thread(target=self._run, args=(None, wheel), name="update", daemon=True).start()

    def incoming_path(self, filename: str) -> Path:
        self.layout.incoming.mkdir(parents=True, exist_ok=True)
        return self.layout.incoming / Path(filename).name

    def _download(self, release: manifest.Release) -> Path:
        wheel = self.incoming_path(release.wheel_url.rsplit("/", 1)[-1])
        logger.info("Downloading %s", release.wheel_url)
        digest = hashlib.sha256()
        size = 0
        with urllib.request.urlopen(release.wheel_url, timeout=_DOWNLOAD_TIMEOUT_S) as response, wheel.open("wb") as f:
            while chunk := response.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_WHEEL_BYTES:
                    raise UpdateError("Download exceeds the size limit for a wheel")
                digest.update(chunk)
                f.write(chunk)
        if release.sha256 and digest.hexdigest() != release.sha256.lower():
            raise UpdateError(f"Checksum mismatch for {wheel.name} — refusing to install it")
        logger.info("Downloaded %s (%.1f MB)", wheel.name, size / 1e6)
        return wheel

    def _ensure_space(self) -> None:
        """Fail before touching anything rather than with pip's ENOSPC
        halfway through the install."""
        needed = releases.required_space_mb(self.layout)
        free = releases.free_space_mb(self.layout.root)
        if free < needed and self._make_room is not None:
            logger.info("%.0f MB free, the install needs about %d MB — making room", free, needed)
            self._make_room(self.layout.root, needed)
            free = releases.free_space_mb(self.layout.root)
        if free < needed:
            raise UpdateError(
                f"Not enough disk space: {free:.0f} MB free, the install needs about {needed} MB. "
                "Free some space and try again."
            )

    def _run(self, release: manifest.Release | None, wheel: Path | None) -> None:
        try:
            self._ensure_space()
            if release is not None:
                wheel = self._download(release)
            assert wheel is not None
            self.state = "installing"
            logger.info("Installing %s next to the running %s", wheel.name, __version__)
            version = releases.install_release(self.layout, wheel, logger.info)
            releases.switch_to(self.layout, version)
            self.state = "restarting"
            logger.info("Switched to %s — restarting", version)
            self._request_restart()
        except Exception as exc:
            logger.exception("Update failed")
            self.state = "failed"
            self.error = str(exc)
        finally:
            if wheel is not None and self.state == "failed":
                shutil.rmtree(self.layout.incoming, ignore_errors=True)
