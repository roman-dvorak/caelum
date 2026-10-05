# Capture sets in DNG

A capture program can return several frames that belong together — an HDR
bracket, a series of darks, a focus sweep — as one **capture set**. When the
set's raw frames are stored, they go into **one multi-frame DNG**. This
document is the convention for that file; it is caelum's own, built only from
standard TIFF/DNG structures so that ordinary software still opens it.

## Files of a set

For a set whose representative (primary) frame was captured at
`YYYYMMDD-HHMMSS` (UTC):

| file | contents |
|---|---|
| `thumbnails/Y/M/D/<stem>.webp` + `.json` | the representative — listed, shown live, used by derivatives and uploads |
| `thumbnails/Y/M/D/<stem>_set/<stem>_mNN.webp` + `.json` | every other member, `NN` = its position in the set |
| `raw/Y/M/D/<stem>.dng` + `.json` | **all** raw frames of the set (below); the sidecar is the representative's |

Every sidecar has `capture_set` (`id`, `kind`, `count`, `index`, `role`,
`representative`); the representative's also lists all `members` with their
file stems and settings. A single frame is simply a set of one: plain files,
no `capture_set`.

## Layout of the multi-frame DNG

```
IFD0      primary raw frame          (NewSubfileType 0, full camera profile, XMP)
 └ SubIFDs (tag 330), in set order without the primary:
   SubIFD0  raw frame                (NewSubfileType 0)
   SubIFD1  raw frame
   ...
```

- **IFD0** is a complete caelum DNG of the primary frame: image structure,
  CFA, black/white level, `ColorMatrix1`, `AsShotNeutral`, `Make`/`Model`,
  EXIF basics (`ExposureTime`, ISO, `DateTimeOriginal`), and the XMP packet.
  Software that ignores SubIFDs therefore opens the right frame — the one the
  set is represented by everywhere else.
- **Each SubIFD** is an independently decodable raw image: its own
  `ImageWidth`/`ImageLength`, `BitsPerSample`, `Compression` (LJ92 = 7 or
  uncompressed = 1), `PhotometricInterpretation` (CFA), `CFARepeatPatternDim`,
  `CFAPattern`, `BlackLevelRepeatDim`, `BlackLevel`, `WhiteLevel`, strips — and,
  for convenience only, the frame's `ExposureTime`, ISO, `DateTimeOriginal`,
  `SubsecTimeOriginal`.
- The **colour profile** (`ColorMatrix1`, `AsShotNeutral`, calibration) lives
  in IFD0 only, as DNG requires, and applies to every frame (they are all from
  the same camera; per-frame colour gains are in the XMP records).

## XMP

Namespace `caelum` = `https://caelum.astrometers.eu/ns/1.0/`, in IFD0's XMP
packet (tag 700).

On the description itself — everything a single-frame caelum DNG has (sky,
location, exposure, provenance: `capture_program`, `capture_program_sha256`,
`caelum_version`, `camera_capabilities`, ...) for the primary frame, plus the
set:

| property | meaning |
|---|---|
| `caelum:capture_set_id` | random id of the set |
| `caelum:capture_set_kind` | `hdr`, `dark`, `series`, ... |
| `caelum:capture_set_count` | number of frames |
| `caelum:capture_set_index` | the primary's position in the set |
| `caelum:capture_set_representative` | same, as recorded by the program |

and **`caelum:frames`**, an ordered `rdf:Seq` with one struct per frame **in
set order** (position 0 first, regardless of which IFD holds it):

```xml
<caelum:frames>
 <rdf:Seq>
  <rdf:li>
   <rdf:Description
     caelum:index="0"
     caelum:ifd="SubIFD0"
     caelum:role="member"
     caelum:captured_at="2026-10-05T01:02:03.100000+00:00"
     caelum:exposure_us="1000"
     caelum:analogue_gain="1.0"
     caelum:requested_exposure_us="1000"
     .../>
  </rdf:li>
  ...
 </rdf:Seq>
</caelum:frames>
```

| field | meaning |
|---|---|
| `index` | position in the set |
| `ifd` | where its raw data is: `IFD0` or `SubIFD<n>` (n = 0-based entry of tag 330) |
| `role` | `representative` or `member` |
| `captured_at` | middle of the exposure, UTC ISO 8601 |
| `exposure_us`, `analogue_gain`, `digital_gain`, `colour_gains` | as the camera applied them |
| `sensor_timestamp_ns`, `sensor_temperature_c` | from the camera |
| `brightness_median`, `focus_score` | caelum's measurements |
| `requested_exposure_us`, `requested_analogue_gain`, `requested_colour_gains`, `capture_clamped`, `capture_ignored` | what the program asked for and what the camera could not do |
| `annotations` | the program's notes for the frame, JSON |

**`caelum:frames` is authoritative.** The EXIF tags in the SubIFDs are a
convenience copy for tools that show per-IFD EXIF.

## Reading it

- Python: `caelum.storage.dng_reader.list_raw_ifds(data)` gives the raw IFD
  offsets in file order; `standalone_frame(data, n)` returns frame `n` as an
  ordinary single-frame DNG (IFD0's profile + that frame's raw data) that any
  raw developer, or `rawpy`, opens.
- LibRaw / rawpy on the file itself returns the primary (IFD0) frame.

## Compatibility

Verified automatically (tests `test_dng_multi.py`, `test_capture_set.py`):

- LibRaw (rawpy 0.27.1, LibRaw 0.22.1) opens the file and decodes IFD0 —
  bit-identical to the samples written, LJ92 and uncompressed;
- every frame, extracted with `standalone_frame`, decodes bit-identically.

To check by hand on a desktop (not automated here):

| tool | expected |
|---|---|
| `exiftool -a -G1 file.dng` | IFD0 + `SubIFD`, `SubIFD1`, ... groups; XMP-caelum incl. `Frames` |
| darktable, RawTherapee | open the primary frame |
| Adobe DNG SDK `dng_validate` | warnings about SubIFDs with NewSubfileType 0 are possible — DNG expects one main image; the extra frames are extensions of this convention |
