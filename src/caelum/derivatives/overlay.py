"""User-defined overlay elements — masks, text labels and inserted images,
configured from the web UI's visual editor rather than written as code.

This is a *view-time* overlay: it never touches `ProcessedFrame.image`, only
contributes entries to `FrameMetadata.overlay_elements`, which is exactly
what already reaches both the local-web Dashboard (over `/ws/stream`) and
remote-web (through the sidecar JSON) — see `OverlayRenderer` on the
frontend. A "mask" here is an opaque box drawn on top wherever the image is
displayed, not pixel redaction baked into the stored JPEG/FITS; baking a
redaction into stored files would require running before the thumbnail is
encoded, on the capture thread itself (see `DerivativePool._run_modify_chain`'s
own docstring for why plugins never see the frame that early).
"""

from __future__ import annotations

import string
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from caelum.capture.frame_store import ProcessedFrame
from caelum.capture.metadata import FrameMetadata, OverlayElement
from caelum.plugins.base import Plugin

#: The fixed set of `str.format()` fields a label `template` may reference.
#: Mirrored in the frontend's overlay editor as the "insert placeholder"
#: quick-buttons — kept here as the single source of truth for what's valid.
#:
#: Beyond plain `str.format()`, templates support (see `_LabelFormatter`):
#: - a numeric divisor: `{exposure_us/1000:.1f}` (ms with one decimal);
#:   decimals come from the standard format spec, e.g. `{exposure_s:.2f}`;
#: - strftime formats for datetimes: `{captured_at:%Y-%m-%d %H:%M:%S}`.
#:   A bare `{captured_at}` keeps rendering as ISO 8601.
LABEL_PLACEHOLDERS: tuple[str, ...] = (
    "exposure_us",
    "exposure_s",
    "analogue_gain",
    "sky_state.period",
    "sky_state.sun_altitude_deg",
    "sky_state.sun_azimuth_deg",
    "sky_state.moon_altitude_deg",
    "sky_state.moon_azimuth_deg",
    "sky_state.moon_illumination",
    "focus_score",
    "captured_at",
    "captured_at_local",
)


class OverlayElementDef(BaseModel):
    id: str
    kind: Literal["mask", "label", "image"]
    #: Fractional (0..1) top-left anchor, same convention as `detection_box`.
    x: float = Field(ge=0.0, le=1.0)
    y: float = Field(ge=0.0, le=1.0)
    #: mask/image only.
    w: float | None = Field(default=None, ge=0.0, le=1.0)
    h: float | None = Field(default=None, ge=0.0, le=1.0)
    #: mask fill / label text color.
    color: str = "#000000"
    #: mask fill opacity.
    opacity: float = Field(default=1.0, ge=0.0, le=1.0)
    #: label only — a `str.format()` template, e.g. "Exp: {exposure_s:.2f}s"
    #: or "{captured_at:%d.%m.%Y %H:%M} UTC" — see `LABEL_PLACEHOLDERS`.
    template: str | None = None
    font_size_px: int | None = Field(default=None, ge=1, le=200)
    #: label only — horizontal alignment, both of the (multi-line) text and
    #: of the label against its `x` anchor: "left" puts the text's left edge
    #: at `x`, "right" its right edge, "center" (the original behaviour) its
    #: middle. Newlines in `template` render as line breaks.
    align: Literal["left", "center", "right"] = "center"
    #: image only — a filename under `data_dir/overlay_assets/`.
    asset: str | None = None


class OverlayTemplate(BaseModel):
    name: str
    elements: list[OverlayElementDef] = Field(default_factory=list)


class OverlaySettings(BaseModel):
    """A named set of templates, exactly one of which is active at a time.

    Older deployments stored a single flat `elements` list with no template
    concept — `_migrate_flat_elements` upgrades that shape into a single
    "Default" template transparently on every load/save, so an in-place
    upgrade never loses a running camera's configured overlay.
    """

    templates: list[OverlayTemplate] = Field(default_factory=lambda: [OverlayTemplate(name="Default")])
    active_template: str | None = "Default"

    @model_validator(mode="before")
    @classmethod
    def _migrate_flat_elements(cls, data: Any) -> Any:
        if isinstance(data, dict) and "elements" in data and "templates" not in data:
            data = dict(data)
            elements = data.pop("elements")
            data["templates"] = [{"name": "Default", "elements": elements}]
            data["active_template"] = "Default"
        return data

    def active_elements(self) -> list[OverlayElementDef]:
        for template in self.templates:
            if template.name == self.active_template:
                return template.elements
        return []


class _LabelFormatter(string.Formatter):
    """`str.format()` plus a `/divisor` suffix on field names and ISO 8601
    as the default rendering of datetimes (strftime when a spec is given,
    which is just `datetime.__format__`)."""

    def get_field(self, field_name: str, args: Any, kwargs: Any) -> Any:
        base, slash, divisor = field_name.partition("/")
        value, used_key = super().get_field(base, args, kwargs)
        if slash:
            value = value / float(divisor)
        return value, used_key

    def format_field(self, value: Any, format_spec: str) -> Any:
        if isinstance(value, datetime) and not format_spec:
            return value.isoformat()
        return super().format_field(value, format_spec)


_LABEL_FORMATTER = _LabelFormatter()


def _render_label_text(template: str, metadata: FrameMetadata) -> str:
    try:
        return _LABEL_FORMATTER.format(
            template,
            exposure_us=metadata.exposure_us,
            exposure_s=metadata.exposure_us / 1_000_000,
            analogue_gain=metadata.analogue_gain,
            sky_state=metadata.sky_state,
            focus_score=metadata.focus_score,
            captured_at=metadata.captured_at,
            captured_at_local=metadata.captured_at.astimezone(),
        )
    except (KeyError, AttributeError, IndexError, ValueError, TypeError, ZeroDivisionError):
        # A bad/unknown placeholder shouldn't drop the whole overlay element
        # — show the raw template so the mistake is visible and fixable
        # rather than silently missing.
        return template


class OverlayWorker(Plugin):
    """Draws whatever the admin configured in the visual overlay editor —
    shipped built-in, loaded through the same `PluginLoader` path as any
    third-party plugin, exactly like `KeogramWorker`/`MeteorDetectionWorker`."""

    id = "overlay"
    config_schema = OverlaySettings

    def __init__(self, settings: dict[str, Any] | None = None) -> None:
        super().__init__(settings or {})
        self._settings = OverlaySettings.model_validate(self.settings)

    def provide_overlay_elements(self, frame: ProcessedFrame) -> list[OverlayElement]:
        elements: list[OverlayElement] = []
        for definition in self._settings.active_elements():
            element = self._build_element(definition, frame)
            if element is not None:
                elements.append(element)
        return elements

    def _build_element(self, definition: OverlayElementDef, frame: ProcessedFrame) -> OverlayElement | None:
        if definition.kind == "mask":
            if definition.w is None or definition.h is None:
                return None
            return OverlayElement(
                type="mask",
                source=self.id,
                payload={
                    "x": definition.x,
                    "y": definition.y,
                    "w": definition.w,
                    "h": definition.h,
                    "color": definition.color,
                    "opacity": definition.opacity,
                },
            )
        if definition.kind == "label":
            if not definition.template:
                return None
            return OverlayElement(
                type="custom_label",
                source=self.id,
                payload={
                    "x": definition.x,
                    "y": definition.y,
                    "text": _render_label_text(definition.template, frame.metadata),
                    "color": definition.color,
                    "font_size_px": definition.font_size_px,
                    "align": definition.align,
                },
            )
        if definition.kind == "image":
            if definition.w is None or definition.h is None or not definition.asset:
                return None
            return OverlayElement(
                type="custom_image",
                source=self.id,
                payload={
                    "x": definition.x,
                    "y": definition.y,
                    "w": definition.w,
                    "h": definition.h,
                    "asset": definition.asset,
                },
            )
        return None
