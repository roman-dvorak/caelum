"""Minimal reader for IFD0 of a little-endian TIFF/DNG — enough to check
the tags we write without depending on exiftool. Pillow can't open a
12-bit CFA DNG at all."""

from __future__ import annotations

import struct

_SIZES = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 7: 1, 9: 4, 10: 8, 11: 4, 12: 8}
_FMT = {1: "B", 3: "H", 4: "L", 9: "l", 11: "f", 12: "d"}


def read_ifd0(data: bytes) -> dict[int, object]:
    assert data[:4] == b"II*\x00", "not a little-endian TIFF"
    offset = struct.unpack_from("<L", data, 4)[0]
    count = struct.unpack_from("<H", data, offset)[0]
    tags: dict[int, object] = {}
    for i in range(count):
        entry = offset + 2 + 12 * i
        tag, typ, n, value = struct.unpack_from("<HHLL", data, entry)
        size = _SIZES[typ] * n
        start = entry + 8 if size <= 4 else value
        raw = data[start : start + size]
        if typ == 2:
            tags[tag] = raw.rstrip(b"\0").decode("ascii")
        elif typ == 7:
            tags[tag] = bytes(raw)
        elif typ in (5, 10):
            fmt = "<LL" if typ == 5 else "<ll"
            tags[tag] = [struct.unpack_from(fmt, raw, 8 * k) for k in range(n)]
        else:
            tags[tag] = list(struct.unpack_from(f"<{n}{_FMT[typ]}", raw))
    return tags
