from __future__ import annotations

from caelum.events import EventBus
from caelum.upload.uploader import UploadWorker
from tests.integration.test_api_endpoints import VIEWER_PASSWORD, _build_harness, login


async def test_upload_status_and_sync(tmp_path, redis_url):
    harness = await _build_harness(tmp_path, redis_url, "uploadapi1")
    worker = UploadWorker(harness.config_manager, EventBus(), harness.data_dir)
    harness.app.state.upload_worker = worker
    try:
        async with harness.client() as client:
            assert (await client.get("/api/upload/status")).status_code == 401
            await login(client, "viewer1", VIEWER_PASSWORD)
            assert (await client.get("/api/upload/status")).status_code == 403
        async with harness.client() as client:
            await login(client)
            status = (await client.get("/api/upload/status")).json()
            assert status["enabled"] is False and status["last_reconcile"] is None
            assert (await client.post("/api/upload/sync")).status_code == 409

            await harness.config_manager.update(
                {"upload": {"enabled": True, "remote_user": "svc", "remote_base_path": str(tmp_path / "r")}}
            )
            status = (await client.get("/api/upload/status")).json()
            assert "remote_host is empty" in status["config_problem"]
            assert "local path on this device" in status["target"]
            synced = await client.post("/api/upload/sync")
            assert synced.status_code == 200 and synced.json()["sync_requested"] is True
    finally:
        await harness.config_manager.stop()
