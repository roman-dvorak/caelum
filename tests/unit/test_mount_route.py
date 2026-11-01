from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from caelum.api.routes import mount
from caelum.derivatives.telescope_position import TelescopePositionWorker


def _client(plugins):
    app = FastAPI()
    app.include_router(mount.router, prefix="/api")
    app.state.plugin_loader = SimpleNamespace(loaded=[SimpleNamespace(plugin=p) for p in plugins])
    return TestClient(app)


def test_disabled_when_plugin_not_loaded():
    assert _client([]).get("/api/mount/state").json()["enabled"] is False


def test_reports_simulated_state():
    worker = TelescopePositionWorker({"source": "simulated", "label": "C14"})
    body = _client([worker]).get("/api/mount/state").json()
    assert body["enabled"] is True and body["label"] == "C14"
    assert body["status"] in ("tracking", "slewing") and body["alt_deg"] is not None
