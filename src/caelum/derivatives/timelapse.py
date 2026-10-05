"""Automated day/night timelapse generation.

Triggered by `PeriodTrackingMixin` (derivatives/base.py) when `sky_state.period`
transitions out of "day" or "night" — see that class's docstring for how a
5-value `SkyPeriod` enum still produces exactly 2 triggers/day. Source
frames are enumerated lazily from disk for the closed `[start, end)` window
(never buffered in memory across the whole period), preferring the raw
frame when one was saved for a timestamp and falling back to the thumbnail
otherwise. Encoding is a `subprocess` call to `ffmpeg` (see `video_encode.py`);
overlay burn-in (optional, using whichever template is active *at generation
time*) is `overlay_render.py`.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import cv2
from pydantic import BaseModel, Field

from caelum.capture.metadata import FrameMetadata
from caelum.derivatives.base import Derivative, PeriodTrackingMixin, PeriodWindow
from caelum.derivatives.overlay import OverlayElementDef, OverlaySettings
from caelum.derivatives.overlay_render import rasterize
from caelum.derivatives.video_encode import encode_timelapse
from caelum.plugins.base import Plugin
from caelum.scheduling.decorators import on_period_end
from caelum.storage import paths
from caelum.storage.browse import fits_to_bgr

logger = logging.getLogger(__name__)


class TimelapseSettings(BaseModel):
    generate_clean: bool = True
    generate_with_overlay: bool = False
    fps: int = Field(default=24, ge=1, le=60)
    #: 0 = keep forever. Independent of RetentionConfig.max_age_days — see
    #: storage/retention.py's sweep_timelapses.
    retention_days: int = Field(default=30, ge=0)
    #: Skip encoding a period with fewer resolved frames than this — avoids
    #: producing a near-useless video from a restart-interrupted or
    #: mostly-cloudy/misclassified period.
    min_frames: int = Field(default=10, ge=1)


def _dates_spanned(start_at: datetime, end_at: datetime) -> list[str]:
    """Every UTC calendar date (`YYYY-MM-DD`) the `[start_at, end_at]`
    window touches — a night crosses midnight, so this is at least 2 dates
    in the common case."""
    start_date = start_at.date()
    end_date = end_at.date()
    dates = []
    d = start_date
    while d <= end_date:
        dates.append(d.isoformat())
        d += timedelta(days=1)
    return dates


def _resolve_frame_paths(data_dir: Path, start_at: datetime, end_at: datetime) -> list[Path]:
    """One entry per captured timestamp in `[start_at, end_at)`, raw
    preferred over thumbnail when both exist for the same timestamp — but
    only legacy FITS raws: a DNG holds undebayered sensor data cv2 can't
    decode, so for those the (ISP-processed) thumbnail is used."""
    results: dict[str, Path] = {}
    for day in _dates_spanned(start_at, end_at):
        for subdir in ("thumbnails", "raw"):
            directory = paths.date_dir_for_iso(data_dir, subdir, day)
            if not directory.is_dir():
                continue
            for child in directory.iterdir():
                if not child.is_file() or child.suffix == ".json":
                    continue
                if subdir == "raw" and child.suffix.lower() == ".dng":
                    continue
                when = paths.capture_time_of(child)
                if when is None or not (start_at <= when < end_at):
                    continue
                stem = child.stem
                # thumbnails processed first, so raw (processed second)
                # naturally overwrites the entry for the same timestamp.
                if subdir == "raw" or stem not in results:
                    results[stem] = child
    return [results[stem] for stem in sorted(results)]


def _load_frame_bgr(path: Path):
    """None on any decode failure — a single corrupt/unreadable source file
    should drop out of the sequence, not abort the whole timelapse."""
    try:
        if path.suffix == ".fits":
            return fits_to_bgr(path)
        return cv2.imread(str(path))
    except Exception:
        logger.exception("Failed to decode %s — skipping this frame", path)
        return None


def _load_metadata(image_path: Path) -> FrameMetadata | None:
    sidecar = paths.sidecar_path(image_path)
    if not sidecar.is_file():
        return None
    try:
        return FrameMetadata.model_validate_json(sidecar.read_text())
    except Exception:
        logger.exception("Bad sidecar %s — burning in overlay without per-frame metadata", sidecar)
        return None


class TimelapseWorker(PeriodTrackingMixin, Plugin):
    """Builds a day timelapse when "day" ends and a night timelapse when
    "night" ends, each optionally with the `overlay` plugin's currently
    active template burned in. Disabled by default (see
    `config.schema._default_plugins`) — like `overlay`/`telescope_position`,
    it shouldn't start writing large video files unasked."""

    id = "timelapse"
    config_schema = TimelapseSettings

    def __init__(self, settings: dict[str, Any] | None = None) -> None:
        Plugin.__init__(self, settings or {})
        PeriodTrackingMixin.__init__(self)
        self._cfg = TimelapseSettings.model_validate(self.settings)

    @on_period_end("day")
    def _on_day_end(self, window: PeriodWindow) -> list[Derivative]:
        return self._build(window, kind="day")

    @on_period_end("night")
    def _on_night_end(self, window: PeriodWindow) -> list[Derivative]:
        return self._build(window, kind="night")

    def _build(self, window: PeriodWindow, kind: str) -> list[Derivative]:
        data_dir = self.data_dir
        if data_dir is None:
            logger.warning("Timelapse worker has no data_dir yet — skipping %s timelapse", kind)
            return []

        frame_paths = _resolve_frame_paths(data_dir, window.start_at, window.end_at)
        if len(frame_paths) < self._cfg.min_frames:
            logger.info(
                "Timelapse %s skipped: only %d frame(s) (min %d)", kind, len(frame_paths), self._cfg.min_frames
            )
            return []

        overlay_elements = self._current_overlay_elements()
        derivatives: list[Derivative] = []
        if self._cfg.generate_clean:
            derivative = self._render_and_encode(data_dir, kind, window, frame_paths, overlay_elements=None)
            if derivative is not None:
                derivatives.append(derivative)
        if self._cfg.generate_with_overlay and overlay_elements is not None:
            derivative = self._render_and_encode(
                data_dir, kind, window, frame_paths, overlay_elements=overlay_elements
            )
            if derivative is not None:
                derivatives.append(derivative)
        return derivatives

    def _render_and_encode(
        self,
        data_dir: Path,
        kind: str,
        window: PeriodWindow,
        frame_paths: list[Path],
        overlay_elements: list[OverlayElementDef] | None,
    ) -> Derivative | None:
        frames = []
        for path in frame_paths:
            image = _load_frame_bgr(path)
            if image is None:
                continue
            if overlay_elements:
                metadata = _load_metadata(path)
                if metadata is not None:
                    image = rasterize(image, overlay_elements, metadata, data_dir / "overlay_assets")
            frames.append(image)
        if not frames:
            return None

        variant = "overlay" if overlay_elements else "clean"
        out_dir = paths.date_dir(data_dir, "timelapses", window.end_at)
        out_path = out_dir / f"{paths.timestamp_stem(window.start_at)}_{kind}_{variant}.mp4"
        tmp_root = data_dir / "timelapses" / ".tmp"

        written = encode_timelapse(frames, self._cfg.fps, out_path, tmp_root)
        if written is None:
            return None

        return Derivative(
            kind=f"timelapse_{kind}",
            created_at=window.end_at,
            image=None,
            path=written,
            metadata={
                "period": kind,
                "variant": variant,
                "start_at": window.start_at.isoformat(),
                "end_at": window.end_at.isoformat(),
                "frame_count": len(frames),
            },
        )

    def _current_overlay_elements(self) -> list[OverlayElementDef] | None:
        if self.config_manager is None:
            return None
        overlay_cfg = self.config_manager.current.plugins.get("overlay")
        if overlay_cfg is None or not overlay_cfg.enabled:
            return None
        try:
            settings = OverlaySettings.model_validate(overlay_cfg.settings)
        except Exception:
            logger.exception("Active overlay config invalid — skipping overlay timelapse variant")
            return None
        return settings.active_elements()
