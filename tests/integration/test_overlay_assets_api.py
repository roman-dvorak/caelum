"""`/api/overlay/assets` access control and the upload/list/delete round-trip."""

from __future__ import annotations

from .test_api_endpoints import VIEWER_PASSWORD, _build_harness, login


async def test_viewer_and_anonymous_cannot_write_overlay_assets(tmp_path, redis_url):
    harness = await _build_harness(tmp_path, redis_url, "ovtest1")
    try:
        async with harness.client() as anon:
            assert (await anon.get("/api/overlay/assets")).status_code == 401
            anon_upload = await anon.post("/api/overlay/assets", files={"file": ("a.png", b"x", "image/png")})
            assert anon_upload.status_code == 401

        async with harness.client() as viewer:
            await login(viewer, "viewer1", VIEWER_PASSWORD)
            assert (await viewer.get("/api/overlay/assets")).status_code == 403
            assert (
                await viewer.post("/api/overlay/assets", files={"file": ("a.png", b"x", "image/png")})
            ).status_code == 403
    finally:
        await harness.config_manager.stop()


async def test_admin_can_upload_list_fetch_and_delete_an_asset(tmp_path, redis_url):
    harness = await _build_harness(tmp_path, redis_url, "ovtest2")
    try:
        async with harness.client() as client:
            await login(client)

            png_bytes = b"\x89PNG\r\n\x1a\nnot a real png but good enough for this test"
            upload = await client.post("/api/overlay/assets", files={"file": ("logo.png", png_bytes, "image/png")})
            assert upload.status_code == 200
            name = upload.json()["name"]
            assert name.endswith(".png")

            listing = await client.get("/api/overlay/assets")
            assert any(a["name"] == name for a in listing.json())

            fetched = await client.get(f"/api/overlay/assets/{name}")
            assert fetched.status_code == 200
            assert fetched.content == png_bytes

            deleted = await client.delete(f"/api/overlay/assets/{name}")
            assert deleted.status_code == 200
            assert (await client.get(f"/api/overlay/assets/{name}")).status_code == 404
    finally:
        await harness.config_manager.stop()


async def test_unsupported_content_type_is_rejected(tmp_path, redis_url):
    harness = await _build_harness(tmp_path, redis_url, "ovtest3")
    try:
        async with harness.client() as client:
            await login(client)
            resp = await client.post(
                "/api/overlay/assets", files={"file": ("script.js", b"alert(1)", "application/javascript")}
            )
            assert resp.status_code == 415
    finally:
        await harness.config_manager.stop()
