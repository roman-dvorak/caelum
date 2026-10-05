"""The per-frame processing steps, as plain functions shared by both sinks
(`client.py`'s worker process and `inline.py`)."""

from __future__ import annotations

import time
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np

from caelum.capture import brightness as brightness_module
from caelum.capture import stats as stats_module
from caelum.capture import thumbnail as thumbnail_module
from caelum.capture.calibration import DarkLibrary
from caelum.capture.metadata import FrameMetadata, SkyStateModel, default_overlay_elements
from caelum.capture.stats import FrameStats
from caelum.config.schema import adu_to_ev
from caelum.storage import dng_writer, paths

from .jobs import FrameInfo


class Timer:
    def __init__(self) -> None:
        self.timings_ms: dict[str, float] = {}
        self._t = time.perf_counter()

    def lap(self, name: str) -> None:
        now = time.perf_counter()
        self.timings_ms[name] = round((now - self._t) * 1000.0, 1)
        self._t = now


def analyze(
    image: np.ndarray, info: FrameInfo, dark_library: DarkLibrary, timer: Timer | None = None
) -> tuple[np.ndarray, FrameStats, bytes, bytes]:
    """Calibrate, measure, encode. Returns (calibrated RGB, stats, live
    JPEG, thumbnail WebP)."""
    timer = timer or Timer()
    calibrated = dark_library.apply_dark(image, info.exposure_us, info.analogue_gain)
    timer.lap("dark")
    stats = stats_module.extract(calibrated, saturation_value=info.settings.saturation_adu)
    circle = brightness_module.measure(calibrated, info.settings.brightness_roi_diameter_frac)
    stats = replace(stats, median=circle.median)
    timer.lap("stats")
    small = thumbnail_module.resize(calibrated, info.settings.thumbnail_max_dim)
    live_jpeg = thumbnail_module.encode_jpeg(small, info.settings.jpeg_quality)
    webp = thumbnail_module.encode_webp(small, info.settings.webp_quality)
    timer.lap("encode")
    return calibrated, stats, live_jpeg, webp


def build_metadata(info: FrameInfo, stats: FrameStats) -> FrameMetadata:
    metadata = FrameMetadata(
        captured_at=info.captured_at,
        exposure_us=info.exposure_us,
        analogue_gain=info.analogue_gain,
        sky_state=SkyStateModel.model_validate(info.sky_state),
        focus_score=stats.focus_score,
        exposure_control=info.exposure_control,
    )
    return metadata.model_copy(update={"overlay_elements": default_overlay_elements(metadata)})


def persist_thumbnail(data_dir: Path, metadata: FrameMetadata, webp: bytes) -> Path:
    thumb_path = paths.thumbnail_path(data_dir, metadata.captured_at)
    thumb_path.parent.mkdir(parents=True, exist_ok=True)
    thumb_path.write_bytes(webp)
    paths.sidecar_path(thumb_path).write_text(metadata.model_dump_json(indent=2))
    return thumb_path


def _xmp_fields(info: FrameInfo, metadata: FrameMetadata, stats: FrameStats) -> dict[str, Any]:
    sky = metadata.sky_state
    meta = info.camera_metadata
    colour_gains = meta.get("ColourGains")
    location = info.settings.location
    return {
        "captured_at": metadata.captured_at.isoformat(),
        "sky_period": sky.period,
        "sun_altitude_deg": round(sky.sun_altitude_deg, 3),
        "sun_azimuth_deg": round(sky.sun_azimuth_deg, 3),
        "moon_altitude_deg": round(sky.moon_altitude_deg, 3),
        "moon_azimuth_deg": round(sky.moon_azimuth_deg, 3),
        "moon_illumination": round(sky.moon_illumination, 4),
        "latitude_deg": location.get("lat"),
        "longitude_deg": location.get("lon"),
        "elevation_m": location.get("elevation_m"),
        "exposure_us": info.exposure_us,
        "analogue_gain": round(info.analogue_gain, 4),
        "digital_gain": meta.get("DigitalGain"),
        "colour_gains": ",".join(f"{g:.4f}" for g in colour_gains) if colour_gains else None,
        "sensor_temperature_c": meta.get("SensorTemperature"),
        "sensor_timestamp_ns": info.sensor_timestamp_ns,
        "brightness_median": round(info.brightness_median, 2) if info.brightness_median is not None else None,
        "brightness_median_ev": round(adu_to_ev(info.brightness_median), 3) if info.brightness_median else None,
        "target_ev": info.settings.target_ev,
        "focus_score": round(stats.focus_score, 3),
    }


def persist_raw(
    data_dir: Path, info: FrameInfo, metadata: FrameMetadata, stats: FrameStats, raw: np.ndarray
) -> Path:
    assert info.raw_config is not None, "persist_raw() needs the raw stream layout"
    sky = metadata.sky_state
    data = dng_writer.build_dng(
        raw,
        info.raw_config,
        info.camera_metadata,
        captured_at=metadata.captured_at,
        exposure_us=info.exposure_us,
        analogue_gain=info.analogue_gain,
        camera_model=info.camera_model,
        software=info.settings.software,
        description=(
            f"caelum allsky {sky.period}, exp {info.exposure_us / 1e6:.6g} s, gain {info.analogue_gain:.2f}, "
            f"sun {sky.sun_altitude_deg:.1f} deg"
        ),
        xmp_fields=_xmp_fields(info, metadata, stats),
        compress=info.settings.dng_compress,
    )
    raw_path = paths.raw_path(data_dir, metadata.captured_at)
    dng_writer.write(raw_path, data)
    paths.sidecar_path(raw_path).write_text(metadata.model_dump_json(indent=2))
    return raw_path
