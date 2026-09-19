"""Keeps local and remote convergent via two triggers:

- **Incremental push** — today's date directories only, run frequently
  (`upload.thumbnail_interval_s`), so new thumbnails/raw/derivatives show up
  on the remote promptly.
- **Reconciliation pass** — the *entire* local tree, run less often
  (`upload.reconcile_interval_s`). rsync compares source vs. destination
  itself, so this is naturally idempotent and self-healing: anything an
  incremental push missed (a reboot mid-transfer, a network blip) gets
  picked up here with no separate ledger/retry-queue needed. Only a
  reconciliation pass advances the "confirmed uploaded" watermark that
  retention uses — the incremental pass only proves *today* is covered.
"""

from __future__ import annotations

import json
import logging
import tempfile
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

from caelum.capture.frame_store import ProcessedFrame
from caelum.config.manager import ConfigManager
from caelum.config.schema import UploadConfig
from caelum.events import FRAME_CAPTURED, EventBus

from . import manifest, transport_rsync

logger = logging.getLogger(__name__)

_IDLE_POLL_S = 5.0


class UploadWorker(threading.Thread):
    def __init__(self, config_manager: ConfigManager, event_bus: EventBus, data_dir: Path) -> None:
        super().__init__(name="UploadWorker", daemon=True)
        self._config_manager = config_manager
        self._data_dir = data_dir
        self._stop_event = threading.Event()
        self._pending_incremental = threading.Event()
        self._last_reconcile_monotonic = 0.0
        self._uploaded_before: datetime | None = None
        event_bus.subscribe(FRAME_CAPTURED, self._on_frame_captured)

    def request_stop(self) -> None:
        self._stop_event.set()

    def uploaded_before(self) -> datetime | None:
        """Newest capture time confirmed present on the remote after a full
        reconciliation pass — retention.py's "safe to delete" watermark."""
        return self._uploaded_before

    def _on_frame_captured(self, _frame: ProcessedFrame) -> None:
        self._pending_incremental.set()

    def run(self) -> None:
        while not self._stop_event.is_set():
            cfg = self._config_manager.current.upload
            if not cfg.enabled:
                self._stop_event.wait(_IDLE_POLL_S)
                continue
            try:
                if self._pending_incremental.wait(timeout=cfg.thumbnail_interval_s):
                    self._pending_incremental.clear()
                    self._incremental_push(cfg)

                if time.monotonic() - self._last_reconcile_monotonic >= cfg.reconcile_interval_s:
                    self._reconcile(cfg)
                    self._last_reconcile_monotonic = time.monotonic()
            except Exception:
                logger.exception("Upload cycle failed")
                self._stop_event.wait(_IDLE_POLL_S)

    def _incremental_push(self, cfg: UploadConfig) -> None:
        # "Today" is a UTC date, and storage/paths.py nests it as YYYY/MM/DD
        # on disk — translate once here so both the local lookup and the
        # remote target mirror that layout exactly.
        today_path = datetime.now(UTC).date().isoformat().replace("-", "/")
        for subdir in ("thumbnails", "raw", "derivatives"):
            local = self._data_dir / subdir / today_path
            if local.exists():
                transport_rsync.push_tree(cfg, local, f"{cfg.camera_slug}/{subdir}/{today_path}")
        self._push_manifests(cfg)

    def _reconcile(self, cfg: UploadConfig) -> None:
        logger.info("Running full upload reconciliation pass")
        ok = transport_rsync.push_tree(cfg, self._data_dir, cfg.camera_slug)
        self._push_manifests(cfg)
        if ok:
            self._uploaded_before = datetime.now(UTC)

    def _push_manifests(self, cfg: UploadConfig) -> None:
        location = self._config_manager.current.location
        camera_manifest = manifest.write_local_manifests(
            self._data_dir, cfg.camera_slug, cfg.camera_name, {"lat": location.lat, "lon": location.lon}
        )
        transport_rsync.push_file(
            cfg, self._data_dir / "manifest.json", f"{cfg.camera_slug}/manifest.json"
        )
        self._update_cameras_index(cfg, camera_manifest)

    def _update_cameras_index(self, cfg: UploadConfig, camera_manifest: dict) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cameras_json_path = Path(tmp) / "cameras.json"
            transport_rsync.pull_file(cfg, "cameras.json", cameras_json_path)
            existing = json.loads(cameras_json_path.read_text()) if cameras_json_path.exists() else None

            merged = manifest.merge_cameras_index(
                existing, cfg.camera_slug, cfg.camera_name, camera_manifest, datetime.now(UTC)
            )
            cameras_json_path.write_text(json.dumps(merged, indent=2))
            transport_rsync.push_file(cfg, cameras_json_path, "cameras.json")
