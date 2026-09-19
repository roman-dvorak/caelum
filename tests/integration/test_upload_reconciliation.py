from __future__ import annotations

import json
import time

from caelum.config.manager import ConfigManager
from caelum.events import EventBus
from caelum.upload.uploader import UploadWorker


def _wait_until(predicate, timeout: float = 3.0, interval: float = 0.02) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


async def _make_config_manager(tmp_path, redis_url, key_prefix, remote_dir):
    config_manager = ConfigManager(
        disk_path=tmp_path / "config.json", default_path=None, redis_url=redis_url, key_prefix=key_prefix
    )
    await config_manager.start()
    await config_manager.update(
        {
            "upload": {
                "enabled": True,
                "remote_host": "",  # local-filesystem mode — no SSH/network involved
                "remote_base_path": str(remote_dir),
                "camera_slug": "cam0",
                "camera_name": "Test Cam",
                "thumbnail_interval_s": 9999,
                "reconcile_interval_s": 9999,
            }
        }
    )
    return config_manager


async def test_reconciliation_recovers_a_file_a_missed_incremental_push_would_have_caught(tmp_path, redis_url):
    local_dir = tmp_path / "local"
    remote_dir = tmp_path / "remote"
    local_dir.mkdir()
    remote_dir.mkdir()

    thumb = local_dir / "thumbnails" / "2026-01-01" / "120000.jpg"
    thumb.parent.mkdir(parents=True)
    thumb.write_bytes(b"fake-jpeg-bytes")
    thumb.with_suffix(".json").write_text("{}")

    config_manager = await _make_config_manager(tmp_path, redis_url, "uploadtest1", remote_dir)
    try:
        worker = UploadWorker(config_manager, EventBus(), local_dir)
        assert worker.uploaded_before() is None

        # Simulate the reconciliation pass firing without ever having seen
        # the incremental trigger — this is the scenario an incremental
        # push failing (crash, network blip) leaves behind.
        worker._reconcile(config_manager.current.upload)

        remote_thumb = remote_dir / "cam0" / "thumbnails" / "2026-01-01" / "120000.jpg"
        assert remote_thumb.exists()
        assert remote_thumb.read_bytes() == b"fake-jpeg-bytes"
        assert (remote_dir / "cam0" / "manifest.json").exists()

        cameras_index = json.loads((remote_dir / "cameras.json").read_text())
        assert cameras_index["cameras"][0]["slug"] == "cam0"

        assert worker.uploaded_before() is not None
    finally:
        await config_manager.stop()


async def test_second_camera_does_not_clobber_first_cameras_entry(tmp_path, redis_url):
    remote_dir = tmp_path / "remote"
    remote_dir.mkdir()

    local_dir_a = tmp_path / "local_a"
    local_dir_a.mkdir()
    (local_dir_a / "thumbnails" / "2026-01-01").mkdir(parents=True)
    (local_dir_a / "thumbnails" / "2026-01-01" / "100000.jpg").write_bytes(b"a")

    local_dir_b = tmp_path / "local_b"
    local_dir_b.mkdir()
    (local_dir_b / "thumbnails" / "2026-01-01").mkdir(parents=True)
    (local_dir_b / "thumbnails" / "2026-01-01" / "100000.jpg").write_bytes(b"b")

    cm_a = await _make_config_manager(tmp_path, redis_url, "uploadtest2a", remote_dir)
    cm_b = await _make_config_manager(tmp_path, redis_url, "uploadtest2b", remote_dir)
    await cm_b.update({"upload": {"camera_slug": "cam1", "camera_name": "Cam One"}})
    try:
        worker_a = UploadWorker(cm_a, EventBus(), local_dir_a)
        worker_b = UploadWorker(cm_b, EventBus(), local_dir_b)

        worker_a._reconcile(cm_a.current.upload)
        worker_b._reconcile(cm_b.current.upload)

        cameras_index = json.loads((remote_dir / "cameras.json").read_text())
        slugs = {c["slug"] for c in cameras_index["cameras"]}
        assert slugs == {"cam0", "cam1"}
        assert (remote_dir / "cam0" / "thumbnails" / "2026-01-01" / "100000.jpg").read_bytes() == b"a"
        assert (remote_dir / "cam1" / "thumbnails" / "2026-01-01" / "100000.jpg").read_bytes() == b"b"
    finally:
        await cm_a.stop()
        await cm_b.stop()
