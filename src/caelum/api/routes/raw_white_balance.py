"""White balance edited against a stored RAW frame, non-destructively.

The browser loads one DNG's pixels once — camera-space linear RGB, no white
balance or colour matrix applied (`/raw/white-balance/pixels`) — plus what
it needs to render them (`/raw/white-balance`), and applies gains, matrix
and tone curve itself, so dragging a slider costs no round-trip.

Saving writes only the file's `AsShotNeutral` tag (see
`storage/dng_reader.py`); the sensor data is never rewritten. Making the
same gains the camera default for future frames is the existing
`POST /api/camera/white-balance`.
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query, Response

from caelum.api.deps import get_config_manager, get_settings
from caelum.api.schemas import RawWhiteBalanceInfo, RawWhiteBalanceSaveRequest
from caelum.config.manager import ConfigManager
from caelum.settings import Settings
from caelum.storage import browse, dng_reader, paths

router = APIRouter()

_DATE_PART_RE = (re.compile(r"^\d{4}$"), re.compile(r"^\d{2}$"), re.compile(r"^\d{2}$"))


def latest_dng(data_dir: Path) -> Path | None:
    """Newest `.dng` under `raw/YYYY/MM/DD/` — walks the date directories
    newest-first and stops at the first one that has any."""

    def newest_first(directory: Path, pattern: re.Pattern[str]) -> list[Path]:
        if not directory.is_dir():
            return []
        return sorted((c for c in directory.iterdir() if c.is_dir() and pattern.match(c.name)), reverse=True)

    for year in newest_first(data_dir / "raw", _DATE_PART_RE[0]):
        for month in newest_first(year, _DATE_PART_RE[1]):
            for day in newest_first(month, _DATE_PART_RE[2]):
                dngs = [c for c in day.iterdir() if c.is_file() and c.suffix.lower() == ".dng"]
                if dngs:
                    return max(dngs, key=lambda c: c.name)
    return None


def _resolve_dng(settings: Settings, path: str | None) -> Path:
    if not path:
        found = latest_dng(settings.data_dir)
        if found is None:
            raise HTTPException(status_code=404, detail="No RAW (DNG) frame stored yet")
        return found
    try:
        target = browse.resolve_within(settings.data_dir, path)
    except browse.PathOutsideRoot as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not target.is_file() or target.suffix.lower() != ".dng":
        raise HTTPException(status_code=404, detail=f"No such DNG: {path}")
    return target


def _describe(settings: Settings, config_manager: ConfigManager, target: Path, info: dng_reader.DngInfo, max_dim: int):
    h2, w2 = info.height // 2, info.width // 2
    factor = max(1, -(-max(h2, w2) // max_dim))
    gains = info.gains
    camera = config_manager.current.camera
    captured = paths.capture_time_of(target)
    return RawWhiteBalanceInfo(
        path=browse.relative_to(settings.data_dir, target),
        captured_at=captured.isoformat() if captured else None,
        sensor_width=info.width,
        sensor_height=info.height,
        width=w2 // factor,
        height=h2 // factor,
        as_shot_neutral=list(info.as_shot_neutral) if info.as_shot_neutral else None,
        red_gain=gains[0] if gains else 1.0,
        blue_gain=gains[1] if gains else 1.0,
        captured_red_gain=info.captured_gains[0] if info.captured_gains else None,
        captured_blue_gain=info.captured_gains[1] if info.captured_gains else None,
        render_matrix=dng_reader.render_matrix(info),
        camera_wb_auto=camera.wb_auto,
        camera_red_gain=camera.wb_red_gain,
        camera_blue_gain=camera.wb_blue_gain,
    )


def _read(target: Path) -> tuple[bytes, dng_reader.DngInfo]:
    data = target.read_bytes()
    try:
        return data, dng_reader.parse(data)
    except dng_reader.DngFormatError as exc:
        raise HTTPException(status_code=422, detail=f"{target.name}: {exc}") from exc


@router.get("/raw/white-balance", response_model=RawWhiteBalanceInfo)
def get_raw_white_balance(
    path: str | None = Query(None, description="DNG path relative to the data directory; newest RAW frame if omitted"),
    max_dim: int = Query(1024, ge=64, le=4096),
    settings: Settings = Depends(get_settings),
    config_manager: ConfigManager = Depends(get_config_manager),
) -> RawWhiteBalanceInfo:
    target = _resolve_dng(settings, path)
    _, info = _read(target)
    return _describe(settings, config_manager, target, info, max_dim)


@router.get("/raw/white-balance/pixels")
def get_raw_white_balance_pixels(
    path: str = Query(..., description="DNG path relative to the data directory"),
    max_dim: int = Query(1024, ge=64, le=4096),
    settings: Settings = Depends(get_settings),
) -> Response:
    """Interleaved RGB, little-endian `uint16`, 0..65535 = black..white
    level, `X-Width` x `X-Height` pixels — linear camera space, so the
    client can white-balance it exactly. No 8-bit image format would do:
    a night frame lives in the bottom few percent of the range."""
    target = _resolve_dng(settings, path)
    data, info = _read(target)
    rgb = dng_reader.linear_rgb(data, info, max_dim)
    payload = np.round(rgb * 65535.0).astype("<u2").tobytes()
    return Response(
        content=payload,
        media_type="application/octet-stream",
        headers={"X-Width": str(rgb.shape[1]), "X-Height": str(rgb.shape[0]), "Cache-Control": "no-store"},
    )


@router.put("/raw/white-balance", response_model=RawWhiteBalanceInfo)
def save_raw_white_balance(
    body: RawWhiteBalanceSaveRequest,
    settings: Settings = Depends(get_settings),
    config_manager: ConfigManager = Depends(get_config_manager),
) -> RawWhiteBalanceInfo:
    target = _resolve_dng(settings, body.path)
    try:
        info = dng_reader.set_as_shot_neutral(target, body.red_gain, body.blue_gain)
    except dng_reader.DngFormatError as exc:
        raise HTTPException(status_code=422, detail=f"{target.name}: {exc}") from exc
    return _describe(settings, config_manager, target, info, 1024)
