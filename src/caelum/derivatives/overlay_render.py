"""The one overlay renderer: draws a frame's `OverlayElement`s into a
transparent RGBA layer.

Everything that shows an overlay shows *these* pixels — the live view
stacks the layer over the stream (`/api/frame/overlay.png`), stored
thumbnails get it as `overlays/…/<stem>.png` next to them or burned into the
WebP itself (`storage_policy.overlay_mode`, see `DerivativePool`), the
remote viewer stacks the uploaded PNG, and timelapses composite it onto
each frame. No viewer renders overlay elements on its own, so the camera
and the remote archive cannot drift apart.

Sizes are defined at a 1024 px wide reference image and scaled with the
actual width, so one template looks the same on a thumbnail and on a
full-resolution frame (text has a floor of `_MIN_TEXT_PX`, so it stays
legible on small thumbnails). Text uses the bundled DejaVu Sans Mono (Pillow's own
default font has no ☉/☾/µ glyphs and no Czech diacritics).
"""

from __future__ import annotations

import io
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps

from caelum.capture.metadata import OverlayElement

logger = logging.getLogger(__name__)

REFERENCE_WIDTH = 1024

_FONT_DIR = Path(__file__).with_name("fonts")
BUILTIN_ASSETS_DIR = Path(__file__).with_name("overlay_builtin")
_LABEL_FONT_PX = 16
_MARGIN_PX = 8
#: Text never scales below this many actual pixels — on a small thumbnail the
#: readouts get relatively bigger rather than illegible.
_MIN_TEXT_PX = 9

_CHIP_BG = (8, 10, 14, 180)
_INK = (229, 229, 229, 255)
_AMBER = (232, 161, 58, 255)
_AMBER_BRIGHT = (246, 190, 100, 255)
_CYAN = (80, 200, 220, 210)
_VOID = (8, 10, 14, 255)

@lru_cache(maxsize=32)
def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    name = "DejaVuSansMono-Bold.ttf" if bold else "DejaVuSansMono.ttf"
    return ImageFont.truetype(str(_FONT_DIR / name), max(1, size))


def _hex_to_rgba(color: str | None, default: tuple[int, int, int, int], alpha: float = 1.0) -> tuple[int, ...]:
    if not color:
        return default
    value = color.lstrip("#")
    try:
        if len(value) == 3:
            value = "".join(c * 2 for c in value)
        r, g, b = int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)
    except ValueError:
        return default
    return r, g, b, round(max(0.0, min(1.0, alpha)) * 255)


def _num(payload: dict[str, Any], key: str) -> float | None:
    value = payload.get(key)
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def _str(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    return value if isinstance(value, str) and value else None


def _box(payload: dict[str, Any]) -> tuple[float, float, float, float] | None:
    values = [_num(payload, k) for k in ("x", "y", "w", "h")]
    if any(v is None for v in values):
        return None
    return tuple(values)  # type: ignore[return-value]


def format_exposure(exposure_us: float) -> str:
    if exposure_us >= 1_000_000:
        return f"{exposure_us / 1_000_000:.2f}s"
    if exposure_us >= 1_000:
        return f"{exposure_us / 1_000:.1f}ms"
    return f"{exposure_us:.0f}µs"


def _resolve_asset(assets_dir: Path | None, name: str) -> Path | None:
    """An uploaded asset, else a built-in one of the same name (the
    AstroMeters logo of the default template)."""
    for directory in (assets_dir, BUILTIN_ASSETS_DIR):
        if directory is not None and (directory / name).is_file():
            return directory / name
    return None


class _Canvas:
    def __init__(self, size: tuple[int, int], assets_dir: Path | None) -> None:
        self.image = Image.new("RGBA", size, (0, 0, 0, 0))
        self.width, self.height = size
        self.scale = self.width / REFERENCE_WIDTH
        self.assets_dir = assets_dir

    def px(self, reference_px: float) -> int:
        return max(1, round(reference_px * self.scale))

    def text_px(self, reference_px: float) -> int:
        return max(_MIN_TEXT_PX, self.px(reference_px))

    def draw(self) -> ImageDraw.ImageDraw:
        return ImageDraw.Draw(self.image)

    def paste_layer(self, layer: Image.Image) -> None:
        self.image.alpha_composite(layer)


def _draw_mask(c: _Canvas, p: dict[str, Any]) -> None:
    box = _box(p)
    if box is None:
        return
    x, y, w, h = box
    opacity = _num(p, "opacity")
    fill = _hex_to_rgba(_str(p, "color"), (0, 0, 0, 255), 1.0 if opacity is None else opacity)
    layer = Image.new("RGBA", c.image.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).rectangle(
        [round(x * c.width), round(y * c.height), round((x + w) * c.width) - 1, round((y + h) * c.height) - 1],
        fill=fill,
    )
    c.paste_layer(layer)


def _draw_custom_label(c: _Canvas, p: dict[str, Any]) -> None:
    text, x, y = _str(p, "text"), _num(p, "x"), _num(p, "y")
    if text is None or x is None or y is None:
        return
    align = p.get("align") if p.get("align") in ("left", "center", "right") else "center"
    valign = p.get("valign") if p.get("valign") in ("top", "middle", "bottom") else "middle"
    font = _font(c.text_px(_num(p, "font_size_px") or _LABEL_FONT_PX))
    spacing = c.px(3)
    measure = ImageDraw.Draw(c.image)
    left, top, right, bottom = measure.multiline_textbbox((0, 0), text, font=font, spacing=spacing, align=align)
    width, height = right - left, bottom - top
    background = _str(p, "background")
    # With a background box the text is inset by its padding, so the box —
    # not the bare glyphs — is what sits on the anchor.
    pad_x, pad_y = (c.px(6), c.px(4)) if background else (0, 0)
    box_w, box_h = width + 2 * pad_x, height + 2 * pad_y
    ax, ay = x * c.width, y * c.height
    box_left = {"left": ax, "center": ax - box_w / 2, "right": ax - box_w}[align]
    box_top = {"top": ay, "middle": ay - box_h / 2, "bottom": ay - box_h}[valign]

    layer = Image.new("RGBA", c.image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    if background:
        opacity = _num(p, "background_opacity")
        draw.rounded_rectangle(
            [box_left, box_top, box_left + box_w, box_top + box_h],
            radius=c.px(3),
            fill=_hex_to_rgba(background, _CHIP_BG, 0.55 if opacity is None else opacity),
        )
    draw.multiline_text(
        (box_left + pad_x - left, box_top + pad_y - top), text, font=font, spacing=spacing, align=align,
        fill=_hex_to_rgba(_str(p, "color"), _INK),
    )
    c.paste_layer(layer)


def _draw_custom_image(c: _Canvas, p: dict[str, Any]) -> None:
    box, asset = _box(p), _str(p, "asset")
    if box is None or asset is None:
        return
    path = _resolve_asset(c.assets_dir, Path(asset).name)
    if path is None:
        logger.debug("Overlay asset %s missing — skipping", asset)
        return
    x, y, w, h = box
    target = (max(1, round(w * c.width)), max(1, round(h * c.height)))
    with Image.open(path) as source:
        fitted = ImageOps.contain(source.convert("RGBA"), target)  # like CSS object-contain
    left = round(x * c.width) + (target[0] - fitted.width) // 2
    top = round(y * c.height) + (target[1] - fitted.height) // 2
    layer = Image.new("RGBA", c.image.size, (0, 0, 0, 0))
    layer.paste(fitted, (left, top))
    c.paste_layer(layer)


def _draw_box(c: _Canvas, p: dict[str, Any], color: tuple[int, ...], label: str | None) -> None:
    box = _box(p)
    if box is None:
        return
    x, y, w, h = box
    x0, y0 = round(x * c.width), round(y * c.height)
    x1, y1 = round((x + w) * c.width), round((y + h) * c.height)
    draw = c.draw()
    draw.rectangle([x0, y0, x1, y1], outline=color, width=c.px(2))
    if label:
        font = _font(c.text_px(10), bold=True)
        text_w = font.getlength(label)
        ascent, descent = font.getmetrics()
        tag_h = ascent + descent + c.px(2)
        tag_top = max(0, y0 - tag_h)
        draw.rectangle([x0, tag_top, x0 + text_w + c.px(8), tag_top + tag_h], fill=color)
        draw.text((x0 + c.px(4), tag_top + c.px(1)), label, font=font, fill=_VOID)


def _draw_detection_box(c: _Canvas, p: dict[str, Any]) -> None:
    _draw_box(c, p, _AMBER, _str(p, "label"))


def _draw_telescope_marker(c: _Canvas, p: dict[str, Any]) -> None:
    x, y = _num(p, "x"), _num(p, "y")
    if x is None or y is None:
        return
    cx, cy, r = x * c.width, y * c.height, c.px(6)
    layer = Image.new("RGBA", c.image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(*_AMBER[:3], 76), outline=_AMBER, width=c.px(2))
    label = _str(p, "label")
    if label:
        font = _font(c.text_px(10))
        text_w = font.getlength(label)
        ascent, descent = font.getmetrics()
        top = cy + r + c.px(2)
        half = text_w / 2 + c.px(3)
        draw.rectangle([cx - half, top, cx + half, top + ascent + descent], fill=_CHIP_BG)
        draw.text((cx - text_w / 2, top), label, font=font, fill=_AMBER_BRIGHT)
    c.paste_layer(layer)


def _draw_unknown(c: _Canvas, element: OverlayElement) -> None:
    """A plugin's own element type: a dashed-looking cyan box if its payload
    is shaped like one, otherwise nothing — never an exception."""
    if _box(element.payload) is not None:
        _draw_box(c, element.payload, _CYAN, _str(element.payload, "label") or element.type)
    else:
        logger.debug("Overlay element type %r has no renderer — skipped", element.type)


_RENDERERS = {
    "mask": _draw_mask,
    "custom_label": _draw_custom_label,
    "custom_image": _draw_custom_image,
    "detection_box": _draw_detection_box,
    "telescope_marker": _draw_telescope_marker,
}


def render_layer(
    elements: list[OverlayElement], size: tuple[int, int], assets_dir: Path | None = None
) -> Image.Image:
    """`size` is (width, height). Returns a transparent RGBA image with the
    elements drawn in list order. One element failing is logged and skipped
    rather than losing the whole overlay."""
    canvas = _Canvas(size, assets_dir)
    for element in elements:
        try:
            renderer = _RENDERERS.get(element.type)
            if renderer is None:
                _draw_unknown(canvas, element)
            else:
                renderer(canvas, element.payload)
        except Exception:
            logger.exception("Overlay element %s/%s failed to render — skipping it", element.source, element.type)
    return canvas.image


def composite(rgb: np.ndarray, layer: Image.Image) -> np.ndarray:
    """Burns `layer` into an RGB uint8 image of the same size."""
    base = Image.fromarray(rgb).convert("RGBA")
    base.alpha_composite(layer)
    return np.asarray(base.convert("RGB"))


def composite_bgr(bgr: np.ndarray, layer: Image.Image) -> np.ndarray:
    """`composite` for OpenCV's BGR arrays (timelapse frames)."""
    return composite(bgr[:, :, ::-1], layer)[:, :, ::-1].copy()


def encode_png(layer: Image.Image) -> bytes:
    buffer = io.BytesIO()
    layer.save(buffer, format="PNG", optimize=False, compress_level=6)
    return buffer.getvalue()
