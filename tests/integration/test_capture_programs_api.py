"""The capture-programs API end to end, with a running (mock) worker."""

from __future__ import annotations

import asyncio

from caelum.cameras.mock_backend import MockCameraBackend
from caelum.capture.worker import CaptureWorker
from caelum.capture_runtime.store import ProgramStore
from caelum.control.exposure import ExposureController
from caelum.control.skystate import SkyStateCalculator
from caelum.control.storage_policy import StoragePolicy
from caelum.processing.inline import InlineFrameSink
from tests.integration.test_api_endpoints import VIEWER_PASSWORD, _build_harness, login

PAIR = '''PROGRAM = {"description": "two exposures", "kind": "hdr"}

async def capture(ctx):
    a = await ctx.capture(exposure_us=1000)
    b = await ctx.capture(exposure_us=4000)
    ctx.log.info("pair done")
    return ctx.capture_set([a, b], kind="hdr", representative=b)
'''


async def _harness(tmp_path, redis_url, prefix):
    harness = await _build_harness(tmp_path, redis_url, prefix)
    store = ProgramStore(tmp_path / "programs")
    worker = CaptureWorker(
        camera_factory=lambda _cfg: MockCameraBackend(),
        config_manager=harness.config_manager,
        skystate_calculator=SkyStateCalculator(lat=50.0755, lon=14.4378, elevation_m=200.0),
        exposure_controller=ExposureController(),
        storage_policy=StoragePolicy(),
        frame_sink=InlineFrameSink(harness.frame_store, __import__("caelum.events").events.EventBus()),
        program_store=store,
    )
    harness.app.state.capture_worker = worker
    harness.app.state.program_store = store
    harness.worker = worker
    return harness, store


async def _until(predicate, timeout=20.0):
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.05)
    return predicate()


async def test_access_is_admin_only(tmp_path, redis_url):
    harness, _ = await _harness(tmp_path, redis_url, "progapi1")
    try:
        async with harness.client() as client:
            assert (await client.get("/api/capture-programs")).status_code == 401
            await login(client, "viewer1", VIEWER_PASSWORD)
            assert (await client.get("/api/capture-programs")).status_code == 403
            assert (await client.put("/api/capture-programs/x.py", json={"source": PAIR})).status_code == 403
    finally:
        await harness.config_manager.stop()


async def test_save_check_activate_test_and_delete(tmp_path, redis_url):
    harness, store = await _harness(tmp_path, redis_url, "progapi2")
    harness.worker.start()
    try:
        async with harness.client() as client:
            await login(client)
            listing = (await client.get("/api/capture-programs")).json()
            assert listing["active"] == {"name": "default.py", "sha256": None}
            assert any(p["name"] == "default.py" and p["origin"] == "builtin" for p in listing["programs"])

            assert (await client.put("/api/capture-programs/default.py", json={"source": PAIR})).status_code == 400
            saved = (await client.put("/api/capture-programs/pair.py", json={"source": PAIR})).json()
            assert (await client.get("/api/capture-programs/pair.py")).json()["source"] == PAIR

            # Saving is not deploying.
            await asyncio.sleep(0.2)
            assert harness.worker.program_status["name"] == "default.py"

            bad = (await client.post("/api/capture-programs/check",
                                     json={"source": "async def capture(ctx):\n    1/0\n"})).json()
            assert bad["ok"] is False and bad["issues"][-1]["line"] == 2

            # A test run on the camera, outside production.
            run = (await client.post("/api/capture-programs/pair.py/test")).json()
            run_url = f"/api/capture-programs/test-runs/{run['run_id']}"
            assert await _until(lambda: store.directory.exists())

            async def report():
                return (await client.get(run_url)).json()

            for _ in range(200):
                body = await report()
                if body["status"] in ("done", "error"):
                    break
                await asyncio.sleep(0.05)
            assert body["status"] == "done", body
            assert [f["exposure_us"] for f in body["frames"]] == [1000, 4000]
            assert body["returned"]["kind"] == "hdr" and body["returned"]["representative"] == 1
            assert any("pair done" in line for line in body["log"])
            image = await client.get(f"{run_url}/{body['frames'][0]['file']}")
            assert image.status_code == 200 and image.content[:4] == b"RIFF"
            assert (await client.get(f"{run_url}/report.json")).status_code == 404
            assert body["frames"][1]["file"].startswith("thumbnails/") and body["frames"][1]["representative"]
            assert any("_set/" in f for f in body["files"])
            # The mock camera has no raw stream: no DNG.
            assert body["dng"] is None
            assert (await client.get(f"{run_url}/../../../etc/passwd")).status_code in (400, 404)

            # Activate the checked version; a stale sha is refused.
            assert (await client.post("/api/capture-programs/pair.py/activate",
                                      json={"sha256": "0" * 64})).status_code == 409
            activated = await client.post("/api/capture-programs/pair.py/activate",
                                          json={"sha256": saved["sha256"]})
            assert activated.status_code == 200, activated.text
            assert harness.config_manager.current.capture.active_sha256 == saved["sha256"]
            assert await _until(lambda: harness.worker.program_status["name"] == "pair.py")
            status = (await client.get("/api/status")).json()["capture_program"]
            assert status["sha256"] == saved["sha256"]

            # Editing the file doesn't change what runs.
            await client.put("/api/capture-programs/pair.py", json={"source": PAIR + "\n# edited\n"})
            await asyncio.sleep(0.2)
            assert harness.worker.program_status["sha256"] == saved["sha256"]

            assert (await client.delete("/api/capture-programs/pair.py")).status_code == 409
            assert (await client.post("/api/capture-programs/default.py/activate", json={})).status_code == 200
            assert await _until(lambda: harness.worker.program_status["name"] == "default.py")
            assert (await client.delete("/api/capture-programs/pair.py")).status_code == 200

            await harness.config_manager.update({"capture": {"editing_enabled": False}})
            assert (await client.put("/api/capture-programs/pair.py", json={"source": PAIR})).status_code == 403
    finally:
        harness.worker.request_stop()
        harness.worker.join(timeout=5)
        await harness.config_manager.stop()


async def test_upload_and_failing_activation(tmp_path, redis_url):
    harness, _ = await _harness(tmp_path, redis_url, "progapi3")
    try:
        async with harness.client() as client:
            await login(client)
            files = {"file": ("Broken.py", b"async def capture(ctx):\n    raise RuntimeError('x')\n", "text/x-python")}
            uploaded = await client.post("/api/capture-programs/upload", files=files)
            assert uploaded.status_code == 200 and uploaded.json()["name"] == "broken.py"
            refused = await client.post("/api/capture-programs/broken.py/activate", json={})
            assert refused.status_code == 422
            assert harness.config_manager.current.capture.active_program == "default.py"
    finally:
        await harness.config_manager.stop()
