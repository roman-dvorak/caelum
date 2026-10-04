from __future__ import annotations

from datetime import UTC, datetime

import numpy as np

from caelum.derivatives.base import Derivative
from caelum.derivatives.pool import thumbnail_path_for, write_derivative


def test_write_derivative_nests_by_kind_and_writes_a_thumbnail(tmp_path):
    image = np.full((200, 400, 3), 128, dtype=np.uint8)
    derivative = Derivative(kind="meteor_crop", created_at=datetime(2026, 3, 14, 20, 30, tzinfo=UTC), image=image)

    full_path = write_derivative(tmp_path, derivative, worker_id="meteor_detection")

    expected_dir = tmp_path / "derivatives" / "2026" / "03" / "14" / "meteor_crop"
    assert full_path == expected_dir / "20260314-203000_meteor_detection_meteor_crop.jpg"
    assert full_path.is_file()

    thumb_path = thumbnail_path_for(full_path)
    assert thumb_path.is_file()
    assert thumb_path.name == "20260314-203000_meteor_detection_meteor_crop_thumb.jpg"
    # A 320px-max-dim thumbnail of a 400x200 source must be meaningfully
    # smaller than the full file, not just a same-size copy under a new name.
    assert thumb_path.stat().st_size < full_path.stat().st_size
