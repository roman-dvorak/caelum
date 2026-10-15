"""Best-effort capture requests: nothing is refused — values beyond the
camera's ranges are clamped, options it lacks are ignored, and the frame
records what was requested and what was really used."""

from __future__ import annotations

from caelum.cameras import picamera2_backend
from caelum.cameras.base import CameraCapabilities, CaptureRequest
from caelum.cameras.mock_backend import MockCameraBackend
from caelum.config.schema import CameraConfig


def _mock(**caps) -> MockCameraBackend:
    camera = MockCameraBackend()
    if caps:
        camera.capabilities = CameraCapabilities(max_resolution=(64, 48), **caps)
    camera.open()
    return camera


def test_request_within_range_is_applied_as_is():
    frame = _mock().capture(CaptureRequest(exposure_us=20_000, analogue_gain=2.0, raw=False))
    settings = frame.capture_settings
    assert settings["requested"] == {"exposure_us": 20_000, "analogue_gain": 2.0, "raw": False}
    assert settings["applied"]["exposure_us"] == 20_000
    assert settings["applied"]["analogue_gain"] == 2.0
    assert settings["clamped"] == [] and settings["ignored"] == []


def test_values_beyond_the_range_are_clamped_to_the_maximum_possible():
    camera = _mock(exposure_us=(100, 50_000), analogue_gain=(1.0, 8.0))
    frame = camera.capture(CaptureRequest(exposure_us=200_000, analogue_gain=0.5, raw=False))
    assert frame.exposure_us == 50_000
    assert frame.analogue_gain == 1.0
    settings = frame.capture_settings
    assert settings["clamped"] == ["exposure_us", "analogue_gain"]
    assert settings["requested"]["exposure_us"] == 200_000
    assert settings["applied"]["exposure_us"] == 50_000


def test_unsupported_options_are_ignored_and_recorded():
    frame = _mock().capture(
        CaptureRequest(exposure_us=1000, colour_gains=(2.0, 1.5), raw=True, extra={"binning": 2})
    )
    settings = frame.capture_settings
    assert settings["ignored"] == ["colour_gains", "raw", "extra.binning"]
    assert settings["requested"]["extra"] == {"binning": 2}
    assert settings["applied"]["raw"] is False


def test_unknown_range_passes_values_through():
    camera = _mock()
    camera.capabilities = CameraCapabilities(max_resolution=(64, 48))
    frame = camera.capture(CaptureRequest(exposure_us=10**10, analogue_gain=100.0, raw=False))
    assert frame.exposure_us == 10**10
    assert frame.capture_settings["clamped"] == []


def test_capabilities_to_dict():
    caps = CameraCapabilities(max_resolution=(4056, 3040), model="imx477", exposure_us=(110, 694_422_939),
                              analogue_gain=(1.0, 22.26), raw=True, colour_gains=True)
    assert caps.to_dict() == {
        "model": "imx477",
        "max_resolution": [4056, 3040],
        "exposure_us": [110, 694_422_939],
        "analogue_gain": [1.0, 22.26],
        "raw": True,
        "colour_gains": True,
    }


class _FakePicam:
    camera_controls = {"ExposureTime": (110, 694_422_939, None), "AnalogueGain": (1.0, 22.26, None)}

    def __init__(self) -> None:
        self.controls: list[dict] = []

    def set_controls(self, controls: dict) -> None:
        self.controls.append(controls)


def _picamera2_backend(monkeypatch) -> picamera2_backend.Picamera2Backend:
    monkeypatch.setattr(picamera2_backend, "Picamera2", object)
    cfg = CameraConfig(backend="picamera2", wb_auto=False, wb_red_gain=2.1, wb_blue_gain=1.7)
    backend = picamera2_backend.Picamera2Backend(cfg)
    backend._picam2 = _FakePicam()
    backend._raw_config = {"format": "SBGGR12_CSI2P", "size": [4056, 3040], "stride": 6112}
    backend._model = "imx477"
    return backend


def test_picamera2_capabilities_come_from_camera_controls(monkeypatch):
    backend = _picamera2_backend(monkeypatch)
    caps = backend._read_capabilities(backend._picam2)
    assert caps.exposure_us == (110, 694_422_939)
    assert caps.analogue_gain == (1.0, 22.26)
    assert caps.raw and caps.colour_gains and caps.model == "imx477"


def test_picamera2_request_gains_apply_once_then_restore_configured_wb(monkeypatch):
    backend = _picamera2_backend(monkeypatch)
    backend.capabilities = backend._read_capabilities(backend._picam2)
    picam = backend._picam2
    record = backend.apply_request(CaptureRequest(exposure_us=1_000_000, analogue_gain=40.0, colour_gains=(3.0, 1.2)))
    assert record["clamped"] == ["analogue_gain"]
    assert {"AwbEnable": False, "ColourGains": (3.0, 1.2)} in picam.controls
    assert picam.controls[-1]["AnalogueGain"] == 22.26
    picam.controls.clear()
    backend.apply_request(CaptureRequest(exposure_us=1_000_000))
    assert {"AwbEnable": False, "ColourGains": (2.1, 1.7)} in picam.controls
    picam.controls.clear()
    backend.apply_request(CaptureRequest(exposure_us=1_000_000))
    assert all("ColourGains" not in c for c in picam.controls)


def test_capture_settings_reach_sidecar_and_xmp():
    from caelum.processing.pipeline import _capture_settings_xmp

    frame = _mock(exposure_us=(100, 50_000)).capture(
        CaptureRequest(exposure_us=200_000, colour_gains=(2.0, 1.5), extra={"binning": 2})
    )
    assert _capture_settings_xmp(frame.capture_settings) == {
        "requested_exposure_us": 200_000,
        "requested_analogue_gain": 1.0,
        "requested_colour_gains": "2.0000,1.5000",
        "capture_clamped": "exposure_us",
        "capture_ignored": "colour_gains,raw,extra.binning",
    }
    from caelum.capture.metadata import FrameMetadata

    assert "capture_settings" in FrameMetadata.model_fields
    from caelum.processing.jobs import FrameInfo

    assert "capture_settings" in FrameInfo.__dataclass_fields__
