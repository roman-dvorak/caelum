"""Test runs store their result exactly as production does: thumbnails,
sidecars and the DNG (multi-frame for a set), in the run's directory."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from caelum.capture.worker import _store_test_set_into
from caelum.capture_runtime import load_program, testrun
from caelum.config.schema import AppConfig
from caelum.control.exposure import ExposureController, ExposureTarget
from caelum.control.skystate import SkyState
from caelum.control.storage_policy import StoragePolicy
from caelum.storage import dng_reader
from tests.factories import make_raw_frame
from tests.tiff_tags import read_ifd0

pytest.importorskip("pidng")

# Daytime: production wouldn't keep raw now, a test run still does.
SKY = SkyState(timestamp=datetime.now(UTC), sun_altitude_deg=30.0, sun_azimuth_deg=0.0, moon_altitude_deg=-10.0,
               moon_azimuth_deg=0.0, moon_illumination=0.0, period="day")


class _RawDriver:
    def __init__(self, with_raw=True):
        self.n = 0
        self.with_raw = with_raw

    def capture_for_program(self, req, align_to_slot):
        self.n += 1
        raw = make_raw_frame(captured_at=datetime(2026, 10, 5, 7, 0, 0, tzinfo=UTC) + timedelta(seconds=self.n),
                             exposure_us=req.exposure_us, with_raw=self.with_raw)
        return raw, SKY

    def stop_requested(self):
        return False


def _run(tmp_path, source, driver):
    program = load_program("t.py", source)
    request = testrun.new_request(tmp_path, program, "admin")
    cfg = AppConfig()

    def store(directory, capture_set):
        provenance = {"capture_program": program.name, "capture_program_sha256": program.sha256}
        _store_test_set_into(directory, cfg, capture_set, provenance, StoragePolicy())

    loop = asyncio.new_event_loop()
    try:
        return request, testrun.execute(
            request, driver=driver, config=cfg, sky=SKY, exposure_controller=ExposureController(),
            commanded=ExposureTarget(10_000, 1.0), capabilities=None, interval_s=60.0, loop=loop, store=store,
        )
    finally:
        loop.close()


def test_single_frame_is_stored_like_production(tmp_path):
    request, report = _run(tmp_path, "async def capture(ctx):\n    return await ctx.capture(exposure_us=5000)\n",
                           _RawDriver())
    assert report["status"] == "done"
    assert report["frames"][0]["file"] == "thumbnails/2026/10/05/20261005-070001.webp"
    assert report["dng"] == "raw/2026/10/05/20261005-070001.dng"
    assert "thumbnails/2026/10/05/20261005-070001.json" in report["files"]
    data = (request.run_dir / report["dng"]).read_bytes()
    assert len(dng_reader.list_raw_ifds(data)) == 1
    assert b'caelum:capture_program="t.py"' in read_ifd0(data)[700]


def test_hdr_set_is_stored_like_production(tmp_path):
    source = (
        "async def capture(ctx):\n"
        "    frames = [await ctx.capture(exposure_us=e) for e in (1000, 4000, 16000)]\n"
        "    return ctx.capture_set(frames, kind='hdr', representative=frames[1])\n"
    )
    request, report = _run(tmp_path, source, _RawDriver())
    # Named after the representative (captured second), members in <stem>_set/.
    assert [f["file"] for f in report["frames"]] == [
        "thumbnails/2026/10/05/20261005-070002_set/20261005-070002_m00.webp",
        "thumbnails/2026/10/05/20261005-070002.webp",
        "thumbnails/2026/10/05/20261005-070002_set/20261005-070002_m02.webp",
    ]
    assert report["dng"] == "raw/2026/10/05/20261005-070002.dng"
    assert not [f for f in report["files"] if f.startswith("raw/") and "_set/" in f]  # one DNG, no member DNGs
    data = (request.run_dir / report["dng"]).read_bytes()
    assert len(dng_reader.list_raw_ifds(data)) == 3
    xmp = read_ifd0(data)[700]
    assert b'caelum:capture_set_kind="hdr"' in xmp and xmp.count(b"<rdf:li>") == 3
    assert read_ifd0(data)[33434] == [(4000, 1_000_000)]  # IFD0 = the representative


def test_no_raw_stream_means_no_dng(tmp_path):
    request, report = _run(tmp_path, "async def capture(ctx):\n    return await ctx.capture(exposure_us=5000)\n",
                           _RawDriver(with_raw=False))
    assert report["dng"] is None
    assert report["frames"][0]["file"].endswith(".webp")
