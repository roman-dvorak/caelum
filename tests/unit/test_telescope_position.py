from __future__ import annotations

from datetime import UTC, datetime

from caelum.config.schema import LensConfig
from caelum.derivatives.telescope_position import TelescopePositionSettings, marker_payload
from caelum.mount import MountPoller, MountState
from caelum.mount.indi import parse_indi_number
from caelum.sky.positions import radec_to_altaz

LENS = LensConfig()
WHEN = datetime(2026, 1, 15, 22, 0, tzinfo=UTC)


def _payload(state, **kw):
    return marker_payload(state, lens=LENS, lat_deg=50.0, lon_deg=14.0, when=WHEN, aspect=1.0, label="T", **kw)


def test_altaz_zenith_projects_to_lens_center():
    p = _payload(MountState(status="tracking", alt_deg=90.0, az_deg=0.0))
    assert (p["x"], p["y"]) == (LENS.center_x, LENS.center_y)
    assert p["status"] == "tracking"


def test_below_horizon_keeps_pointing_but_no_pixels():
    p = _payload(MountState(status="idle", alt_deg=-10.0, az_deg=90.0))
    assert "x" not in p and p["alt_deg"] == -10.0


def test_no_pointing_gives_nothing():
    assert _payload(MountState(status="disconnected")) is None


def test_radec_to_altaz_polaris_altitude_is_latitude():
    alt, _ = radec_to_altaz(37.95, 89.26, WHEN, 50.0, 14.0, "j2000")
    assert abs(alt - 50.0) < 1.0


def test_jnow_and_j2000_differ_by_precession():
    a = radec_to_altaz(100.0, 20.0, WHEN, 50.0, 14.0, "j2000")
    b = radec_to_altaz(100.0, 20.0, WHEN, 50.0, 14.0, "jnow")
    assert 0.1 < abs(a[0] - b[0]) + abs(a[1] - b[1]) < 1.0


def test_radec_state_is_stored_with_epoch():
    p = _payload(MountState(status="slewing", ra_deg=100.0, dec_deg=20.0, epoch="jnow"), now=10.0)
    assert p["ra_deg"] == 100.0 and p["epoch"] == "jnow"


def test_indi_sexagesimal():
    assert parse_indi_number("12:30:00") == 12.5
    assert parse_indi_number("-5 30 0") == -5.5
    assert parse_indi_number("3.25") == 3.25
    assert parse_indi_number("x") is None


class _Source:
    def __init__(self):
        self.fail = False

    def read(self):
        if self.fail:
            raise OSError("down")
        return MountState(status="tracking", alt_deg=40.0, az_deg=100.0, timestamp=clock[0])

    def close(self): ...


clock = [1000.0]


def test_poller_goes_offline_keeping_last_pointing_and_recovers():
    src = _Source()
    poller = MountPoller(src, stale_after_s=10.0, clock=lambda: clock[0])
    poller.poll_once()
    assert poller.latest().status == "tracking"
    src.fail = True
    try:
        poller.poll_once()
    except OSError:
        pass
    state = poller.latest()
    assert state.status == "offline" and state.alt_deg == 40.0
    src.fail = False
    poller.poll_once()
    assert poller.latest().status == "tracking"


def test_poller_marks_old_report_stale():
    src = _Source()
    poller = MountPoller(src, stale_after_s=10.0, clock=lambda: clock[0])
    poller.poll_once()
    clock[0] += 60
    assert poller.latest().status == "offline"


def test_settings_defaults_to_simulated():
    assert TelescopePositionSettings().source == "simulated"
