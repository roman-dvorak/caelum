"""Wraps a system `ffmpeg` binary via `subprocess` — no `cv2.VideoWriter`
(its H.264/mp4 support depends on how the specific opencv-python-headless
wheel was built, unverified here) and no `ffmpeg-python` dependency (a thin
subprocess wrapper is enough for one command, one fewer package to track).

Frames are written as a numbered JPEG sequence to a temp directory first,
not piped via stdin: a temp-dir approach is trivially inspectable/debuggable
(the exact input sequence ffmpeg saw is left on disk if something goes
wrong) and avoids juggling a subprocess's stdin pipe alongside per-frame
encode/backpressure — a reasonable tradeoff against the extra disk churn,
which is bounded and cleaned up immediately after.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

import cv2
import numpy as np

logger = logging.getLogger(__name__)

_ENCODE_TIMEOUT_S = 600


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def encode_timelapse(frames: list[np.ndarray], fps: int, out_path: Path, tmp_root: Path) -> Path | None:
    """`frames`: BGR uint8 arrays, in chronological order. `tmp_root` is the
    parent directory for the temporary JPEG-sequence directory — pass a
    location on the same disk as `out_path` (e.g. `data_dir/timelapses/.tmp`),
    not the OS default temp dir, which may be RAM-backed (tmpfs) on a
    memory-constrained device and a full night's frame sequence can run into
    gigabytes.

    Returns `out_path` on success, `None` on any failure (missing binary,
    subprocess error, timeout) — logs, never raises. Callers must treat a
    `None` return as "skip this variant," not a fatal error.
    """
    if not ffmpeg_available():
        logger.warning("ffmpeg not found on PATH — skipping timelapse encode for %s", out_path)
        return None
    if not frames:
        return None

    tmp_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="seq_", dir=tmp_root) as tmp:
        tmp_dir = Path(tmp)
        for i, frame in enumerate(frames):
            cv2.imwrite(str(tmp_dir / f"seq_{i:06d}.jpg"), frame, [cv2.IMWRITE_JPEG_QUALITY, 90])

        out_path.parent.mkdir(parents=True, exist_ok=True)
        cmd = [
            "ffmpeg",
            "-y",
            "-framerate",
            str(fps),
            "-i",
            str(tmp_dir / "seq_%06d.jpg"),
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(out_path),
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=_ENCODE_TIMEOUT_S, check=False)
        except (OSError, subprocess.TimeoutExpired):
            logger.exception("ffmpeg invocation failed for %s", out_path)
            return None

        if result.returncode != 0:
            logger.error("ffmpeg exited %d for %s: %s", result.returncode, out_path, result.stderr[-2000:])
            return None
        return out_path
