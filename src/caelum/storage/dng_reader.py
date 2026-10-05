"""Reading our own DNGs back, and re-tagging their white balance in place.

Covers exactly what `dng_writer` (PiDNG) and `dng_multi` produce — a
little-endian TIFF with the raw CFA image in IFD0 (and, for a capture set,
further frames in SubIFDs), uncompressed 12-bit packed / 16-bit or LJ92 —
not DNG in general. Pillow can't open a 12-bit CFA DNG at all, and nothing else
in the dependency tree reads them.

White balance lives in `AsShotNeutral` (tag 50728): one value per colour
plane, the camera-space RGB of a neutral grey — i.e. the reciprocals of the
white-balance gains, `[1/r, 1, 1/b]`. It is the form every raw converter
reads (the alternative, `AsShotWhiteXY`, is far less supported). Changing
it never touches the pixel data, which is what makes a white-balance edit
on a DNG non-destructive: `set_as_shot_neutral` patches those 24 bytes and
nothing else.
"""

from __future__ import annotations

import os
import re
import struct
from dataclasses import dataclass
from pathlib import Path

import numpy as np

_TAG_IMAGE_WIDTH = 256
_TAG_IMAGE_LENGTH = 257
_TAG_BITS_PER_SAMPLE = 258
_TAG_COMPRESSION = 259
_TAG_STRIP_OFFSETS = 273
_TAG_STRIP_BYTE_COUNTS = 279
_TAG_XMP = 700
_TAG_CFA_REPEAT_PATTERN_DIM = 33421
_TAG_CFA_PATTERN = 33422
_TAG_BLACK_LEVEL = 50714
_TAG_WHITE_LEVEL = 50717
_TAG_COLOR_MATRIX_1 = 50721
_TAG_AS_SHOT_NEUTRAL = 50728

_TYPE_RATIONAL = 5
_SIZES = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 7: 1, 8: 2, 9: 4, 10: 8, 11: 4, 12: 8}
_FMT = {1: "B", 3: "H", 4: "L", 8: "h", 9: "l", 11: "f", 12: "d"}

#: Linear sRGB (D65) -> XYZ.
_SRGB_TO_XYZ = np.array(
    [
        [0.4124564, 0.3575761, 0.1804375],
        [0.2126729, 0.7151522, 0.0721750],
        [0.0193339, 0.1191920, 0.9503041],
    ]
)

_NEUTRAL_DENOMINATOR = 1_000_000
_XMP_COLOUR_GAINS_RE = re.compile(rb'caelum:colour_gains="([0-9.eE+-]+),([0-9.eE+-]+)"')


class DngFormatError(ValueError):
    """Not a DNG this module can read (or patch)."""


@dataclass(frozen=True)
class _Entry:
    typ: int
    count: int
    #: Byte offset of the value itself — inside the IFD entry when it fits
    #: in 4 bytes, elsewhere in the file otherwise.
    value_offset: int


@dataclass(frozen=True)
class DngInfo:
    width: int
    height: int
    bits_per_sample: int
    #: 2x2 CFA as colour indices (0 = R, 1 = G, 2 = B), row-major.
    cfa: tuple[int, int, int, int]
    #: Per CFA position, row-major, same as `cfa`.
    black_levels: tuple[float, float, float, float]
    white_level: float
    as_shot_neutral: tuple[float, float, float] | None
    #: XYZ -> camera, row-major 3x3.
    color_matrix: tuple[float, ...] | None
    #: The camera's white-balance gains at capture time (`caelum:colour_gains`
    #: in the XMP packet) — what `as_shot_neutral` was before any edit.
    captured_gains: tuple[float, float] | None
    strips: tuple[tuple[int, int], ...]
    compression: int = 1

    @property
    def gains(self) -> tuple[float, float] | None:
        """`as_shot_neutral` as (red, blue) gains, normalized to green."""
        if self.as_shot_neutral is None:
            return None
        r, g, b = self.as_shot_neutral
        if r <= 0 or b <= 0:
            return None
        return g / r, g / b


def _ifd0(data: bytes) -> dict[int, _Entry]:
    if data[:4] != b"II*\x00":
        raise DngFormatError("Not a little-endian TIFF/DNG")
    offset = struct.unpack_from("<L", data, 4)[0]
    if offset + 2 > len(data):
        raise DngFormatError("IFD0 offset past end of file")
    count = struct.unpack_from("<H", data, offset)[0]
    entries: dict[int, _Entry] = {}
    for i in range(count):
        pos = offset + 2 + 12 * i
        tag, typ, n, value = struct.unpack_from("<HHLL", data, pos)
        if typ not in _SIZES:
            continue
        size = _SIZES[typ] * n
        entries[tag] = _Entry(typ, n, pos + 8 if size <= 4 else value)
    return entries


def _values(data: bytes, entry: _Entry) -> list:
    if entry.typ == 2:
        return [data[entry.value_offset : entry.value_offset + entry.count].rstrip(b"\0").decode("ascii", "replace")]
    if entry.typ == 7:
        return [bytes(data[entry.value_offset : entry.value_offset + entry.count])]
    if entry.typ in (5, 10):
        fmt = "<LL" if entry.typ == 5 else "<ll"
        pairs = [struct.unpack_from(fmt, data, entry.value_offset + 8 * k) for k in range(entry.count)]
        return [num / den if den else 0.0 for num, den in pairs]
    return list(struct.unpack_from(f"<{entry.count}{_FMT[entry.typ]}", data, entry.value_offset))


def _get(data: bytes, entries: dict[int, _Entry], tag: int) -> list | None:
    entry = entries.get(tag)
    return _values(data, entry) if entry is not None else None


def parse(data: bytes) -> DngInfo:
    entries = _ifd0(data)

    def required(tag: int) -> list:
        values = _get(data, entries, tag)
        if not values:
            raise DngFormatError(f"Missing TIFF tag {tag}")
        return values

    compression = int(required(_TAG_COMPRESSION)[0])
    if compression not in (1, 7):  # 7 = lossless JPEG (LJ92), what caelum writes by default
        raise DngFormatError(f"Unsupported DNG compression {compression}")
    bits = int(required(_TAG_BITS_PER_SAMPLE)[0])
    if bits not in (12, 16):
        raise DngFormatError(f"Unsupported BitsPerSample {bits}")
    if list(_get(data, entries, _TAG_CFA_REPEAT_PATTERN_DIM) or [2, 2]) != [2, 2]:
        raise DngFormatError("Only a 2x2 CFA is supported")
    cfa = required(_TAG_CFA_PATTERN)
    if len(cfa) != 4 or sorted(cfa) != [0, 1, 1, 2]:
        raise DngFormatError(f"Unsupported CFA pattern {cfa}")

    black = [float(v) for v in (_get(data, entries, _TAG_BLACK_LEVEL) or [0.0])]
    if len(black) == 1:
        black *= 4
    neutral = _get(data, entries, _TAG_AS_SHOT_NEUTRAL)
    matrix = _get(data, entries, _TAG_COLOR_MATRIX_1)
    xmp = _get(data, entries, _TAG_XMP)
    captured = None
    if xmp:
        match = _XMP_COLOUR_GAINS_RE.search(bytes(xmp[0]) if isinstance(xmp[0], bytes) else bytes(xmp))
        if match:
            captured = (float(match.group(1)), float(match.group(2)))

    offsets = required(_TAG_STRIP_OFFSETS)
    counts = required(_TAG_STRIP_BYTE_COUNTS)
    return DngInfo(
        width=int(required(_TAG_IMAGE_WIDTH)[0]),
        height=int(required(_TAG_IMAGE_LENGTH)[0]),
        bits_per_sample=bits,
        cfa=tuple(int(c) for c in cfa),  # type: ignore[arg-type]
        black_levels=tuple(black[:4]),  # type: ignore[arg-type]
        white_level=float(required(_TAG_WHITE_LEVEL)[0]),
        as_shot_neutral=tuple(float(v) for v in neutral) if neutral and len(neutral) == 3 else None,  # type: ignore[arg-type]
        color_matrix=tuple(float(v) for v in matrix) if matrix and len(matrix) == 9 else None,
        captured_gains=captured,
        strips=tuple(zip((int(o) for o in offsets), (int(c) for c in counts), strict=True)),
        compression=compression,
    )


_TAG_NEW_SUBFILE_TYPE = 254
_TAG_SUB_IFDS = 330


def _raw_entries(data: bytes, offset: int) -> dict[int, tuple[int, int, bytes]]:
    """Every entry of the IFD at `offset` as (type, count, value bytes)."""
    count = struct.unpack_from("<H", data, offset)[0]
    entries = {}
    for i in range(count):
        pos = offset + 2 + 12 * i
        tag, typ, n, value = struct.unpack_from("<HHLL", data, pos)
        size = _SIZES.get(typ, 4 if typ == 13 else 0) * n
        start = pos + 8 if size <= 4 else value
        entries[tag] = (typ, n, bytes(data[start:start + size]))
    return entries


def list_raw_ifds(data: bytes) -> list[int]:
    """Offsets of the raw frames in file order: IFD0 first, then its
    SubIFDs (the frames of a multi-frame DNG, see docs/dng-capture-sets.md).
    A single-frame DNG has just IFD0."""
    if data[:4] != b"II*\x00":
        raise DngFormatError("Not a little-endian TIFF/DNG")
    ifd0 = struct.unpack_from("<L", data, 4)[0]
    offsets = [ifd0]
    sub = _raw_entries(data, ifd0).get(_TAG_SUB_IFDS)
    if sub is not None:
        offsets += list(struct.unpack(f"<{sub[1]}L", sub[2]))
    return offsets


def standalone_frame(data: bytes, index: int) -> bytes:
    """Frame `index` (in `list_raw_ifds` order) of a multi-frame DNG as a
    single-frame DNG: the IFD0 profile with that frame's raw structure,
    per-frame tags and pixel data."""
    from . import tiff_writer as tw

    offsets = list_raw_ifds(data)
    if not 0 <= index < len(offsets):
        raise DngFormatError(f"no raw frame {index} (file has {len(offsets)})")

    def entries_of(offset: int) -> dict[int, tw.Entry]:
        return {
            tag: tw.Entry(tag, typ, n, value)
            for tag, (typ, n, value) in _raw_entries(data, offset).items()
            if typ in tw.TYPE_SIZE and typ != 13 and tag not in (_TAG_SUB_IFDS, 34665)
        }

    merged = entries_of(offsets[0])
    frame = _raw_entries(data, offsets[index])
    merged.update(entries_of(offsets[index]))
    strip_offsets = struct.unpack(f"<{frame[_TAG_STRIP_OFFSETS][1]}L", _widen(frame[_TAG_STRIP_OFFSETS]))
    strip_counts = struct.unpack(f"<{frame[_TAG_STRIP_BYTE_COUNTS][1]}L", _widen(frame[_TAG_STRIP_BYTE_COUNTS]))
    strips = [bytes(data[o:o + n]) for o, n in zip(strip_offsets, strip_counts, strict=True)]
    return tw.write_tiff(tw.IFD(entries=list(merged.values()), strips=strips))


def _widen(entry: tuple[int, int, bytes]) -> bytes:
    typ, n, value = entry
    if typ == 3:  # SHORT offsets/counts
        return struct.pack(f"<{n}L", *struct.unpack(f"<{n}H", value))
    return value


def read_info(path: Path) -> DngInfo:
    return parse(path.read_bytes())


def bayer(data: bytes, info: DngInfo) -> np.ndarray:
    """The raw CFA image as `uint16`, (height, width)."""
    if info.compression == 7:
        # Lossless JPEG: decoded by LibRaw (pidng's own decoder doesn't build
        # on Python 3). Bit-identical to the samples that were written.
        import io

        import rawpy

        with rawpy.imread(io.BytesIO(data)) as raw_file:
            return np.array(raw_file.raw_image_visible, dtype=np.uint16, copy=True)
    raw = np.concatenate([np.frombuffer(data, dtype=np.uint8, count=n, offset=o) for o, n in info.strips])
    if info.bits_per_sample == 16:
        return raw.view("<u2")[: info.width * info.height].reshape(info.height, info.width)
    # TIFF packs 12-bit samples MSB first: two pixels in three bytes.
    row_bytes = (info.width * 12 + 7) // 8
    packed = raw[: row_bytes * info.height].reshape(info.height, row_bytes).astype(np.uint16)
    out = np.empty((info.height, (row_bytes // 3) * 2), dtype=np.uint16)
    out[:, 0::2] = (packed[:, 0::3] << 4) | (packed[:, 1::3] >> 4)
    out[:, 1::2] = ((packed[:, 1::3] & 0x0F) << 8) | packed[:, 2::3]
    return out[:, : info.width]


def linear_rgb(data: bytes, info: DngInfo, max_dim: int) -> np.ndarray:
    """Camera-space linear RGB, black-subtracted and scaled so the white
    level is 1.0 — no white balance, no colour matrix. One pixel per 2x2
    CFA cell (no interpolation: plenty for a downscaled preview), then
    box-averaged down until it fits `max_dim`. `float32`, (h, w, 3)."""
    cfa = bayer(data, info)
    h2, w2 = info.height // 2, info.width // 2
    rgb = np.zeros((h2, w2, 3), dtype=np.float32)
    weight = np.zeros(3, dtype=np.float32)
    for index, colour in enumerate(info.cfa):
        dy, dx = divmod(index, 2)
        plane = cfa[dy : 2 * h2 : 2, dx : 2 * w2 : 2].astype(np.float32)
        plane -= info.black_levels[index]
        plane /= max(info.white_level - info.black_levels[index], 1.0)
        rgb[..., colour] += plane
        weight[colour] += 1.0
    rgb /= weight

    factor = max(1, -(-max(h2, w2) // max_dim))
    if factor > 1:
        h, w = h2 // factor, w2 // factor
        rgb = rgb[: h * factor, : w * factor].reshape(h, factor, w, factor, 3).mean(axis=(1, 3))
    return np.clip(rgb, 0.0, 1.0)


def render_matrix(info: DngInfo) -> list[list[float]]:
    """White-balanced camera RGB -> linear sRGB, dcraw-style: the colour
    matrix composed with sRGB->XYZ, rows normalized so a neutral maps to
    equal RGB (white balance is applied separately, as gains), inverted.

    Independent of `as_shot_neutral`, so it stays right after a white
    balance edit. For PiDNG's profile it works out to exactly the ISP's
    colour correction matrix."""
    if info.color_matrix is None:
        return np.eye(3).tolist()
    cam_rgb = np.array(info.color_matrix).reshape(3, 3) @ _SRGB_TO_XYZ
    sums = cam_rgb.sum(axis=1, keepdims=True)
    if np.any(np.abs(sums) < 1e-9):
        return np.eye(3).tolist()
    try:
        return np.linalg.inv(cam_rgb / sums).tolist()
    except np.linalg.LinAlgError:
        return np.eye(3).tolist()


def set_as_shot_neutral(path: Path, red_gain: float, blue_gain: float) -> DngInfo:
    """Rewrite the file's `AsShotNeutral` to `[1/red, 1, 1/blue]`, leaving
    every other byte as it was. Atomic, like `dng_writer.write`."""
    if not (red_gain > 0 and blue_gain > 0):
        raise ValueError("Gains must be positive")
    data = bytearray(path.read_bytes())
    entry = _ifd0(bytes(data)).get(_TAG_AS_SHOT_NEUTRAL)
    if entry is None or entry.typ != _TYPE_RATIONAL or entry.count != 3:
        # Adding a tag would mean rebuilding the IFD — not worth it for files
        # we didn't write.
        raise DngFormatError("File has no 3-value AsShotNeutral tag to update")

    for k, value in enumerate((1.0 / red_gain, 1.0, 1.0 / blue_gain)):
        struct.pack_into(
            "<LL", data, entry.value_offset + 8 * k, round(value * _NEUTRAL_DENOMINATOR), _NEUTRAL_DENOMINATOR
        )

    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)
    return parse(bytes(data))
