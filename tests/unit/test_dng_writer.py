from __future__ import annotations

from datetime import UTC, datetime

import pytest

from tests.factories import RAW_HEIGHT, RAW_WIDTH, make_raw_bayer, make_raw_config
from tests.tiff_tags import read_ifd0

pytest.importorskip("pidng")

from caelum.storage import dng_writer  # noqa: E402

TAG_WIDTH, TAG_HEIGHT, TAG_BITS = 256, 257, 258
TAG_DESCRIPTION, TAG_MAKE, TAG_MODEL, TAG_SOFTWARE, TAG_DATETIME = 270, 271, 272, 305, 306
TAG_XMP = 700
TAG_CFA_PATTERN = 33422
TAG_EXPOSURE_TIME = 33434
TAG_ISO = 34855
TAG_DATETIME_ORIGINAL = 36867
TAG_UNIQUE_CAMERA_MODEL = 50708


def _build(**overrides) -> bytes:
    kwargs = dict(
        captured_at=datetime(2026, 10, 3, 1, 2, 3, 456000, tzinfo=UTC),
        exposure_us=10_000_000,
        analogue_gain=2.0,
        camera_model="imx477",
        software="caelum 1.2.3",
        description="night, exp 10 s",
        xmp_fields={"sky_period": "night", "sun_altitude_deg": -30.5, "skipped": None},
    )
    kwargs.update(overrides)
    meta = {"ExposureTime": kwargs["exposure_us"], "AnalogueGain": kwargs["analogue_gain"], "ColourGains": [1.8, 1.6]}
    return dng_writer.build_dng(make_raw_bayer(), make_raw_config(), meta, **kwargs)


def test_dng_has_the_sensor_geometry_and_cfa_layout():
    tags = read_ifd0(_build())
    assert tags[TAG_WIDTH] == [RAW_WIDTH]
    assert tags[TAG_HEIGHT] == [RAW_HEIGHT]
    assert tags[TAG_BITS] == [12]
    assert list(tags[TAG_CFA_PATTERN]) == [0, 1, 1, 2]  # RGGB


def test_long_exposures_are_written_as_a_valid_rational():
    tags = read_ifd0(_build(exposure_us=10_000_000))
    assert tags[TAG_EXPOSURE_TIME] == [(10_000_000, 1_000_000)]  # 10 s, not PiDNG's 1/0
    assert tags[TAG_ISO] == [200]


def test_capture_metadata_is_written():
    tags = read_ifd0(_build())
    assert tags[TAG_DATETIME] == "2026:10:03 01:02:03"
    assert tags[TAG_DATETIME_ORIGINAL] == "2026:10:03 01:02:03"
    assert tags[TAG_MAKE] == "Raspberry Pi"
    assert tags[TAG_MODEL] == "imx477"
    assert tags[TAG_UNIQUE_CAMERA_MODEL] == "Raspberry Pi imx477"
    assert tags[TAG_SOFTWARE] == "caelum 1.2.3"
    assert tags[TAG_DESCRIPTION] == "night, exp 10 s"


def test_xmp_carries_the_caelum_fields():
    xmp = read_ifd0(_build())[TAG_XMP].decode("utf-8")
    assert 'caelum:sky_period="night"' in xmp
    assert 'caelum:sun_altitude_deg="-30.5"' in xmp
    assert "skipped" not in xmp  # None values are left out


def test_non_ascii_text_does_not_break_the_writer():
    tags = read_ifd0(_build(description="Ondřejov — noc"))
    assert tags[TAG_DESCRIPTION].startswith("Ond")


def test_write_is_atomic_and_leaves_no_temp_file(tmp_path):
    path = tmp_path / "raw" / "x.dng"
    dng_writer.write(path, _build())
    assert path.read_bytes()[:4] == b"II*\x00"
    assert [p.name for p in path.parent.iterdir()] == ["x.dng"]


def test_compressed_dng_is_smaller_and_marked_lossless_jpeg():
    import numpy as np

    rng = np.random.default_rng(0)
    # A smooth, realistic-ish sky: compressible, unlike pure noise.
    yy, xx = np.mgrid[0:RAW_HEIGHT, 0:RAW_WIDTH]
    pixels = (300 + 2 * yy + xx + rng.integers(0, 8, size=yy.shape)).astype(np.uint16)
    meta = {"ExposureTime": 1_000_000, "AnalogueGain": 1.0}
    kwargs = dict(captured_at=datetime(2026, 10, 3, tzinfo=UTC), exposure_us=1_000_000, analogue_gain=1.0)
    cfg = make_raw_config()
    plain = dng_writer.build_dng(pixels, cfg, meta, compress=False, **kwargs)
    packed = dng_writer.build_dng(pixels, cfg, meta, compress=True, **kwargs)
    assert len(packed) < len(plain)
    assert read_ifd0(packed)[259] == [7]  # Compression: JPEG (lossless, LJ92)
