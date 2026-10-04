"""Server-side rasterization of `OverlayElementDef`s onto a historical
frame, for timelapse burn-in (see `timelapse.py`). This is the only
Python-side overlay renderer in the repo — the live view is rendered
entirely as CSS by the frontend's `OverlayRenderer.tsx`, which never touches
pixels.

v1 scope is intentionally limited to the `overlay` plugin's element kinds
(mask/label/image) from whichever template is active at generation time —
the system-provided elements (`timestamp`, `exposure_readout`,
`sky_state_badge`) and `telescope_position`'s `telescope_marker` are
live-view-only conveniences and are not rasterized here.
"""

from __future__ import annotations

import logging
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw

from caelum.capture.metadata import FrameMetadata
from caelum.derivatives.overlay import OverlayElementDef, _render_label_text

logger = logging.getLogger(__name__)


def _hex_to_rgb(color: str) -> tuple[int, int, int]:
    color = color.lstrip("#")
    return int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16)


def rasterize(
    image: np.ndarray,
    elements: list[OverlayElementDef],
    metadata: FrameMetadata,
    assets_dir: Path,
) -> np.ndarray:
    """`image`: BGR uint8 (as read by `cv2.imread`/`fits_to_bgr`). Returns a
    new BGR uint8 array of the same shape with `elements` drawn on top. A
    single element's drawing failure is logged and skipped rather than
    aborting the whole frame."""
    height, width = image.shape[:2]
    base = Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB)).convert("RGBA")

    for element in elements:
        try:
            if element.kind == "mask" and element.w is not None and element.h is not None:
                _draw_mask(base, element, width, height)
            elif element.kind == "label" and element.template:
                _draw_label(base, element, width, height, metadata)
            elif element.kind == "image" and element.w is not None and element.h is not None and element.asset:
                _draw_image_asset(base, element, width, height, assets_dir)
        except Exception:
            logger.exception("Overlay element %r failed to rasterize — skipping it", element.id)

    rgb = np.array(base.convert("RGB"))
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)


def _draw_mask(base: Image.Image, element: OverlayElementDef, width: int, height: int) -> None:
    assert element.w is not None and element.h is not None
    x0, y0 = int(element.x * width), int(element.y * height)
    x1, y1 = int((element.x + element.w) * width), int((element.y + element.h) * height)
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    rgb = _hex_to_rgb(element.color)
    alpha = int(element.opacity * 255)
    ImageDraw.Draw(layer).rectangle([x0, y0, x1, y1], fill=(*rgb, alpha))
    base.alpha_composite(layer)


def _draw_label(
    base: Image.Image, element: OverlayElementDef, width: int, height: int, metadata: FrameMetadata
) -> None:
    assert element.template is not None
    text = _render_label_text(element.template, metadata)
    draw = ImageDraw.Draw(base)
    rgb = _hex_to_rgb(element.color)
    # v1: PIL's bundled default bitmap font — fixed size, `font_size_px` not
    # honored yet. A scalable TTF is a documented follow-up, not needed to
    # make burned-in labels legible for a first version.
    draw.text((int(element.x * width), int(element.y * height)), text, fill=(*rgb, 255))


def _draw_image_asset(
    base: Image.Image, element: OverlayElementDef, width: int, height: int, assets_dir: Path
) -> None:
    assert element.w is not None and element.h is not None and element.asset is not None
    asset_path = assets_dir / element.asset
    if not asset_path.is_file():
        return
    asset = Image.open(asset_path).convert("RGBA")
    target_w = max(1, int(element.w * width))
    target_h = max(1, int(element.h * height))
    asset = asset.resize((target_w, target_h))
    base.paste(asset, (int(element.x * width), int(element.y * height)), asset)
