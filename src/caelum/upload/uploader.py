"""Keeps local and remote convergent via two triggers:

- **Incremental push** — today's date directories only, run frequently
  (`upload.thumbnail_interval_s`), so new thumbnails/raw/derivatives show up
  on the remote promptly.
- **Reconciliation pass** — every published capture (thumbnails, raw,
  derivatives — nothing else in the data directory), run less often
  (`upload.reconcile_interval_s`). The transport (rsync, or the listing
  diff of transport_scp.py / transport_s3.py) compares source vs. destination
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
from caelum.storage import paths

from . import manifest, transport_rsync, transport_s3, transport_scp
from .stats import TransferStats

logger = logging.getLogger(__name__)

_IDLE_POLL_S = 5.0


_TRANSPORTS = {"rsync": transport_rsync, "scp": transport_scp, "s3": transport_s3}


def _transport(cfg: UploadConfig):
    """Every module exposes the same push_tree/push_file/pull_file trio."""
    return _TRANSPORTS.get(cfg.transport, transport_rsync)


class UploadWorker(threading.Thread):
    def __init__(self, config_manager: ConfigManager, event_bus: EventBus, data_dir: Path) -> None:
        super().__init__(name="UploadWorker", daemon=True)
        self._config_manager = config_manager
        self._data_dir = data_dir
        self._stop_event = threading.Event()
        self._pending_incremental = threading.Event()
        self._last_reconcile_monotonic = 0.0
        self._uploaded_before: datetime | None = None
        self._sync_requested = threading.Event()
        self._lock = threading.Lock()
        self._state: dict = {
            "running": None,
            "last_incremental": None,
            "last_reconcile": None,
            "last_success_at": None,
            "last_error": None,
            "consecutive_failures": 0,
        }
        event_bus.subscribe(FRAME_CAPTURED, self._on_frame_captured)

    def request_stop(self) -> None:
        self._stop_event.set()
        self._pending_incremental.set()

    def request_sync(self) -> None:
        """Run a full reconciliation pass now instead of at its interval."""
        self._sync_requested.set()
        self._pending_incremental.set()

    @property
    def status(self) -> dict:
        cfg = self._config_manager.current.upload
        with self._lock:
            state = dict(self._state)
        next_in = None
        if cfg.enabled and self._last_reconcile_monotonic:
            next_in = max(0.0, cfg.reconcile_interval_s - (time.monotonic() - self._last_reconcile_monotonic))
        return {
            "enabled": cfg.enabled,
            "transport": cfg.transport,
            "target": _describe_target(cfg),
            "config_problem": _config_problem(cfg),
            **state,
            "uploaded_before": self._uploaded_before.isoformat() if self._uploaded_before else None,
            "next_reconcile_in_s": round(next_in, 1) if next_in is not None else None,
            "sync_requested": self._sync_requested.is_set(),
        }

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
                    if self._stop_event.is_set():
                        break
                    if not self._sync_requested.is_set():
                        self._incremental_push(cfg)

                due = time.monotonic() - self._last_reconcile_monotonic >= cfg.reconcile_interval_s
                if due or self._sync_requested.is_set():
                    self._sync_requested.clear()
                    self._reconcile(cfg)
                    self._last_reconcile_monotonic = time.monotonic()
            except Exception:
                logger.exception("Upload cycle failed")
                self._stop_event.wait(_IDLE_POLL_S)

    def _begin(self, kind: str) -> tuple[TransferStats, float, datetime]:
        with self._lock:
            self._state["running"] = kind
        return TransferStats(), time.monotonic(), datetime.now(UTC)

    def _finish(self, kind: str, stats: TransferStats, started: float, started_at: datetime, ok: bool) -> None:
        ok = ok and not stats.errors
        record = {
            "at": started_at.isoformat(),
            "ok": ok,
            "duration_s": round(time.monotonic() - started, 2),
            "files": stats.files,
            "bytes": stats.bytes,
            "errors": stats.errors,
        }
        with self._lock:
            self._state["running"] = None
            self._state[f"last_{kind}"] = record
            if ok:
                self._state["last_success_at"] = record["at"]
                self._state["consecutive_failures"] = 0
            else:
                self._state["consecutive_failures"] += 1
                self._state["last_error"] = {"at": record["at"], "pass": kind,
                                             "message": stats.errors[0] if stats.errors else "upload failed"}
        if ok and stats.files:
            logger.info("Upload %s pass: %d file(s), %.1f MB in %.1fs", kind, stats.files, stats.bytes / 1e6,
                        record["duration_s"])

    def _incremental_push(self, cfg: UploadConfig) -> None:
        stats, started, started_at = self._begin("incremental")
        ok = False
        try:
            # "Today" is a UTC date, and storage/paths.py nests it as YYYY/MM/DD
            # on disk — translate once here so both the local lookup and the
            # remote target mirror that layout exactly.
            today_path = datetime.now(UTC).date().isoformat().replace("-", "/")
            ok = True
            for subdir in ("thumbnails", "raw", "derivatives"):
                local = self._data_dir / subdir / today_path
                if local.exists():
                    target = f"{cfg.camera_slug}/{subdir}/{today_path}"
                    ok = _transport(cfg).push_tree(cfg, local, target, stats=stats) and ok
            ok = self._push_manifests(cfg, stats) and ok
        except Exception as exc:
            stats.error(f"{type(exc).__name__}: {exc}")
            raise
        finally:
            self._finish("incremental", stats, started, started_at, ok)

    def _reconcile(self, cfg: UploadConfig) -> None:
        logger.info("Running full upload reconciliation pass")
        stats, started, started_at = self._begin("reconcile")
        ok = False
        try:
            # Only the published captures — never the rest of the data directory
            # (capture-program sources, program test runs, overlay assets, darks).
            ok = True
            for subdir in paths.MANAGED_SUBDIRS:
                target = f"{cfg.camera_slug}/{subdir}"
                ok = _transport(cfg).push_tree(cfg, self._data_dir / subdir, target, stats=stats) and ok
            ok = self._push_manifests(cfg, stats) and ok
            if ok and not stats.errors:
                self._uploaded_before = started_at
        except Exception as exc:
            stats.error(f"{type(exc).__name__}: {exc}")
            raise
        finally:
            self._finish("reconcile", stats, started, started_at, ok)

    def _push_manifests(self, cfg: UploadConfig, stats: TransferStats | None = None) -> bool:
        location = self._config_manager.current.location
        camera_manifest = manifest.write_local_manifests(
            self._data_dir, cfg.camera_slug, cfg.camera_name, {"lat": location.lat, "lon": location.lon}
        )
        ok = _transport(cfg).push_file(
            cfg, self._data_dir / "manifest.json", f"{cfg.camera_slug}/manifest.json", stats=stats
        )
        return self._update_cameras_index(cfg, camera_manifest, stats) and ok

    def _update_cameras_index(self, cfg: UploadConfig, camera_manifest: dict,
                              stats: TransferStats | None = None) -> bool:
        with tempfile.TemporaryDirectory() as tmp:
            cameras_json_path = Path(tmp) / "cameras.json"
            _transport(cfg).pull_file(cfg, "cameras.json", cameras_json_path)
            existing = json.loads(cameras_json_path.read_text()) if cameras_json_path.exists() else None

            merged = manifest.merge_cameras_index(
                existing, cfg.camera_slug, cfg.camera_name, camera_manifest, datetime.now(UTC)
            )
            cameras_json_path.write_text(json.dumps(merged, indent=2))
            return _transport(cfg).push_file(cfg, cameras_json_path, "cameras.json", stats=stats)


def _describe_target(cfg: UploadConfig) -> str:
    if cfg.transport == "s3":
        where = f"s3://{cfg.s3_bucket}/{cfg.s3_prefix}".rstrip("/")
        return f"{where} at {cfg.s3_endpoint_url}" if cfg.s3_endpoint_url else where
    if not cfg.remote_host:
        return f"{cfg.remote_base_path} (local path on this device)"
    user = f"{cfg.remote_user}@" if cfg.remote_user else ""
    port = f" port {cfg.ssh_port}" if cfg.ssh_port != 22 else ""
    return f"{user}{cfg.remote_host}:{cfg.remote_base_path}{port}"


def _config_problem(cfg: UploadConfig) -> str | None:
    """An obvious misconfiguration, worded for the status panel."""
    if cfg.transport == "s3":
        return None if cfg.s3_bucket else "upload.s3_bucket is empty"
    if cfg.transport == "scp" and not cfg.remote_host:
        return "upload.remote_host is empty — scp needs a server"
    if cfg.transport == "rsync" and not cfg.remote_host and cfg.remote_user:
        return ("upload.remote_host is empty, so remote_base_path is used as a local path on this device "
                "(remote_user is ignored) — set remote_host to upload to a server")
    if cfg.transport != "s3" and cfg.remote_host and not Path(cfg.ssh_key_path).exists():
        return f"SSH key {cfg.ssh_key_path} not found"
    return None
