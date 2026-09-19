"""`GET /api/logs` access control and content."""

from __future__ import annotations

import logging

from .test_api_endpoints import VIEWER_PASSWORD, _build_harness, login


async def test_anonymous_and_viewer_cannot_read_logs(tmp_path, redis_url):
    harness = await _build_harness(tmp_path, redis_url, "logstest1")
    try:
        async with harness.client() as anon:
            assert (await anon.get("/api/logs")).status_code == 401

        async with harness.client() as viewer:
            await login(viewer, "viewer1", VIEWER_PASSWORD)
            assert (await viewer.get("/api/logs")).status_code == 403
    finally:
        await harness.config_manager.stop()


async def test_admin_sees_logged_messages(tmp_path, redis_url):
    """The harness builds its own LogBuffer rather than going through
    configure_logging() (which would attach to the process-wide root logger
    and leak across tests), so this attaches and detaches it itself,
    scoped to this one test."""
    harness = await _build_harness(tmp_path, redis_url, "logstest2")
    root = logging.getLogger()
    root.addHandler(harness.app.state.log_buffer)
    try:
        logging.getLogger("caelum.logstest").warning("distinctive marker %s", "xyz123")

        async with harness.client() as client:
            await login(client)
            resp = await client.get("/api/logs")
            assert resp.status_code == 200
            entries = resp.json()
            assert any("distinctive marker xyz123" in e["message"] for e in entries)
            marker = next(e for e in entries if "distinctive marker xyz123" in e["message"])
            assert marker["level"] == "WARNING"
            assert marker["logger"] == "caelum.logstest"
            assert "timestamp" in marker
    finally:
        root.removeHandler(harness.app.state.log_buffer)
        await harness.config_manager.stop()
