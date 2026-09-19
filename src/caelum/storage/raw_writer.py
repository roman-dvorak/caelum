"""FITS writer for raw frames. `astropy` is used purely as a file format
writer here — sky math lives entirely in control/skystate.py.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from astropy.io import fits

from caelum.capture.frame_store import ProcessedFrame


def write(path: Path, frame: ProcessedFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # FITS convention for a color cube: (channels, height, width).
    data = np.moveaxis(frame.image, -1, 0)

    hdu = fits.PrimaryHDU(data=data)
    header = hdu.header
    header["EXPOSURE"] = (frame.metadata.exposure_us / 1_000_000.0, "seconds")
    header["GAIN"] = (frame.metadata.analogue_gain, "analogue gain")
    header["DATE-OBS"] = frame.metadata.captured_at.isoformat()
    header["SUNALT"] = (frame.metadata.sky_state.sun_altitude_deg, "degrees")
    header["MOONALT"] = (frame.metadata.sky_state.moon_altitude_deg, "degrees")
    header["MOONILLU"] = (frame.metadata.sky_state.moon_illumination, "fraction 0-1")
    header["SKYPERD"] = frame.metadata.sky_state.period

    hdu.writeto(path, overwrite=True)
