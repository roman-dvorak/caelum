"""Atomic disk persistence for AppConfig — the durable source of truth."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from .schema import AppConfig


def read(path: Path) -> AppConfig | None:
    if not path.exists():
        return None
    return AppConfig.model_validate_json(path.read_text())


def write(path: Path, config: AppConfig) -> None:
    """Write atomically: a crash/power-loss between these two steps still
    leaves either the old or the new file intact, never a truncated one —
    important on an SD card that can lose power at any moment."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = config.model_dump_json(indent=2)
    fd, tmp_path = tempfile.mkstemp(prefix=".config-", suffix=".json.tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        Path(tmp_path).unlink(missing_ok=True)
        raise
