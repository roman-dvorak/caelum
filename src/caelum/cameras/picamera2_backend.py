"""Raspberry Pi camera backend via picamera2/libcamera.

Only importable where `picamera2` is installed (the `picamera2` extra,
ARM-only) — see registry.py for the lazy import that keeps this module out
of the way on dev machines. Not exercised by the test suite against real
hardware (the leak-cleanup path is, with a fake `Picamera2`); validate on
real hardware per the project plan's verification checklist.

Each capture delivers both the ISP-processed "main" RGB stream and the
sensor's full-resolution raw Bayer stream of the same exposure — the raw
buffer is copied out (so the request can be released straight away) and
later written as DNG by the processing worker.

Captures are on demand — see `Picamera2Backend`.
"""

from __future__ import annotations

import atexit
import logging
import os
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np

from caelum.config.schema import CameraConfig

from .base import CameraBackend, CameraCapabilities, CameraStalled, RawFrame

try:
    from picamera2 import Picamera2
except ImportError as exc:  # pragma: no cover - exercised only on real hardware
    Picamera2 = None  # type: ignore[assignment,misc]
    _import_error: Exception | None = exc
else:
    _import_error = None

logger = logging.getLogger(__name__)

# Frame length beyond the exposure itself, per capture.
_FRAME_MARGIN_US = 100_000
# A frame whose exposure/gain is further than this from the request isn't
# the one asked for; at most `_MAX_EXTRA_FRAMES` more are taken.
_MATCH_TOLERANCE = 0.05
_MAX_EXTRA_FRAMES = 2
# A frame not delivered within its exposure plus this is never coming.
_FRAME_GRACE_S = 3.0

_BAYER_ORDERS = ("RGGB", "BGGR", "GRBG", "GBRG")

# Set when an open or a capture failed in a way that can leave libcamera's
# process-wide camera manager with a stale view of the sensor — see
# `_reset_camera_manager`.
_manager_suspect = False


def _reset_camera_manager() -> None:
    """Drop picamera2's process-wide libcamera CameraManager so the next
    camera open enumerates the sensor afresh.

    If the manager is first created while another process holds the camera
    (it happens right after boot), libcamera can't set the sensor's controls
    while enumerating ("Unable to set controls: Device or resource busy") and
    keeps the sensor's unflipped formats; every later open in this process
    then configures a raw stream (SRGGB) that doesn't match what the rotated
    sensor delivers (SBGGR), and capture hangs. Only safe with no camera
    open — called from `open()`, after the previous one was closed."""
    manager = getattr(Picamera2, "_cm", None)
    if manager is None or getattr(manager, "cameras", None):
        return
    try:
        manager.reset()
        logger.info("Reset the libcamera camera manager")
    except Exception:  # noqa: BLE001
        logger.warning("Resetting the libcamera camera manager failed", exc_info=True)


def _cleanup_failed_init(cam: Any) -> None:
    """Undo what a `Picamera2()` constructor that raised had already set up.

    `Picamera2.__init__` opens a notification pipe and registers itself with
    the process-wide camera manager *before* acquiring the camera. When the
    acquire fails (e.g. "Device or resource busy" because another process
    owns the camera) it raises, the half-built object is unreachable, and
    its `close()` returns early because `is_open` is still False — so the
    two pipe fds and the manager entry leak. Retried once a second, that
    exhausts the process's fd limit in under 20 minutes and takes the HTTP
    server down with it."""
    camera = getattr(cam, "camera", None)
    if camera is not None and getattr(cam, "is_open", False):
        try:
            camera.release()
        except Exception:  # noqa: BLE001 - best effort, the camera may never have been acquired
            pass
    idx = getattr(cam, "camera_idx", None)
    manager = getattr(type(cam), "_cm", None)
    if idx is not None and manager is not None and idx in getattr(manager, "cameras", {}):
        try:
            manager.cleanup(idx)
        except Exception:  # noqa: BLE001
            logger.debug("Camera manager cleanup after failed open raised", exc_info=True)
    reader = getattr(cam, "notifymeread", None)
    if reader is not None:
        try:
            reader.close()
        except OSError:
            pass
    elif getattr(cam, "notifyme_r", None) is not None:
        try:
            os.close(cam.notifyme_r)
        except OSError:
            pass
    if getattr(cam, "notifyme_w", None) is not None:
        try:
            os.close(cam.notifyme_w)
        except OSError:
            pass
    close = getattr(cam, "close", None)
    if close is not None:
        atexit.unregister(close)


def _construct_picamera2(factory: Any) -> Any:
    """`factory()`, but cleaning up after it if it raises — see
    `_cleanup_failed_init`."""
    cam = factory.__new__(factory)
    try:
        cam.__init__()
    except Exception:
        _cleanup_failed_init(cam)
        raise
    return cam


def _plain(value: Any) -> Any:
    """libcamera metadata -> JSON-able Python values (tuples become lists,
    numpy scalars become Python scalars), so it can cross a process
    boundary and land in a sidecar unchanged."""
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, (bool, int, float, str)) or value is None:
        return value
    return str(value)


class Picamera2Backend(CameraBackend):
    """Captures on demand: the camera stays stopped between captures, and
    each `capture_frame()` starts it with the controls set beforehand, takes
    the first frame and stops it again.

    libcamera writes the start controls to the sensor before the first frame,
    so that frame already has exactly the requested exposure and gain — no
    pipeline latency. (A continuously running camera applies a change only
    6–7 frames later: with long frames, minutes.) The cost is ~0.2 s of
    start/readout overhead per capture on top of the exposure itself."""

    def __init__(self, cfg: CameraConfig) -> None:
        if Picamera2 is None:
            raise RuntimeError(
                "picamera2 is not installed — install the 'picamera2' extra on a Raspberry Pi"
            ) from _import_error
        self.capabilities = CameraCapabilities(max_resolution=cfg.resolution, supports_streaming=True)
        self._resolution = cfg.resolution
        self._wb_auto = cfg.wb_auto
        self._wb_red_gain = cfg.wb_red_gain
        self._wb_blue_gain = cfg.wb_blue_gain
        self._picam2: Picamera2 | None = None
        self._raw_config: dict[str, Any] | None = None
        self._model = ""
        self._requested: tuple[int, float] | None = None

    def open(self) -> None:
        global _manager_suspect
        if _manager_suspect:
            _reset_camera_manager()
            _manager_suspect = False
        try:
            picam2 = _construct_picamera2(Picamera2)
        except Exception:
            _manager_suspect = True  # e.g. busy: the manager may now hold stale sensor state
            raise
        self._picam2 = picam2
        try:
            # The raw stream's Bayer order has to match what the sensor
            # really delivers. With a sensor mounted rotated (IMX477 here
            # reports Rotation 180, compensated by flipping it both ways)
            # picamera2 gets it wrong: it takes the order from sensor modes
            # read at start-up, in whatever flip state the sensor was left —
            # SRGGB after a fresh boot, while libcamera then selects SBGGR. A
            # mismatch makes Unicam reject every buffer ("Failed to queue
            # buffer ... Invalid argument") and capture hangs inside
            # libcamera. libcamera's own validated configuration has the
            # right order, so configure, read it back, and if picamera2's
            # request differs, configure again with exactly that.
            self._configure(None)
        except Exception:
            self._picam2 = None
            try:
                if picam2.started:
                    picam2.stop()
                picam2.close()
            except Exception:  # noqa: BLE001
                logger.debug("picamera2 close after failed open raised", exc_info=True)
            raise
        self._model = str(picam2.camera_properties.get("Model", "") or "")
        logger.info("picamera2 raw stream: %s", self._raw_config)
        self.set_white_balance(self._wb_red_gain, self._wb_blue_gain, auto=self._wb_auto)

    def _configure(self, raw_format: str | None) -> None:
        assert self._picam2 is not None
        raw = {} if raw_format is None else {"format": raw_format}
        self._picam2.configure(self._picam2.create_still_configuration(main={"size": self._resolution}, raw=raw))
        requested = str((self._picam2.camera_configuration().get("raw") or {}).get("format", ""))
        actual = self._libcamera_raw_format()
        if actual and requested and actual != requested:
            if raw_format is not None:
                raise RuntimeError(f"libcamera keeps adjusting the raw format ({requested} -> {actual})")
            logger.info("Raw format %s adjusted by libcamera to %s — reconfiguring with it", requested, actual)
            self._configure(actual)
            return
        raw_cfg = self._picam2.camera_configuration().get("raw") or {}
        self._raw_config = {
            "format": str(raw_cfg.get("format", "")),
            "size": list(raw_cfg.get("size", (0, 0))),
            "stride": int(raw_cfg.get("stride", 0)),
        } if raw_cfg else None

    def _libcamera_raw_format(self) -> str | None:
        """The raw stream's pixel format as libcamera validated it."""
        assert self._picam2 is not None
        config = getattr(self._picam2, "libcamera_config", None)
        if config is None:
            return None
        for i in range(config.size):
            fmt = str(config.at(i).pixel_format)
            if any(order in fmt for order in _BAYER_ORDERS):
                return fmt
        return None

    def close(self) -> None:
        if self._picam2 is not None:
            try:
                if self._picam2.started:
                    self._picam2.stop()
            finally:
                self._picam2.close()
                self._picam2 = None

    def configure(self, cfg: CameraConfig) -> None:
        self._resolution = cfg.resolution
        self._wb_auto = cfg.wb_auto
        self._wb_red_gain = cfg.wb_red_gain
        self._wb_blue_gain = cfg.wb_blue_gain
        if self._picam2 is not None:
            self.close()
            self.open()

    def set_controls(self, exposure_us: int, analogue_gain: float) -> None:
        """Takes effect at the next `capture_frame()` (the camera is stopped
        in between)."""
        assert self._picam2 is not None, "set_controls() called before open()"
        # The frame just long enough for the exposure, so the one frame
        # taken per start isn't stretched by a default frame rate.
        frame_us = int(exposure_us) + _FRAME_MARGIN_US
        self._picam2.set_controls(
            {
                "AeEnable": False,  # the app owns exposure, never the camera's built-in AE
                "ExposureTime": int(exposure_us),
                "AnalogueGain": float(analogue_gain),
                "FrameDurationLimits": (frame_us, frame_us),
            }
        )
        self._requested = (int(exposure_us), float(analogue_gain))

    def set_white_balance(self, red_gain: float, blue_gain: float, auto: bool = False) -> None:
        assert self._picam2 is not None, "set_white_balance() called before open()"
        self._wb_auto = auto
        self._wb_red_gain = red_gain
        self._wb_blue_gain = blue_gain
        if auto:
            # Auto white balance needs a run of frames to converge, which
            # one-frame captures never give it — it'll stay where it starts.
            logger.warning("Auto white balance doesn't converge with on-demand captures; set fixed gains instead")
            self._picam2.set_controls({"AwbEnable": True})
        else:
            self._picam2.set_controls({"AwbEnable": False, "ColourGains": (red_gain, blue_gain)})

    def _matches_request(self, meta: dict[str, Any]) -> bool:
        if self._requested is None:
            return True
        exposure_us, gain = self._requested
        return (
            abs(float(meta.get("ExposureTime", 0)) - exposure_us) <= _MATCH_TOLERANCE * exposure_us
            and abs(float(meta.get("AnalogueGain", 0.0)) - gain) <= _MATCH_TOLERANCE * gain
        )

    def _next_request(self, wait_s: float) -> Any:
        assert self._picam2 is not None
        try:
            return self._picam2.capture_request(wait=wait_s)
        except TimeoutError as exc:
            global _manager_suspect
            _manager_suspect = True
            # The timed-out capture job stays first in picamera2's job list,
            # and stop() queues behind it — waiting for a frame that never
            # comes. Drop it so the camera can be stopped and closed.
            self._picam2.cancel_all_and_flush()
            raise CameraStalled(f"No frame from the camera within {wait_s:.1f}s") from exc

    def capture_frame(self) -> RawFrame:
        assert self._picam2 is not None, "capture_frame() called before open()"
        picam2 = self._picam2
        wait_s = (self._requested[0] / 1e6 if self._requested else 0.0) + _FRAME_GRACE_S
        picam2.start()
        try:
            request = self._next_request(wait_s)
            # The first frame normally carries the start controls already; if
            # the sensor ever disagrees, give it a frame or two more.
            for _ in range(_MAX_EXTRA_FRAMES):
                if self._matches_request(request.get_metadata()):
                    break
                logger.warning("First frame after start not at the requested exposure/gain — taking another")
                request.release()
                request = self._next_request(wait_s)
            try:
                # make_array copies out of the mapped buffer (make_buffer is
                # an np.array() of it), so both survive the release below.
                image = request.make_array("main")
                raw = request.make_array("raw") if self._raw_config is not None else None
                meta = request.get_metadata()
            finally:
                request.release()
        finally:
            picam2.stop()

        exposure_us = int(meta.get("ExposureTime", 0))
        # SensorTimestamp is CLOCK_MONOTONIC at the end of the exposure.
        # captured_at is the *middle* of the exposure, in wall-clock time.
        sensor_ts = int(meta.get("SensorTimestamp", 0))
        captured_at = datetime.now(UTC)
        exposure_start_ns = None
        if sensor_ts:
            lag_ns = time.monotonic_ns() - sensor_ts
            if 0 <= lag_ns < 3_600_000_000_000:
                captured_at -= timedelta(microseconds=lag_ns // 1000 + exposure_us // 2)
            exposure_start_ns = sensor_ts - exposure_us * 1000

        # picamera2's "main" stream for a still configuration is ISP-processed
        # (already debayered); drop an alpha channel if the platform's default
        # format includes one, keeping RGB order.
        if image.ndim == 3 and image.shape[2] == 4:
            image = image[:, :, :3]
        image = np.ascontiguousarray(image)

        return RawFrame(
            image=image,
            exposure_us=exposure_us,
            analogue_gain=float(meta.get("AnalogueGain", 0.0)),
            sensor_timestamp_ns=sensor_ts,
            captured_at=captured_at,
            raw_bayer=raw,
            raw_stream_config=dict(self._raw_config) if self._raw_config is not None else None,
            camera_metadata=_plain(meta),
            camera_model=self._model,
            exposure_start_monotonic_ns=exposure_start_ns,
        )
