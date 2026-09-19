"""Local-disk rotation.

Local disk is a rotating *cache*, not the archive — the remote storage
server (see upload/) is the permanent copy. A file is only deleted once
it's confirmed uploaded, *unless* upload is disabled entirely, in which case
the local copy is the only copy that will ever exist and retention runs on
age/space alone — the user's own configuration choice. This means a local
disk that's genuinely full with upload lagging far behind will not free
space until upload catches up; that tradeoff (data safety over guaranteed
free space) is deliberate, not an oversight.
"""

from __future__ import annotations

import logging
import shutil
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from caelum.config.manager import ConfigManager
from caelum.config.schema import RetentionConfig, UploadConfig

from . import paths

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RetentionResult:
    deleted_files: int
    freed_bytes: int


def _candidates(data_dir: Path) -> list[tuple[datetime, Path, int]]:
    found: list[tuple[datetime, Path, int]] = []
    for subdir in paths.MANAGED_SUBDIRS:
        base = data_dir / subdir
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or path.suffix == ".json":
                continue
            when = paths.capture_time_of(path)
            if when is None:
                continue
            found.append((when, path, path.stat().st_size))
    return found


def _free_space_mb(data_dir: Path) -> float:
    usage = shutil.disk_usage(data_dir)
    return usage.free / (1024 * 1024)


def _delete(path: Path) -> int:
    size = path.stat().st_size if path.exists() else 0
    path.unlink(missing_ok=True)
    paths.sidecar_path(path).unlink(missing_ok=True)
    return size


def sweep(
    data_dir: Path,
    retention_cfg: RetentionConfig,
    upload_cfg: UploadConfig,
    uploaded_before: datetime | None,
    now: datetime | None = None,
) -> RetentionResult:
    now = now or datetime.now(UTC)
    data_dir.mkdir(parents=True, exist_ok=True)

    candidates = _candidates(data_dir)
    if upload_cfg.enabled:
        candidates = [c for c in candidates if uploaded_before is not None and c[0] < uploaded_before]
    candidates.sort(key=lambda c: c[0])  # oldest first

    deleted = 0
    freed = 0

    max_age_cutoff = now - timedelta(days=retention_cfg.max_age_days)
    remaining = []
    for when, path, size in candidates:
        if when < max_age_cutoff:
            freed += _delete(path)
            deleted += 1
        else:
            remaining.append((when, path, size))
    candidates = remaining

    while candidates and _free_space_mb(data_dir) < retention_cfg.min_free_space_mb:
        _when, path, _size = candidates.pop(0)
        freed += _delete(path)
        deleted += 1

    return RetentionResult(deleted_files=deleted, freed_bytes=freed)


class RetentionSweeper(threading.Thread):
    def __init__(
        self,
        config_manager: ConfigManager,
        data_dir: Path,
        get_uploaded_before: Callable[[], datetime | None] = lambda: None,
    ) -> None:
        super().__init__(name="RetentionSweeper", daemon=True)
        self._config_manager = config_manager
        self._data_dir = data_dir
        self._get_uploaded_before = get_uploaded_before
        self._stop_event = threading.Event()

    def request_stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        while not self._stop_event.is_set():
            cfg = self._config_manager.current
            try:
                result = sweep(self._data_dir, cfg.retention, cfg.upload, self._get_uploaded_before())
                if result.deleted_files:
                    logger.info(
                        "Retention sweep deleted %d file(s), freed %.1f MB",
                        result.deleted_files,
                        result.freed_bytes / (1024 * 1024),
                    )
            except Exception:
                logger.exception("Retention sweep failed")
            self._stop_event.wait(cfg.retention.sweep_interval_s)
