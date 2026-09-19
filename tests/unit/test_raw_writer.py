from __future__ import annotations

from astropy.io import fits

from caelum.storage import raw_writer
from tests.factories import make_processed_frame


def test_write_produces_a_readable_fits_file_with_expected_header(tmp_path):
    frame = make_processed_frame()
    path = tmp_path / "120000.fits"

    raw_writer.write(path, frame)

    assert path.exists()
    with fits.open(path) as hdul:
        data = hdul[0].data
        header = hdul[0].header
        assert data.shape == (3, frame.image.shape[0], frame.image.shape[1])
        assert header["GAIN"] == frame.metadata.analogue_gain
        assert header["SKYPERD"] == frame.metadata.sky_state.period
