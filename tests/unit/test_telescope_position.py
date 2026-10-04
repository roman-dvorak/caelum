from __future__ import annotations

from caelum.derivatives.telescope_position import TelescopePositionSettings, project_altaz_to_fraction


def test_zenith_projects_to_the_configured_center():
    settings = TelescopePositionSettings(center_x=0.5, center_y=0.5, radius=0.4)
    point = project_altaz_to_fraction(alt_deg=90.0, az_deg=0.0, settings=settings)
    assert point is not None
    assert point.x == 0.5
    assert point.y == 0.5


def test_horizon_north_projects_to_top_of_the_configured_radius():
    settings = TelescopePositionSettings(center_x=0.5, center_y=0.5, radius=0.4)
    point = project_altaz_to_fraction(alt_deg=0.0, az_deg=0.0, settings=settings)
    assert point is not None
    assert round(point.x, 6) == 0.5
    assert round(point.y, 6) == 0.1  # center_y - radius


def test_below_horizon_returns_none():
    settings = TelescopePositionSettings()
    assert project_altaz_to_fraction(alt_deg=-5.0, az_deg=90.0, settings=settings) is None
