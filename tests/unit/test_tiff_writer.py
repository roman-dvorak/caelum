from __future__ import annotations

import struct

import pytest

from caelum.storage import tiff_writer as tw
from caelum.storage.dng_reader import _raw_entries, list_raw_ifds


def test_ifd0_with_subifds_and_strips_round_trips():
    sub = [tw.IFD(entries=[tw.longs(256, [i + 1]), tw.ascii_(270, f"frame {i}")], strips=[bytes([i]) * (10 + i)])
           for i in range(3)]
    ifd0 = tw.IFD(entries=[tw.longs(256, [99]), tw.rationals(33434, [(1, 30)])], strips=[b"primary!"], subifds=sub)
    data = tw.write_tiff(ifd0)
    assert data[:4] == b"II*\x00"
    offsets = list_raw_ifds(data)
    assert len(offsets) == 4
    assert all(o % 4 == 0 for o in offsets)
    for i, offset in enumerate(offsets[1:]):
        entries = _raw_entries(data, offset)
        assert struct.unpack("<L", entries[256][2])[0] == i + 1
        assert entries[270][2] == f"frame {i}\0".encode()
        (strip_at,) = struct.unpack("<L", entries[273][2])
        (count,) = struct.unpack("<L", entries[279][2])
        assert data[strip_at:strip_at + count] == bytes([i]) * (10 + i)
    entries0 = _raw_entries(data, offsets[0])
    assert struct.unpack("<2L", entries0[33434][2]) == (1, 30)
    # Entries are sorted by tag, as TIFF requires.
    count = struct.unpack_from("<H", data, offsets[0])[0]
    tags = [struct.unpack_from("<H", data, offsets[0] + 2 + 12 * i)[0] for i in range(count)]
    assert tags == sorted(tags)


def test_entry_value_size_is_checked():
    with pytest.raises(ValueError):
        tw.Entry(256, tw.LONG, 2, b"\0" * 4)


def test_nested_subifds_are_refused():
    inner = tw.IFD(entries=[], subifds=[tw.IFD(entries=[])])
    with pytest.raises(ValueError):
        tw.write_tiff(tw.IFD(entries=[], subifds=[inner]))
