"""DNG writer for the sensor's raw Bayer data.

Builds on PiDNG's `Picamera2Camera` profile (the same one picamera2's own
`save_dng` uses — black levels, colour matrix and as-shot neutral from the
frame's metadata), and then adds what that leaves out or gets wrong:

- `ExposureTime` as a proper rational: PiDNG writes 1/int(1/t), which is
  1/0 for any exposure of a second or longer — i.e. every night frame;
- capture time (`DateTime`, `DateTimeOriginal`, `SubsecTimeOriginal`, UTC);
- `Make`/`Model`/`UniqueCameraModel`, `Software`, a short
  `ImageDescription`;
- an XMP packet in a `caelum:` namespace with everything else known about
  the frame: sky period, sun/moon position, moon illumination, site
  location, exposure/gains, the exposure loop's brightness measurement.

PiDNG ships as a system package on Raspberry Pi OS (`python3-pidng`), seen
through the venv's system site-packages, so it is imported lazily.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

import numpy as np

_XMP_NS = "https://caelum.astrometers.eu/ns/1.0/"


def _ascii(text: str) -> str:
    """TIFF ASCII tags are 7-bit only — PiDNG raises on anything else."""
    return text.encode("ascii", "replace").decode("ascii")


def _xmp_attrs(fields: dict[str, Any], indent: str) -> str:
    return "\n".join(
        f'{indent}caelum:{key}="{escape(str(value), {chr(34): "&quot;"})}"'
        for key, value in fields.items()
        if value is not None
    )


def _xmp_packet(fields: dict[str, Any], frames: list[dict[str, Any]] | None = None) -> bytes:
    """`frames`: one record per frame of a multi-frame DNG, written as the
    ordered list `caelum:frames` (rdf:Seq of structs) — see
    docs/dng-capture-sets.md."""
    head = f'  <rdf:Description rdf:about="" xmlns:caelum="{_XMP_NS}"\n{_xmp_attrs(fields, "    ")}'
    if frames:
        items = "\n".join(
            f"      <rdf:li>\n       <rdf:Description\n{_xmp_attrs(frame, '        ')}/>\n      </rdf:li>"
            for frame in frames
        )
        body = (
            f"{head}>\n    <caelum:frames>\n     <rdf:Seq>\n{items}\n     </rdf:Seq>\n"
            "    </caelum:frames>\n  </rdf:Description>\n"
        )
    else:
        body = f"{head}/>\n"
    xml = (
        '<?xpacket begin="﻿" id="W5M0MpCehiHzreSzNTczkc9d"?>\n'
        '<x:xmpmeta xmlns:x="adobe:ns:meta/">\n'
        ' <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">\n'
        f"{body}"
        " </rdf:RDF>\n"
        "</x:xmpmeta>\n"
        '<?xpacket end="w"?>'
    )
    return xml.encode("utf-8")


def _camera_metadata_defaults(meta: dict[str, Any], exposure_us: int, analogue_gain: float) -> dict[str, Any]:
    """PiDNG's profile reads these keys unconditionally."""
    meta = dict(meta)
    meta["ExposureTime"] = max(int(meta.get("ExposureTime") or exposure_us or 1), 1)
    meta["AnalogueGain"] = float(meta.get("AnalogueGain") or analogue_gain or 1.0)
    meta.setdefault("DigitalGain", 1.0)
    meta.setdefault("SensorTimestamp", 0)
    meta.setdefault("SensorBlackLevels", [4096, 4096, 4096, 4096])
    meta.setdefault("ColourGains", [1.0, 1.0])
    meta.setdefault("ColourCorrectionMatrix", [1, 0, 0, 0, 1, 0, 0, 0, 1])
    return meta


def build_dng(
    raw: np.ndarray,
    raw_config: dict[str, Any],
    camera_metadata: dict[str, Any],
    *,
    captured_at: datetime,
    exposure_us: int,
    analogue_gain: float,
    camera_model: str = "",
    software: str = "caelum",
    description: str = "",
    xmp_fields: dict[str, Any] | None = None,
    compress: bool = True,
) -> bytes:
    """`compress`: lossless JPEG (LJ92), the standard DNG compression every
    raw developer reads — about a third smaller for night frames, ~0.5 s of
    CPU per full-size frame on a Pi 4."""
    from pidng.core import PICAM2DNG
    from pidng.dng import Tag

    camera = prepare_camera(
        raw_config, camera_metadata, captured_at=captured_at, exposure_us=exposure_us,
        analogue_gain=analogue_gain, camera_model=camera_model, software=software, description=description,
    )
    if xmp_fields:
        camera.tags.set(Tag.XMP_Metadata, list(_xmp_packet(xmp_fields)))
    converter = PICAM2DNG(camera)
    converter.options(compress=compress)
    return bytes(converter.convert(np.ascontiguousarray(raw), ""))


def prepare_camera(
    raw_config: dict[str, Any],
    camera_metadata: dict[str, Any],
    *,
    captured_at: datetime,
    exposure_us: int,
    analogue_gain: float,
    camera_model: str = "",
    software: str = "caelum",
    description: str = "",
):
    """PiDNG's camera profile for one frame, with caelum's corrections and
    additions (see the module docstring) — its `.tags` are the frame's DNG
    tags, its `.fmt` the raw layout."""
    from pidng.camdefs import Picamera2Camera
    from pidng.dng import Tag

    fmt = {
        "format": str(raw_config.get("format", "")),
        "size": tuple(raw_config.get("size", (0, 0))),
        "stride": int(raw_config.get("stride", 0)),
    }
    if "PISP" in fmt["format"]:
        # Pi 5 compressed raw — would need picamera2's decompress step first.
        raise ValueError(f"Compressed raw format {fmt['format']!r} is not supported")

    meta = _camera_metadata_defaults(camera_metadata, exposure_us, analogue_gain)
    model = camera_model or "Raspberry Pi camera"
    camera = Picamera2Camera(fmt, meta, model)

    when = captured_at.astimezone(UTC)
    stamp = when.strftime("%Y:%m:%d %H:%M:%S")
    tags = camera.tags
    tags.set(Tag.ExposureTime, [[int(meta["ExposureTime"]), 1_000_000]])
    tags.set(Tag.DateTime, stamp)
    tags.set(Tag.DateTimeOriginal, stamp)
    tags.set(Tag.SubsecTimeOriginal, f"{when.microsecond // 1000:03d}")
    tags.set(Tag.Make, "Raspberry Pi")
    tags.set(Tag.Model, _ascii(model))
    tags.set(Tag.UniqueCameraModel, _ascii(f"Raspberry Pi {model}"))
    tags.set(Tag.Software, _ascii(software))
    if description:
        tags.set(Tag.ImageDescription, _ascii(description))
    return camera


def write(path: Path, data: bytes) -> None:
    """Atomic: readers (the uploader, the files API) never see a partial DNG."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)
