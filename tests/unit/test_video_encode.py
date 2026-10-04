from __future__ import annotations

from unittest.mock import patch

import numpy as np
import pytest

from caelum.derivatives.video_encode import encode_timelapse, ffmpeg_available


def _frames(n: int = 3, width: int = 32, height: int = 24) -> list[np.ndarray]:
    return [np.full((height, width, 3), fill, dtype=np.uint8) for fill in range(n)]


def test_ffmpeg_available_reflects_shutil_which():
    with patch("caelum.derivatives.video_encode.shutil.which", return_value=None):
        assert ffmpeg_available() is False
    with patch("caelum.derivatives.video_encode.shutil.which", return_value="/usr/bin/ffmpeg"):
        assert ffmpeg_available() is True


def test_encode_timelapse_returns_none_when_ffmpeg_missing(tmp_path):
    with patch("caelum.derivatives.video_encode.shutil.which", return_value=None):
        result = encode_timelapse(_frames(), fps=24, out_path=tmp_path / "out.mp4", tmp_root=tmp_path / ".tmp")
    assert result is None


def test_encode_timelapse_returns_none_for_empty_frame_list(tmp_path):
    result = encode_timelapse([], fps=24, out_path=tmp_path / "out.mp4", tmp_root=tmp_path / ".tmp")
    assert result is None


@pytest.mark.skipif(not ffmpeg_available(), reason="ffmpeg not installed")
def test_encode_timelapse_produces_a_real_video_file(tmp_path):
    out_path = tmp_path / "out.mp4"
    result = encode_timelapse(_frames(5), fps=10, out_path=out_path, tmp_root=tmp_path / ".tmp")

    assert result == out_path
    assert out_path.is_file()
    assert out_path.stat().st_size > 0
    # The temp sequence directory must be cleaned up afterward.
    assert list((tmp_path / ".tmp").iterdir()) == []


@pytest.mark.skipif(not ffmpeg_available(), reason="ffmpeg not installed")
def test_encode_timelapse_returns_none_on_bad_fps(tmp_path):
    # fps=0 is invalid for ffmpeg's -framerate; must fail cleanly, not raise.
    out_path = tmp_path / "out.mp4"
    result = encode_timelapse(_frames(), fps=0, out_path=out_path, tmp_root=tmp_path / ".tmp")
    assert result is None
