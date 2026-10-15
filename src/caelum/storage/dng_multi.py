"""Multi-frame DNG: all raw frames of a capture set in one file.

Layout (see docs/dng-capture-sets.md for the full convention):

- **IFD0** is the set's *primary* (representative) raw frame, complete with
  everything a single-frame caelum DNG has — camera profile, EXIF basics,
  and the XMP packet. Software that knows nothing about capture sets opens
  it as an ordinary DNG of the primary frame.
- **SubIFDs** (tag 330) hold the other frames' raw data in set order, each
  independently decodable (own size, CFA, black/white level, compression,
  strips) plus informational per-frame EXIF (exposure, ISO, time).
- **XMP in IFD0** carries the set (`caelum:capture_set_*`) and
  `caelum:frames`, an ordered rdf:Seq with one record per frame — index,
  which IFD holds it, exposure, gains, timestamps, capture settings. That
  list is authoritative; the per-frame EXIF copies are only a convenience.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import numpy as np

from . import tiff_writer as tw
from .dng_writer import _xmp_packet, prepare_camera

#: Tags a raw SubIFD gets: image structure, and informational per-frame EXIF.
_SUBIFD_TAGS = {
    256, 257, 258, 259, 262, 274, 277, 278, 284, 339,  # structure
    33421, 33422, 50710, 50711, 50713, 50714, 50717, 50719, 50720, 50829,  # CFA, levels, crop
    33434, 34855, 36867, 37521,  # ExposureTime, ISO, DateTimeOriginal, SubsecTimeOriginal
}
_NEW_SUBFILE_TYPE = 254
_COMPRESSION = 259
_SOFTWARE = 305
_XMP = 700
_SAMPLE_FORMAT = 339
_DNG_VERSION = 50706
_DNG_BACKWARD_VERSION = 50707
_LJ92 = 7
_UNCOMPRESSED = 1


@dataclass
class MultiFrame:
    raw: np.ndarray
    raw_config: dict[str, Any]
    camera_metadata: dict[str, Any]
    captured_at: datetime
    exposure_us: int
    analogue_gain: float
    #: This frame's record in `caelum:frames` (index, exposure, ...); the
    #: writer adds `ifd`.
    xmp: dict[str, Any] = field(default_factory=dict)


def _encode(pixels: np.ndarray, width: int, height: int, bpp: int, compress: bool) -> bytes:
    """The strip for one frame, exactly as PiDNG would write it."""
    if compress:
        from ljpegCompress import pack16tolj

        return bytes(pack16tolj(pixels, int(width * 2), int(height / 2), bpp, 0, 0, 0, "", 6))
    from pidng.packing import pack10, pack12, pack14

    packers = {10: pack10, 12: pack12, 14: pack14}
    if bpp == 8:
        return pixels.astype("uint8").tobytes()
    if bpp in packers:
        return packers[bpp](pixels).tobytes()
    return pixels.tobytes()


def _entries(tags) -> list[tw.Entry]:
    entries = []
    for tag in tags.list():
        code, size = tag.DataType
        if code == 13 or tag.subIFD is not None:  # nested IFDs: not used by our profile
            continue
        entries.append(tw.Entry(tag.TagId, code, tag.DataCount, bytes(tag.Value[: tag.DataCount * size])))
    return entries


def _frame_ifd(frame: MultiFrame, *, camera_model: str, software: str, description: str, compress: bool):
    from pidng.core import PICAM2DNG

    camera = prepare_camera(
        frame.raw_config, frame.camera_metadata, captured_at=frame.captured_at, exposure_us=frame.exposure_us,
        analogue_gain=frame.analogue_gain, camera_model=camera_model, software=software, description=description,
    )
    if "PISP" in str(camera.fmt.get("format", "")):
        raise ValueError(f"Compressed raw format {camera.fmt['format']!r} is not supported")
    converter = PICAM2DNG(camera)
    converter.options(compress=compress)
    pixels = converter.__unpack_pixels__(np.ascontiguousarray(frame.raw))
    width, height = camera.fmt["size"]
    strip = _encode(pixels, width, height, int(camera.fmt["bpp"]), compress)
    entries = _entries(camera.tags)
    entries += [
        tw.longs(_NEW_SUBFILE_TYPE, [0]),
        tw.shorts(_COMPRESSION, [_LJ92 if compress else _UNCOMPRESSED]),
        tw.shorts(_SAMPLE_FORMAT, [1]),
    ]
    return entries, strip


def build_multi_dng(
    frames: list[MultiFrame],
    primary: int,
    *,
    camera_model: str = "",
    software: str = "caelum",
    description: str = "",
    xmp_fields: dict[str, Any] | None = None,
    compress: bool = True,
) -> bytes:
    """One DNG holding every frame: `frames[primary]` in IFD0, the others in
    SubIFDs in their order. Returns the file's bytes."""
    if not 0 <= primary < len(frames):
        raise ValueError("primary is not one of the frames")
    order = [primary] + [i for i in range(len(frames)) if i != primary]
    records = []
    ifd0 = None
    subifds = []
    for position, index in enumerate(order):
        frame = frames[index]
        entries, strip = _frame_ifd(frame, camera_model=camera_model, software=software,
                                    description=description if index == primary else "", compress=compress)
        ifd_name = "IFD0" if position == 0 else f"SubIFD{position - 1}"
        records.append((index, {**frame.xmp, "index": index, "ifd": ifd_name}))
        if position == 0:
            ifd0 = tw.IFD(entries=entries, strips=[strip])
        else:
            subifds.append(tw.IFD(entries=[e for e in entries if e.tag in _SUBIFD_TAGS or e.tag == _NEW_SUBFILE_TYPE],
                                  strips=[strip]))
    assert ifd0 is not None
    frames_xmp = [record for _, record in sorted(records, key=lambda r: r[0])]
    ifd0.entries = [e for e in ifd0.entries if e.tag not in (_SOFTWARE, _XMP)] + [
        tw.ascii_(_SOFTWARE, software),
        tw.Entry(_DNG_VERSION, tw.BYTE, 4, bytes([1, 4, 0, 0])),
        tw.Entry(_DNG_BACKWARD_VERSION, tw.BYTE, 4, bytes([1, 0, 0, 0])),
        tw.undefined(_XMP, _xmp_packet(xmp_fields or {}, frames_xmp)),
    ]
    ifd0.subifds = subifds
    return tw.write_tiff(ifd0)
