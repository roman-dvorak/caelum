"""The sky above the camera as the lens sees it, and the tool that calibrates the lens.

* `GET  /sky/objects`        — stars/Sun/Moon/planets projected onto the frame
  with the configured lens (preview level: it is what the live view's hover
  popups are built from);
* `POST /sky/objects`        — the same for a lens given in the request, so
  the calibration page can show a candidate before it is saved;
* `POST /camera/lens/detect-circle` and `POST /camera/lens/fit-stars` — find
  the lens geometry from the latest frame (admin; see `sky/lens_fit.py`).

Nothing here writes configuration: the UI saves a result through
`PUT /api/config` like any other setting.
"""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from caelum.api.deps import get_config_manager, get_frame_store
from caelum.capture.frame_store import FrameStore, ProcessedFrame
from caelum.config.manager import ConfigManager
from caelum.config.schema import LensConfig
from caelum.sky import lens_fit
from caelum.sky.positions import sky_objects

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
    horizon = 90.0 - lens.fov_deg / 2.0  # lowest altitude the lens can see
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
