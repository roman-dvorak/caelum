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


# ---- processing-side builders ---------------------------------------------

# A 12-bit CSI-2 packed Bayer buffer (3 bytes per 2 pixels) for a tiny
# sensor — the layout picamera2 hands back for e.g. SRGGB12_CSI2P.
RAW_WIDTH, RAW_HEIGHT = 64, 48
RAW_STRIDE = 96


def make_raw_config(width: int = RAW_WIDTH, height: int = RAW_HEIGHT, stride: int = RAW_STRIDE) -> dict:
    return {"format": "SRGGB12_CSI2P", "size": [width, height], "stride": stride}


def make_raw_bayer(seed: int = 0) -> np.ndarray:
    return np.random.default_rng(seed).integers(0, 256, size=(RAW_HEIGHT, RAW_STRIDE), dtype=np.uint8)


def make_raw_frame(
    captured_at: datetime | None = None,
    image: np.ndarray | None = None,
    with_raw: bool = True,
    exposure_us: int = 10_000_000,
    analogue_gain: float = 2.0,
):
    from caelum.cameras.base import RawFrame

    return RawFrame(
        image=image if image is not None else make_image(fill=60),
        exposure_us=exposure_us,
        analogue_gain=analogue_gain,
        sensor_timestamp_ns=123_456_789,
        captured_at=captured_at or datetime.now(UTC),
        raw_bayer=make_raw_bayer() if with_raw else None,
        raw_stream_config=make_raw_config() if with_raw else None,
        camera_metadata={
            "ExposureTime": exposure_us,
            "AnalogueGain": analogue_gain,
            "DigitalGain": 1.0,
            "ColourGains": [1.8, 1.6],
            "SensorBlackLevels": [4096, 4096, 4096, 4096],
            "ColourCorrectionMatrix": [1.5, -0.3, -0.2, -0.4, 1.6, -0.2, 0.0, -0.6, 1.6],
            "SensorTemperature": 31.0,
        }
        if with_raw
        else {},
        camera_model="imx477" if with_raw else "",
    )


def make_submission(raw_frame=None, save_raw: bool = False, period: str = "night"):
    from caelum.config.schema import AppConfig
    from caelum.processing.jobs import FrameSubmission, ProcessingSettings

    return FrameSubmission(
        raw=raw_frame if raw_frame is not None else make_raw_frame(),
        sky_state=SkyStateModel(
            sun_altitude_deg=-30.0,
            sun_azimuth_deg=180.0,
            moon_altitude_deg=10.0,
            moon_azimuth_deg=90.0,
            moon_illumination=0.5,
            period=period,
        ),
        save_raw=save_raw,
        settings=ProcessingSettings.from_config(AppConfig(), period),
    )
