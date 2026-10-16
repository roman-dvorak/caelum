"""`/api/overlay/assets` access control and the upload/list/delete round-trip."""

from __future__ import annotations

import io

from PIL import Image

from tests.factories import make_image, make_processed_frame

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


async def test_overlay_preview_renders_a_draft_template_on_the_latest_frame(tmp_path, redis_url):
    harness = await _build_harness(tmp_path, redis_url, "ovtest3")
    try:
        async with harness.client() as client:
            await login(client)
            draft = [{"id": "m", "kind": "mask", "x": 0, "y": 0, "w": 0.5, "h": 0.5, "color": "#00ff00"}]
            assert (await client.post("/api/overlay/preview.png", json=draft)).status_code == 404

            harness.frame_store.update(make_processed_frame(image=make_image(width=400, height=200)))
            response = await client.post("/api/overlay/preview.png", json=draft)
            assert response.status_code == 200
            layer = Image.open(io.BytesIO(response.content))
            assert layer.size == (400, 200)
            assert layer.getpixel((50, 50)) == (0, 255, 0, 255)

            # The live layer only exists once the pool has rendered it.
            assert (await client.get("/api/frame/overlay.png")).status_code == 404
            latest = harness.frame_store.get_latest()
            harness.frame_store.set_overlay(latest.metadata.captured_at, [], "file", response.content)
            live = await client.get("/api/frame/overlay.png")
            assert live.status_code == 200 and live.content == response.content
    finally:
        await harness.config_manager.stop()
