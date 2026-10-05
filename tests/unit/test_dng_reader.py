from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pytest

from tests.factories import RAW_HEIGHT, RAW_WIDTH, make_raw_bayer, make_raw_config

pytest.importorskip("pidng")

from caelum.storage import dng_reader, dng_writer  # noqa: E402


def _build(colour_gains=(1.8, 1.6), seed: int = 0) -> bytes:
    meta = {"ExposureTime": 1_000_000, "AnalogueGain": 2.0, "ColourGains": list(colour_gains)}
    return dng_writer.build_dng(
        make_raw_bayer(seed),
        make_raw_config(),
        meta,
        captured_at=datetime(2026, 10, 3, 1, 2, 3, tzinfo=UTC),
        exposure_us=1_000_000,
        analogue_gain=2.0,
        xmp_fields={"colour_gains": ",".join(f"{g:.4f}" for g in colour_gains)},
    )


def _csi2p_unpacked(packed: np.ndarray) -> np.ndarray:
    """What the sensor actually measured — the CSI-2 packed buffer the
    camera hands over, unpacked the way picamera2/PiDNG define it."""
    data = packed[:, : RAW_WIDTH * 3 // 2].astype(np.uint16)
    out = np.empty((RAW_HEIGHT, RAW_WIDTH), dtype=np.uint16)
    out[:, 0::2] = (data[:, 0::3] << 4) | (data[:, 2::3] & 0x0F)
    out[:, 1::2] = (data[:, 1::3] << 4) | (data[:, 2::3] >> 4)
    return out


def test_bayer_round_trips_the_sensor_data():
    data = _build()
    info = dng_reader.parse(data)
    assert (info.width, info.height, info.bits_per_sample) == (RAW_WIDTH, RAW_HEIGHT, 12)
    np.testing.assert_array_equal(dng_reader.bayer(data, info), _csi2p_unpacked(make_raw_bayer()))


def test_white_balance_is_read_as_gains():
    info = dng_reader.parse(_build(colour_gains=(1.8, 1.6)))
    assert info.cfa == (0, 1, 1, 2)  # RGGB
    assert info.as_shot_neutral == pytest.approx((1 / 1.8, 1.0, 1 / 1.6), abs=1e-4)
    assert info.gains == pytest.approx((1.8, 1.6), abs=1e-3)
    assert info.captured_gains == pytest.approx((1.8, 1.6))


def test_set_as_shot_neutral_changes_only_that_tag(tmp_path):
    original = _build()
    path = tmp_path / "frame.dng"
    path.write_bytes(original)

    info = dng_reader.set_as_shot_neutral(path, 1.25, 2.5)

    assert info.gains == pytest.approx((1.25, 2.5), abs=1e-4)
    assert info.captured_gains == pytest.approx((1.8, 1.6))  # the as-captured record stays
    patched = path.read_bytes()
    assert len(patched) == len(original)
    changed = [i for i, (a, b) in enumerate(zip(original, patched, strict=True)) if a != b]
    assert changed and max(changed) - min(changed) < 24  # three rationals, nothing else
    np.testing.assert_array_equal(dng_reader.bayer(patched, info), dng_reader.bayer(original, info))
    assert [p.name for p in tmp_path.iterdir()] == ["frame.dng"]


def test_linear_rgb_is_one_pixel_per_cfa_cell_scaled_to_white():
    data = _build()
    info = dng_reader.parse(data)
    rgb = dng_reader.linear_rgb(data, info, max_dim=1024)
    assert rgb.shape == (RAW_HEIGHT // 2, RAW_WIDTH // 2, 3)
    assert rgb.min() >= 0.0 and rgb.max() <= 1.0

    cfa = _csi2p_unpacked(make_raw_bayer()).astype(np.float64)
    black, white = info.black_levels[0], info.white_level
    expected_red = np.clip((cfa[0, 0] - black) / (white - black), 0, 1)
    expected_green = np.clip(((cfa[0, 1] - black) + (cfa[1, 0] - black)) / 2 / (white - black), 0, 1)
    assert rgb[0, 0, 0] == pytest.approx(expected_red, abs=1e-5)
    assert rgb[0, 0, 1] == pytest.approx(expected_green, abs=1e-5)


def test_linear_rgb_downscales_to_fit():
    data = _build()
    rgb = dng_reader.linear_rgb(data, dng_reader.parse(data), max_dim=8)
    assert max(rgb.shape[:2]) <= 8


def test_render_matrix_does_not_depend_on_the_white_balance():
    # With an identity colour correction matrix, PiDNG's profile renders
    # through an identity matrix — whatever the as-shot gains were.
    for gains in ((1.0, 1.0), (1.8, 1.6), (0.7, 3.0)):
        matrix = dng_reader.render_matrix(dng_reader.parse(_build(colour_gains=gains)))
        np.testing.assert_allclose(matrix, np.eye(3), atol=1e-3)


def test_not_a_dng_is_rejected():
    with pytest.raises(dng_reader.DngFormatError):
        dng_reader.parse(b"\x89PNG\r\n\x1a\n" + b"0" * 64)
