"""User-defined overlay elements — masks, text labels and inserted images,
configured from the web UI's visual editor rather than written as code.

The worker only contributes entries to the frame's overlay element list;
`DerivativePool` collects them together with every other plugin's and the
system elements, renders them once with `overlay_render.render_layer`, and
stores the result next to the thumbnail (or burned into it) and in the
sidecar JSON — so the live view, the local history and remote-web all show
the same pixels. A "mask" is therefore an opaque box on the overlay layer;
with `storage_policy.overlay_mode = "burn"` it ends up in the stored WebP,
otherwise the clean thumbnail stays underneath.
"""

from __future__ import annotations

import string
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from caelum.capture.frame_store import ProcessedFrame
from caelum.capture.metadata import FrameMetadata, OverlayElement
from caelum.derivatives.overlay_render import format_exposure
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
#:
#: `exposure` is the exposure already formatted for people ("15.00s",
#: "2.5ms"); `software`, `camera_model` and `camera_name` come from the
#: frame's provenance (empty for frames recorded without it).
LABEL_PLACEHOLDERS: tuple[str, ...] = (
    "exposure",
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
    "camera_name",
    "camera_model",
    "software",
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
    #: label only — which edge of the text block sits on `y`: "top",
    #: "middle" (the original behaviour) or "bottom" — what lets a label sit
    #: in a corner however many lines it has.
    valign: Literal["top", "middle", "bottom"] = "middle"
    #: label only — a box behind the text (e.g. "#000000"), None for none;
    #: keeps it legible on a bright sky.
    background: str | None = None
    background_opacity: float = Field(default=0.55, ge=0.0, le=1.0)
    #: image only — a filename under `data_dir/overlay_assets/`.
    asset: str | None = None


class OverlayTemplate(BaseModel):
    name: str
    elements: list[OverlayElementDef] = Field(default_factory=list)


#: Shipped in `overlay_render.BUILTIN_ASSETS_DIR`; an upload of the same
#: name in `data_dir/overlay_assets/` takes precedence.
ASTROMETERS_LOGO = "astrometers-logo.png"

_CORNER_LABEL = {"color": "#f0f0f0", "font_size_px": 15, "background": "#000000", "background_opacity": 0.5}


def default_template() -> OverlayTemplate:
    """The overlay a new camera starts with: capture time (UTC), exposure
    and gain top left; camera/observatory name top right; the AstroMeters
    logo and the capture software bottom left; the camera model bottom
    right. An ordinary template — editable, replaceable, removable."""
    margin_x, margin_y = 0.012, 0.016
    elements = [
        OverlayElementDef(
            id="time", kind="label", x=margin_x, y=margin_y, align="left", valign="top",
            template="{captured_at:%Y-%m-%d %H:%M:%S} UTC\nExp {exposure}  Gain {analogue_gain:.1f}×",
            **_CORNER_LABEL,
        ),
        OverlayElementDef(
            id="station", kind="label", x=1 - margin_x, y=margin_y, align="right", valign="top",
            template="{camera_name}", **_CORNER_LABEL,
        ),
        OverlayElementDef(
            id="logo", kind="image", x=margin_x, y=0.87, w=0.09, h=0.115, asset=ASTROMETERS_LOGO,
        ),
        OverlayElementDef(
            id="software", kind="label", x=0.105, y=1 - margin_y, align="left", valign="bottom",
            template="{software}", **_CORNER_LABEL,
        ),
        OverlayElementDef(
            id="camera", kind="label", x=1 - margin_x, y=1 - margin_y, align="right", valign="bottom",
            template="{camera_model}", **_CORNER_LABEL,
        ),
    ]
    return OverlayTemplate(name="Default", elements=elements)


def _is_untouched_old_default(data: dict[str, Any]) -> bool:
    templates = data.get("templates")
    return (
        isinstance(templates, list)
        and len(templates) == 1
        and isinstance(templates[0], dict)
        and templates[0].get("name") == "Default"
        and not templates[0].get("elements")
    )


class OverlaySettings(BaseModel):
    """A named set of templates, exactly one of which is active at a time.

    Older deployments stored a single flat `elements` list with no template
    concept — `_migrate_flat_elements` upgrades that shape into a single
    "Default" template transparently on every load/save, so an in-place
    upgrade never loses a running camera's configured overlay.
    """

    templates: list[OverlayTemplate] = Field(default_factory=lambda: [default_template()])
    active_template: str | None = "Default"

    @model_validator(mode="before")
    @classmethod
    def _migrate_flat_elements(cls, data: Any) -> Any:
        if isinstance(data, dict) and "elements" in data and "templates" not in data:
            data = dict(data)
            elements = data.pop("elements")
            data["templates"] = [{"name": "Default", "elements": elements}]
            data["active_template"] = "Default"
        # What older releases shipped (one empty "Default") was never a
        # choice anyone made — give it the real default overlay.
        if isinstance(data, dict) and _is_untouched_old_default(data):
            data = {**data, "templates": [default_template().model_dump()]}
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
    provenance = metadata.provenance or {}
    version = provenance.get("caelum_version")
    try:
        return _LABEL_FORMATTER.format(
            template,
            exposure=format_exposure(metadata.exposure_us),
            exposure_us=metadata.exposure_us,
            exposure_s=metadata.exposure_us / 1_000_000,
            analogue_gain=metadata.analogue_gain,
            sky_state=metadata.sky_state,
            focus_score=metadata.focus_score,
            captured_at=metadata.captured_at,
            captured_at_local=metadata.captured_at.astimezone(),
            camera_name=provenance.get("camera_name") or "",
            camera_model=provenance.get("camera_model") or provenance.get("camera_backend") or "",
            software=f"caelum {version}" if version else "caelum",
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
        return build_elements(self._settings.active_elements(), frame.metadata, self.id)


def build_elements(
    definitions: list[OverlayElementDef], metadata: FrameMetadata, source: str = "overlay"
) -> list[OverlayElement]:
    """The editor's element definitions as one frame's `OverlayElement`s —
    label templates filled in from `metadata`, incomplete definitions
    dropped. Shared by the live worker and the timelapse burn-in."""
    elements = []
    for definition in definitions:
        element = _build_element(definition, metadata, source)
        if element is not None:
            elements.append(element)
    return elements


def _build_element(definition: OverlayElementDef, metadata: FrameMetadata, source: str) -> OverlayElement | None:
    if definition.kind == "mask":
        if definition.w is None or definition.h is None:
            return None
        return OverlayElement(
            type="mask",
            source=source,
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
            source=source,
            payload={
                "x": definition.x,
                "y": definition.y,
                "text": _render_label_text(definition.template, metadata),
                "color": definition.color,
                "font_size_px": definition.font_size_px,
                "align": definition.align,
                "valign": definition.valign,
                "background": definition.background,
                "background_opacity": definition.background_opacity,
            },
        )
    if definition.kind == "image":
        if definition.w is None or definition.h is None or not definition.asset:
            return None
        return OverlayElement(
            type="custom_image",
            source=source,
            payload={
                "x": definition.x,
                "y": definition.y,
                "w": definition.w,
                "h": definition.h,
                "asset": definition.asset,
            },
        )
    return None
