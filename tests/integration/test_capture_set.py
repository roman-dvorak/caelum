"""Capture sets through the processing sinks: every member gets its
thumbnail + sidecar (and DNG), only the representative is published and
stored under the plain stem; members go to `<stem>_set/`."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from caelum.cameras.base import CaptureRequest
from caelum.capture.brightness import measure
from caelum.capture.frame_store import FrameStore
from caelum.capture.worker import build_submissions
from caelum.capture_runtime import CapturedFrame, CaptureSet
from caelum.config.schema import AppConfig
from caelum.control.skystate import SkyState
from caelum.control.storage_policy import StoragePolicy
from caelum.events import EventBus
from caelum.processing.client import ProcessingClient
from caelum.processing.inline import InlineFrameSink
from caelum.storage import dng_reader, paths
from tests.factories import make_image, make_raw_frame
from tests.integration.test_processing import _Collector, _wait_until
from tests.tiff_tags import read_ifd0

T0 = datetime(2026, 10, 5, 1, 2, 3, tzinfo=UTC)
SKY = SkyState(
    timestamp=T0, sun_altitude_deg=-30.0, sun_azimuth_deg=0.0, moon_altitude_deg=-10.0,
    moon_azimuth_deg=0.0, moon_illumination=0.0, period="night",
)
PROVENANCE = {"capture_program": "hdr.py", "capture_program_sha256": "ab" * 32, "caelum_version": "test"}


def _set(count: int = 3, representative: int = 1, with_raw: bool = True) -> CaptureSet:
    frames = []
    for i in range(count):
        exposure = 1000 * 10**i
        raw = make_raw_frame(captured_at=T0 + timedelta(seconds=i * 0.4), exposure_us=exposure,
                             image=make_image(fill=20 + 40 * i), with_raw=with_raw)
        frames.append(CapturedFrame(raw=raw, brightness=measure(raw.image, 0.8), sky=SKY,
                                    requested=CaptureRequest(exposure_us=exposure), index=i))
    return CaptureSet(frames=frames, kind="hdr", representative=representative, annotations={"ev_step": 3.3})


def _submissions(**kw):
    cfg = AppConfig()
    assert "night" in cfg.storage_policy.raw_periods
    return build_submissions(cfg, _set(**kw), PROVENANCE, StoragePolicy())


def _assert_layout(data_dir):
    thumb = paths.thumbnail_path(data_dir, T0)
    primary = json.loads(paths.sidecar_path(thumb).read_text())
    assert primary["exposure_us"] == 10_000
    assert primary["provenance"]["capture_program"] == "hdr.py"
    cs = primary["capture_set"]
    assert cs["kind"] == "hdr" and cs["count"] == 3 and cs["role"] == "representative" and cs["index"] == 1
    assert [m["file_stem"] for m in cs["members"]] == [
        "20261005-010203_set/20261005-010203_m00", "20261005-010203", "20261005-010203_set/20261005-010203_m02",
    ]
    assert primary["annotations"] == {"set": {"ev_step": 3.3}}
    for index, exposure in ((0, 1000), (2, 100_000)):
        member = paths.member_path(data_dir, "thumbnails", T0, index, ".webp")
        assert member.exists()
        meta = json.loads(paths.sidecar_path(member).read_text())
        assert meta["exposure_us"] == exposure
        assert meta["capture_set"]["role"] == "member" and meta["capture_set"]["index"] == index
        assert paths.capture_time_of(member) == T0
    # The day directory itself lists one capture.
    day = paths.date_dir(data_dir, "thumbnails", T0)
    assert sorted(p.name for p in day.iterdir() if p.is_file()) == ["20261005-010203.json", "20261005-010203.webp"]


def test_inline_sink_stores_set_and_publishes_only_representative(tmp_path):
    pytest.importorskip("pidng")
    bus = EventBus()
    collected = _Collector(bus)
    sink = InlineFrameSink(FrameStore(), bus, tmp_path)
    assert sink.submit_set(_submissions()) is True
    assert len(collected) == 1
    assert collected.frames[0].metadata.exposure_us == 10_000
    _assert_layout(tmp_path)
    dng = paths.raw_path(tmp_path, T0)
    xmp = read_ifd0(dng.read_bytes())[700]
    assert b'caelum:capture_program="hdr.py"' in xmp
    assert b'caelum:capture_set_kind="hdr"' in xmp
    _assert_multi_dng(dng)


def _assert_multi_dng(dng):
    data = dng.read_bytes()
    assert len(dng_reader.list_raw_ifds(data)) == 3  # primary in IFD0, two SubIFDs
    xmp = read_ifd0(data)[700]
    assert xmp.count(b"<rdf:li>") == 3
    assert b'caelum:ifd="IFD0"' in xmp and b'caelum:ifd="SubIFD1"' in xmp
    assert b'caelum:exposure_us="100000"' in xmp
    assert not paths.member_path(dng.parents[4], "raw", T0, 2, ".dng").exists()
    # IFD0 is the representative (10 ms); the others are in set order.
    exposures = [dng_reader.parse(dng_reader.standalone_frame(data, i)) for i in range(3)]
    assert all(info.width == 64 for info in exposures)


def test_process_sink_stores_set_and_publishes_only_representative(tmp_path):
    pytest.importorskip("pidng")
    bus = EventBus()
    collected = _Collector(bus)
    client = ProcessingClient(FrameStore(), bus, tmp_path, slots=3, job_timeout_s=60.0)
    client.start()
    try:
        assert client.submit_set(_submissions()) is True
        assert _wait_until(lambda: client.stats["processed"] == 3)
        assert len(collected) == 1
        assert collected.frames[0].metadata.capture_set["role"] == "representative"
        _assert_layout(tmp_path)
        _assert_multi_dng(paths.raw_path(tmp_path, T0))
    finally:
        client.stop()


def test_set_larger_than_the_slots_is_dropped_whole(tmp_path):
    client = ProcessingClient(FrameStore(), EventBus(), tmp_path, slots=2, job_timeout_s=60.0)
    client.start()
    try:
        assert client.submit_set(_submissions(with_raw=False)) is False
        assert client.stats["dropped"] == 1 and client.stats["submitted"] == 0
    finally:
        client.stop()
