"""The sky above the camera as the lens sees it, and the tool that calibrates the lens.

* `GET  /sky/setup`          — the lens and the observer's position, for the
  browser to draw the sky live (preview level);
* `GET  /sky/objects`        — stars/Sun/Moon/planets projected onto the frame
  with the configured lens (preview level: it is what the live view's hover
  popups are built from);
* `POST /sky/objects`        — the same for a lens given in the request, so
  the calibration page can show a candidate before it is saved;
* `POST /camera/lens/detect-circle` and `POST /camera/lens/fit-stars` — find
  the lens geometry from the latest frame (admin; see `sky/lens_fit.py`);
* `POST /camera/lens/fit-pairs` — solve the lens (roll, tilt, field of view…)
  from stars the user has dragged onto their real places in the image;
* `GET  /camera/lens/stored-frame` and `.../stored-frame/image` — a stored DNG
  as a picture to calibrate on, with the time and place it was taken at.

Nothing here writes configuration: the UI saves a result through
`PUT /api/config` like any other setting.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Literal

import cv2
import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field

from caelum.api.deps import get_config_manager, get_frame_store, get_settings
from caelum.capture.frame_store import FrameStore, ProcessedFrame
from caelum.config.manager import ConfigManager
from caelum.config.schema import LensConfig
from caelum.settings import Settings
from caelum.sky import lens_fit
from caelum.sky.positions import sky_objects
from caelum.storage import browse, dng_reader

router = APIRouter()  # preview level
lens_router = APIRouter()  # admin only


class SkyObjectResponse(BaseModel):
    kind: str
    name: str
    mag: float
    alt_deg: float
    az_deg: float
    #: Fractions of the frame width / height.
    x: float
    y: float


class SkyObjectsResponse(BaseModel):
    time: datetime
    aspect: float
    lens: LensConfig
    objects: list[SkyObjectResponse]


class SkyObjectsRequest(BaseModel):
    lens: LensConfig
    max_mag: float = Field(default=4.5, ge=-2.0, le=6.0)
    bodies: bool = True
    at: datetime | None = None


class FitStarsRequest(BaseModel):
    #: Solve for the field of view (radius held at the detected circle).
    fit_fov: bool = True
    #: Start from the configured lens instead of detecting the circle first.
    from_config: bool = False


def _frame_geometry(frame: ProcessedFrame | None, config: ConfigManager) -> tuple[int, int]:
    if frame is not None:
        height, width = frame.image.shape[:2]
        return width, height
    width, height = config.current.camera.resolution
    return width, height


def _project(lens: LensConfig, size: tuple[int, int], when: datetime, config: ConfigManager,
             max_mag: float, bodies: bool) -> list[SkyObjectResponse]:
    location = config.current.location
    horizon = 90.0 - lens.fov_deg / 2.0 - lens.tilt_deg  # lowest altitude the lens can see
    found = sky_objects(
        when, location.lat, location.lon, location.elevation_m, max_mag=max_mag, min_alt_deg=horizon, bodies=bodies
    )
    if not found:
        return []
    pixels = lens_fit.project_to_pixels(
        np.array([o.alt_deg for o in found]),
        np.array([o.az_deg for o in found]),
        lens_fit.Lens(**lens.model_dump()),
        size,
    )
    out = []
    for obj, (px, py) in zip(found, pixels, strict=True):
        x, y = px / size[0], py / size[1]
        if np.isnan(x) or not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
            continue
        out.append(SkyObjectResponse(kind=obj.kind, name=obj.name, mag=round(obj.mag, 2),
                                     alt_deg=round(obj.alt_deg, 2), az_deg=round(obj.az_deg, 2),
                                     x=round(float(x), 5), y=round(float(y), 5)))
    return out


def _frame_time(frame: ProcessedFrame | None) -> datetime:
    return frame.metadata.captured_at if frame is not None else datetime.now(UTC)


class SkySetupResponse(BaseModel):
    """What the browser needs to draw the sky over the live view itself."""

    lens: LensConfig
    lat: float
    lon: float
    elevation_m: float


@router.get("/sky/setup", response_model=SkySetupResponse)
def get_sky_setup(config: ConfigManager = Depends(get_config_manager)) -> SkySetupResponse:
    cfg = config.current
    return SkySetupResponse(lens=cfg.camera.lens, lat=cfg.location.lat, lon=cfg.location.lon,
                            elevation_m=cfg.location.elevation_m)


@router.get("/sky/objects", response_model=SkyObjectsResponse)
def get_sky_objects(
    max_mag: float = Query(4.5, ge=-2.0, le=6.0),
    bodies: bool = Query(True),
    frame_store: FrameStore = Depends(get_frame_store),
    config: ConfigManager = Depends(get_config_manager),
) -> SkyObjectsResponse:
    frame = frame_store.get_latest()
    width, height = _frame_geometry(frame, config)
    when = _frame_time(frame)
    lens = config.current.camera.lens
    return SkyObjectsResponse(time=when, aspect=width / height, lens=lens,
                              objects=_project(lens, (width, height), when, config, max_mag, bodies))


@lens_router.post("/sky/objects", response_model=SkyObjectsResponse)
def project_sky_objects(
    body: SkyObjectsRequest,
    frame_store: FrameStore = Depends(get_frame_store),
    config: ConfigManager = Depends(get_config_manager),
) -> SkyObjectsResponse:
    frame = frame_store.get_latest()
    width, height = _frame_geometry(frame, config)
    when = body.at or _frame_time(frame)
    return SkyObjectsResponse(
        time=when, aspect=width / height, lens=body.lens,
        objects=_project(body.lens, (width, height), when, config, body.max_mag, body.bodies),
    )


def _latest_or_409(frame_store: FrameStore) -> ProcessedFrame:
    frame = frame_store.get_latest()
    if frame is None:
        raise HTTPException(status_code=409, detail="No frame has been captured yet")
    return frame


@lens_router.post("/camera/lens/detect-circle")
def detect_circle(frame_store: FrameStore = Depends(get_frame_store)) -> dict:
    """The lit fisheye disc in the latest frame: centre and radius as the config stores them."""
    frame = _latest_or_409(frame_store)
    fit = lens_fit.detect_image_circle(frame.image)
    if fit is None:
        raise HTTPException(
            status_code=422,
            detail="No clear image circle found — the frame needs a visible difference between "
                   "the lens disc and the black outside it.",
        )
    height, width = frame.image.shape[:2]
    return {**fit.to_dict(), "image_width": width, "image_height": height}


@lens_router.post("/camera/lens/fit-stars")
def fit_stars(
    body: FitStarsRequest,
    frame_store: FrameStore = Depends(get_frame_store),
    config: ConfigManager = Depends(get_config_manager),
) -> dict:
    """Fit the lens to the stars in the latest frame — needs a clear night frame."""
    frame = _latest_or_409(frame_store)
    height, width = frame.image.shape[:2]
    size = (width, height)
    configured = config.current.camera.lens

    if body.from_config:
        initial = lens_fit.Lens(**configured.model_dump())
    else:
        circle = lens_fit.detect_image_circle(frame.image)
        if circle is None:
            raise HTTPException(status_code=422, detail="No clear image circle found to start from")
        initial = lens_fit.Lens(circle.center_x, circle.center_y, circle.radius)

    circle_px = (initial.center_x * width, initial.center_y * height, initial.radius * min(size))
    stars = lens_fit.detect_stars(frame.image, circle=circle_px)
    if len(stars) < 8:
        raise HTTPException(
            status_code=422,
            detail=f"Only {len(stars)} stars detected — use a clear, dark night frame (no Moon, no cloud).",
        )
    location = config.current.location
    fit = lens_fit.fit_lens_from_stars(
        stars, size, frame.metadata.captured_at, location.lat, location.lon, initial, fit_fov=body.fit_fov
    )
    if fit is None:
        raise HTTPException(
            status_code=422,
            detail=f"{len(stars)} stars detected but they do not line up with the catalog for "
                   f"{frame.metadata.captured_at:%Y-%m-%d %H:%M} UTC at the configured location — "
                   "check location.lat/lon and the camera clock.",
        )
    return {**fit.to_dict(), "frame_time": frame.metadata.captured_at, "image_width": width, "image_height": height}


class PairPoint(BaseModel):
    #: The catalog star's sky position and where it really is in the frame
    #: (fractions of the width / height).
    alt_deg: float = Field(ge=-90.0, le=90.0)
    az_deg: float
    x: float = Field(ge=0.0, le=1.0)
    y: float = Field(ge=0.0, le=1.0)


class FitPairsRequest(BaseModel):
    #: The starting lens: what is not solved for stays as it is here.
    lens: LensConfig
    pairs: list[PairPoint] = Field(min_length=2, max_length=500)
    free: list[Literal["roll", "tilt", "center", "fov", "radius"]] = Field(
        default_factory=lambda: ["roll", "tilt", "fov"], min_length=1
    )
    #: Also try the lens with east and west swapped and keep the better one.
    try_mirror: bool = False
    image_width: int = Field(gt=0, le=65536)
    image_height: int = Field(gt=0, le=65536)


@lens_router.post("/camera/lens/fit-pairs")
def fit_pairs(body: FitPairsRequest) -> dict:
    """Solve the lens from stars matched by hand. Needs no frame: the pairs and the frame's size say it all."""
    size = (body.image_width, body.image_height)
    pairs = np.array([[p.alt_deg, p.az_deg, p.x * size[0], p.y * size[1]] for p in body.pairs])
    try:
        fit = lens_fit.fit_lens_from_pairs(
            pairs, size, lens_fit.Lens(**body.lens.model_dump()), tuple(body.free), try_mirror=body.try_mirror
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return fit.to_dict()


# ---- a stored frame to calibrate on -----------------------------------------


class StoredFrameInfo(BaseModel):
    path: str
    captured_at: datetime
    lat: float
    lon: float
    elevation_m: float
    #: Sensor size, not the size of the picture served.
    width: int
    height: int


def _xmp_attribute(xmp: bytes, name: str) -> str | None:
    match = re.search(rb'caelum:' + name.encode() + rb'="([^"]*)"', xmp)
    return match.group(1).decode() if match else None


def _read_stored_dng(settings: Settings, path: str) -> tuple[bytes, dng_reader.DngInfo, StoredFrameInfo]:
    try:
        target = browse.resolve_within(settings.data_dir, path)
    except browse.PathOutsideRoot as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not target.is_file():
        raise HTTPException(status_code=404, detail=f"No such file: {path}")
    if target.suffix.lower() != ".dng":
        raise HTTPException(status_code=415, detail="Only DNG frames can be used for calibration")
    data = target.read_bytes()
    try:
        info = dng_reader.parse(data)
        xmp = dng_reader.xmp_packet(data)
    except dng_reader.DngFormatError as exc:
        raise HTTPException(status_code=422, detail=f"Not a readable DNG: {exc}") from exc
    when = _xmp_attribute(xmp or b"", "captured_at")
    lat, lon = _xmp_attribute(xmp or b"", "latitude_deg"), _xmp_attribute(xmp or b"", "longitude_deg")
    if when is None or lat is None or lon is None:
        raise HTTPException(
            status_code=422,
            detail="This DNG carries no caelum capture time and position, so the sky above it cannot be worked out.",
        )
    elevation = _xmp_attribute(xmp or b"", "elevation_m")
    return data, info, StoredFrameInfo(
        path=path, captured_at=datetime.fromisoformat(when), lat=float(lat), lon=float(lon),
        elevation_m=float(elevation) if elevation else 0.0, width=info.width, height=info.height,
    )


@lens_router.get("/camera/lens/stored-frame", response_model=StoredFrameInfo)
def get_stored_frame_info(
    path: str = Query(..., description="DNG path relative to the data directory"),
    settings: Settings = Depends(get_settings),
) -> StoredFrameInfo:
    return _read_stored_dng(settings, path)[2]


@lens_router.get("/camera/lens/stored-frame/image")
def get_stored_frame_image(path: str = Query(...), max_dim: int = Query(2048, ge=256, le=4096),
                           settings: Settings = Depends(get_settings)) -> Response:
    """The DNG as a PNG stretched so that faint stars show — what the calibration is drawn on."""
    data, info, _ = _read_stored_dng(settings, path)
    gray = dng_reader.linear_rgb(data, info, max_dim).mean(axis=2)
    low, high = np.percentile(gray, [1.0, 99.7])
    stretched = np.arcsinh(8.0 * np.clip((gray - low) / max(high - low, 1e-6), 0.0, 1.0)) / np.arcsinh(8.0)
    ok, encoded = cv2.imencode(".png", (stretched * 255.0).astype(np.uint8))
    if not ok:
        raise HTTPException(status_code=500, detail="PNG encoding failed")
    return Response(
        content=encoded.tobytes(), media_type="image/png", headers={"Cache-Control": "private, max-age=300"}
    )
