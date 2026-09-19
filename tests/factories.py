"""Shared test helpers for building synthetic ProcessedFrame instances."""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np

from caelum.capture.frame_store import ProcessedFrame
from caelum.capture.metadata import FrameMetadata, SkyStateModel
from caelum.capture.stats import FrameStats


def make_image(width: int = 64, height: int = 48, fill: int = 10) -> np.ndarray:
    return np.full((height, width, 3), fill, dtype=np.uint8)


def make_processed_frame(
    captured_at: datetime | None = None,
    image: np.ndarray | None = None,
    period: str = "night",
) -> ProcessedFrame:
    captured_at = captured_at or datetime.now(UTC)
    image = image if image is not None else make_image()
    metadata = FrameMetadata(
        captured_at=captured_at,
        exposure_us=1_000_000,
        analogue_gain=1.0,
        sky_state=SkyStateModel(
            sun_altitude_deg=-30.0,
            sun_azimuth_deg=180.0,
            moon_altitude_deg=10.0,
            moon_azimuth_deg=90.0,
            moon_illumination=0.5,
            period=period,
        ),
        focus_score=0.0,
    )
    stats = FrameStats(mean=10.0, p95=10.0, p99=10.0, saturated_fraction=0.0, focus_score=0.0)
    return ProcessedFrame(image=image, thumbnail_jpeg=b"", stats=stats, metadata=metadata, save_raw=False)
