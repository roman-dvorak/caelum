"""Minimal little-endian TIFF writer: one IFD0 with any number of SubIFDs
(tag 330), each with its own image strips.

PiDNG can only nest a single SubIFD, which is why the multi-frame DNG
(`dng_multi.py`) uses this instead. Entries carry their value already
packed (as PiDNG's `dngTag.Value` does), so tag sets built with PiDNG can
be reused as they are. StripOffsets (273), StripByteCounts (279) and
SubIFDs (330) are filled in from the layout — don't pass them.

Layout: header, IFD0 (+ its out-of-line values), each SubIFD (+ values),
then all strips — every offset 4-byte aligned.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

BYTE, ASCII, SHORT, LONG, RATIONAL, UNDEFINED, SRATIONAL, FLOAT, DOUBLE = 1, 2, 3, 4, 5, 7, 10, 11, 12
TYPE_SIZE = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 6: 1, 7: 1, 8: 2, 9: 4, 10: 8, 11: 4, 12: 8, 13: 4}

STRIP_OFFSETS = 273
STRIP_BYTE_COUNTS = 279
SUB_IFDS = 330
_COMPUTED = {STRIP_OFFSETS, STRIP_BYTE_COUNTS, SUB_IFDS}


@dataclass(frozen=True)
class Entry:
    tag: int
    type: int
    count: int
    value: bytes  # exactly count * TYPE_SIZE[type] bytes

    def __post_init__(self) -> None:
        expected = self.count * TYPE_SIZE[self.type]
        if len(self.value) != expected:
            raise ValueError(f"tag {self.tag}: {len(self.value)} value bytes, expected {expected}")


def longs(tag: int, values: list[int]) -> Entry:
    return Entry(tag, LONG, len(values), struct.pack(f"<{len(values)}L", *values))


def shorts(tag: int, values: list[int]) -> Entry:
    return Entry(tag, SHORT, len(values), struct.pack(f"<{len(values)}H", *values))


def ascii_(tag: int, text: str) -> Entry:
    data = text.encode("ascii", "replace") + b"\0"
    return Entry(tag, ASCII, len(data), data)


def undefined(tag: int, data: bytes) -> Entry:
    return Entry(tag, UNDEFINED, len(data), bytes(data))


def rationals(tag: int, values: list[tuple[int, int]]) -> Entry:
    flat = [x for pair in values for x in pair]
    return Entry(tag, RATIONAL, len(values), struct.pack(f"<{len(flat)}L", *flat))


@dataclass
class IFD:
    entries: list[Entry]
    strips: list[bytes] = field(default_factory=list)
    subifds: list[IFD] = field(default_factory=list)


def _align(n: int) -> int:
    return (n + 3) & ~3


def _final_entries(ifd: IFD) -> list[Entry]:
    entries = {e.tag: e for e in ifd.entries if e.tag not in _COMPUTED}
    if ifd.strips:
        entries[STRIP_OFFSETS] = longs(STRIP_OFFSETS, [0] * len(ifd.strips))
        entries[STRIP_BYTE_COUNTS] = longs(STRIP_BYTE_COUNTS, [len(s) for s in ifd.strips])
    if ifd.subifds:
        entries[SUB_IFDS] = Entry(SUB_IFDS, LONG, len(ifd.subifds), b"\0" * 4 * len(ifd.subifds))
    return [entries[tag] for tag in sorted(entries)]


def _ifd_size(entries: list[Entry]) -> int:
    size = 2 + 12 * len(entries) + 4
    return size + sum(_align(len(e.value)) for e in entries if len(e.value) > 4)


def write_tiff(ifd0: IFD) -> bytes:
    if any(sub.subifds for sub in ifd0.subifds):
        raise ValueError("only one level of SubIFDs is supported")
    ifds = [ifd0, *ifd0.subifds]
    finals = [_final_entries(ifd) for ifd in ifds]

    # Pass 1: layout.
    offset = 8
    ifd_offsets = []
    for entries in finals:
        ifd_offsets.append(offset)
        offset = _align(offset + _ifd_size(entries))
    strip_offsets: list[list[int]] = []
    for ifd in ifds:
        here = []
        for strip in ifd.strips:
            here.append(offset)
            offset = _align(offset + len(strip))
        strip_offsets.append(here)
    total = offset

    # Pass 2: write.
    buf = bytearray(total)
    struct.pack_into("<2sHI", buf, 0, b"II", 42, ifd_offsets[0])
    for index, (ifd, entries) in enumerate(zip(ifds, finals, strict=True)):
        computed = {}
        if ifd.strips:
            computed[STRIP_OFFSETS] = struct.pack(f"<{len(ifd.strips)}L", *strip_offsets[index])
        if index == 0 and ifd.subifds:
            computed[SUB_IFDS] = struct.pack(f"<{len(ifd.subifds)}L", *ifd_offsets[1:])
        base = ifd_offsets[index]
        struct.pack_into("<H", buf, base, len(entries))
        data_at = base + 2 + 12 * len(entries) + 4
        for i, entry in enumerate(entries):
            value = computed.get(entry.tag, entry.value)
            at = base + 2 + 12 * i
            if len(value) <= 4:
                struct.pack_into("<HHI4s", buf, at, entry.tag, entry.type, entry.count, value.ljust(4, b"\0"))
            else:
                struct.pack_into("<HHII", buf, at, entry.tag, entry.type, entry.count, data_at)
                buf[data_at:data_at + len(value)] = value
                data_at += _align(len(value))
        struct.pack_into("<I", buf, base + 2 + 12 * len(entries), 0)  # no next IFD
        for strip, at in zip(ifd.strips, strip_offsets[index], strict=True):
            buf[at:at + len(strip)] = strip
    return bytes(buf)
