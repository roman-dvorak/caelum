"""`/api/system/*` access control and the info payload shape."""

from __future__ import annotations

from .test_api_endpoints import VIEWER_PASSWORD, _build_harness, login


async def test_viewer_and_anonymous_cannot_reach_system_routes(tmp_path, redis_url):
    harness = await _build_harness(tmp_path, redis_url, "systest1")
    try:
        async with harness.client() as anon:
            assert (await anon.get("/api/system/info")).status_code == 401
            assert (await anon.post("/api/system/reboot")).status_code == 401

        async with harness.client() as viewer:
            await login(viewer, "viewer1", VIEWER_PASSWORD)
            assert (await viewer.get("/api/system/info")).status_code == 403
    finally:
        await harness.config_manager.stop()


async def test_admin_gets_system_info(tmp_path, redis_url):
    harness = await _build_harness(tmp_path, redis_url, "systest2")
    try:
        async with harness.client() as client:
            await login(client)
            resp = await client.get("/api/system/info")
            assert resp.status_code == 200
            body = resp.json()
            assert body["hostname"]
            assert 0.0 <= body["cpu_percent"] <= 100.0
            assert any(d["path"] == "/" for d in body["disks"])
    finally:
        await harness.config_manager.stop()
