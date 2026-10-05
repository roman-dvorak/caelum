"""Multi-frame DNG: every frame decodes bit-identically, IFD0 is the
primary for software that knows nothing about sets (LibRaw via rawpy)."""

from __future__ import annotations

import io
from datetime import timedelta

import numpy as np
import pytest

from caelum.storage import dng_reader
from tests.factories import make_raw_frame
from tests.tiff_tags import read_ifd0

pytest.importorskip("pidng")
rawpy = pytest.importorskip("rawpy")

from caelum.storage.dng_multi import MultiFrame, build_multi_dng  # noqa: E402
from caelum.storage.dng_writer import prepare_camera  # noqa: E402


def _frames(count=3):
    from pidng.core import PICAM2DNG

    rng = np.random.default_rng(7)
    frames, truth = [], []
    for i in range(count):
        base = make_raw_frame(exposure_us=1000 * 10**i)
        raw = rng.integers(0, 256, base.raw_bayer.shape, dtype=np.uint8)
        camera = prepare_camera(base.raw_stream_config, base.camera_metadata, captured_at=base.captured_at,
                                exposure_us=base.exposure_us, analogue_gain=base.analogue_gain)
        truth.append(PICAM2DNG(camera).__unpack_pixels__(raw))
        frames.append(MultiFrame(raw=raw, raw_config=base.raw_stream_config, camera_metadata=base.camera_metadata,
                                 captured_at=base.captured_at + timedelta(seconds=i), exposure_us=base.exposure_us,
                                 analogue_gain=base.analogue_gain, xmp={"exposure_us": base.exposure_us}))
    return frames, truth


def _decode(data: bytes) -> np.ndarray:
    with rawpy.imread(io.BytesIO(data)) as raw:
        return np.array(raw.raw_image_visible)


@pytest.mark.parametrize("compress", [True, False])
def test_every_frame_round_trips_and_ifd0_is_the_primary(compress):
    frames, truth = _frames()
    data = build_multi_dng(frames, primary=1, xmp_fields={"capture_set_kind": "hdr"}, compress=compress)
    # Plain LibRaw sees the primary.
    assert np.array_equal(_decode(data), truth[1])
    # Each frame on its own, in file order: primary, then the rest in set order.
    for position, index in enumerate([1, 0, 2]):
        assert np.array_equal(_decode(dng_reader.standalone_frame(data, position)), truth[index])


def test_xmp_lists_frames_in_set_order():
    frames, _ = _frames()
    data = build_multi_dng(frames, primary=2, xmp_fields={"capture_set_kind": "hdr"})
    xmp = read_ifd0(data)[700].decode()
    assert 'caelum:capture_set_kind="hdr"' in xmp
    items = xmp.split("<rdf:li>")[1:]
    assert [f'caelum:index="{i}"' in item for i, item in enumerate(items)] == [True, True, True]
    assert 'caelum:ifd="SubIFD0"' in items[0] and 'caelum:ifd="IFD0"' in items[2]
    assert 'caelum:exposure_us="100000"' in items[2]


def test_ifd0_keeps_the_single_frame_profile():
    frames, _ = _frames()
    tags = read_ifd0(build_multi_dng(frames, primary=0))
    for tag in (50706, 50721, 50728, 271, 272, 33434):  # DNGVersion, ColorMatrix1, AsShotNeutral, Make, Model, Exp
        assert tag in tags
    assert 330 in tags  # SubIFDs


def test_bad_primary():
    frames, _ = _frames(2)
    with pytest.raises(ValueError):
        build_multi_dng(frames, primary=5)
