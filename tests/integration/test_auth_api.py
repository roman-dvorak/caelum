"""Access control as seen through the HTTP surface.

These assert the thing that actually matters: that a caller without the
right session cannot reach the control endpoints, whatever the route
implementation happens to do internally.
"""

from __future__ import annotations

from .test_api_endpoints import ADMIN_PASSWORD, VIEWER_PASSWORD, _build_harness, login


async def test_anonymous_callers_are_rejected(tmp_path, redis_url):
    harness = await _build_harness(tmp_path, redis_url, "authtest1")
    try:
        async with harness.client() as client:
            for method, path in [
                ("get", "/api/status"),
                ("get", "/api/config"),
                ("get", "/api/plugins"),
                ("get", "/api/files"),
                ("get", "/api/frames/dates"),
            ]:
                resp = await getattr(client, method)(path)
                assert resp.status_code == 401, f"{path} was reachable anonymously"

            # The bootstrap endpoint must stay open — the SPA needs it to
            # know whether to render a login form at all.
            assert (await client.get("/api/auth/context")).status_code == 200
    finally:
        await harness.config_manager.stop()


async def test_login_logout_cycle(tmp_path, redis_url):
    harness = await _build_harness(tmp_path, redis_url, "authtest2")
    try:
        async with harness.client() as client:
            assert (await login(client, "admin", "wrong")).status_code == 401
            assert (await client.get("/api/config")).status_code == 401

            resp = await login(client)
            assert resp.status_code == 200
            assert resp.json()["role"] == "admin"
            assert (await client.get("/api/config")).status_code == 200

            await client.post("/api/auth/logout")
            assert (await client.get("/api/config")).status_code == 401
    finally:
        await harness.config_manager.stop()


async def test_viewer_can_preview_but_not_control(tmp_path, redis_url):
    harness = await _build_harness(tmp_path, redis_url, "authtest3")
    try:
        async with harness.client() as client:
            await login(client, "viewer1", VIEWER_PASSWORD)

            assert (await client.get("/api/status")).status_code == 200
            assert (await client.get("/api/frames/dates")).status_code == 200

            assert (await client.get("/api/config")).status_code == 403
            assert (await client.post("/api/camera/mode", json={"stream_mode": True})).status_code == 403
            assert (await client.get("/api/auth/users")).status_code == 403
            assert (await client.delete("/api/files", params={"path": "thumbnails"})).status_code == 403
    finally:
        await harness.config_manager.stop()


async def test_public_preview_access_opens_the_read_only_surface(tmp_path, redis_url):
    harness = await _build_harness(tmp_path, redis_url, "authtest4")
    try:
        async with harness.client() as client:
            await login(client)
            await client.put("/api/config", json={"patch": {"auth": {"preview_access": "public"}}})
            await client.post("/api/auth/logout")

            # Anonymous now sees the preview...
            assert (await client.get("/api/status")).status_code == 200
            assert (await client.get("/api/frames/dates")).status_code == 200
            # ...but control is still admin-only.
            assert (await client.get("/api/config")).status_code == 401
    finally:
        await harness.config_manager.stop()


async def test_admin_preview_access_hides_preview_from_viewers(tmp_path, redis_url):
    harness = await _build_harness(tmp_path, redis_url, "authtest5")
    try:
        async with harness.client() as admin:
            await login(admin)
            await admin.put("/api/config", json={"patch": {"auth": {"preview_access": "admin"}}})

        async with harness.client() as viewer:
            await login(viewer, "viewer1", VIEWER_PASSWORD)
            assert (await viewer.get("/api/status")).status_code == 403
    finally:
        await harness.config_manager.stop()


async def test_disabling_auth_makes_everyone_an_admin(tmp_path, redis_url):
    harness = await _build_harness(tmp_path, redis_url, "authtest6")
    try:
        async with harness.client() as client:
            await login(client)
            await client.put("/api/config", json={"patch": {"auth": {"enabled": False}}})

        async with harness.client() as anon:
            assert (await anon.get("/api/config")).status_code == 200
            context = (await anon.get("/api/auth/context")).json()
            assert context["auth_enabled"] is False
            assert context["role"] == "admin"
    finally:
        await harness.config_manager.stop()


async def test_changing_password_invalidates_other_sessions(tmp_path, redis_url):
    harness = await _build_harness(tmp_path, redis_url, "authtest7")
    try:
        async with harness.client() as other_device:
            await login(other_device)
            assert (await other_device.get("/api/config")).status_code == 200

            async with harness.client() as here:
                await login(here)
                resp = await here.post(
                    "/api/auth/password",
                    json={"current_password": ADMIN_PASSWORD, "new_password": "a-brand-new-password"},
                )
                assert resp.status_code == 200
                # The tab that made the change keeps working...
                assert (await here.get("/api/config")).status_code == 200

            # ...every other session is logged out.
            assert (await other_device.get("/api/config")).status_code == 401
    finally:
        await harness.config_manager.stop()


async def test_wrong_current_password_is_refused(tmp_path, redis_url):
    harness = await _build_harness(tmp_path, redis_url, "authtest8")
    try:
        async with harness.client() as client:
            await login(client)
            resp = await client.post(
                "/api/auth/password",
                json={"current_password": "not-it", "new_password": "a-brand-new-password"},
            )
            assert resp.status_code == 403
    finally:
        await harness.config_manager.stop()


async def test_user_administration(tmp_path, redis_url):
    harness = await _build_harness(tmp_path, redis_url, "authtest9")
    try:
        async with harness.client() as client:
            await login(client)

            created = await client.post(
                "/api/auth/users", json={"username": "guest", "password": "guest-password", "role": "viewer"}
            )
            assert created.status_code == 201
            assert "password_hash" not in created.json()

            assert {u["username"] for u in (await client.get("/api/auth/users")).json()} == {
                "admin",
                "viewer1",
                "guest",
            }

            # Weak passwords and duplicate names are rejected, not silently accepted.
            assert (
                await client.post("/api/auth/users", json={"username": "x", "password": "short"})
            ).status_code == 422
            assert (
                await client.post(
                    "/api/auth/users", json={"username": "guest", "password": "another-password"}
                )
            ).status_code == 422

            assert (await client.put("/api/auth/users/guest", json={"role": "admin"})).json()["role"] == "admin"
            assert (await client.delete("/api/auth/users/admin")).status_code == 422  # own account
            assert (await client.delete("/api/auth/users/guest")).status_code == 200
    finally:
        await harness.config_manager.stop()


async def test_bearer_token_is_accepted(tmp_path, redis_url):
    """Scripts and `curl` authenticate with a header rather than a cookie."""
    harness = await _build_harness(tmp_path, redis_url, "authtest10")
    try:
        async with harness.client() as client:
            await login(client)
            token = client.cookies["caelum_session"]

        async with harness.client() as scripted:
            resp = await scripted.get("/api/config", headers={"Authorization": f"Bearer {token}"})
            assert resp.status_code == 200
    finally:
        await harness.config_manager.stop()
