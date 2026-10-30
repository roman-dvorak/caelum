"""The toggleable layers of the sky overlay.

Each layer is rendered by the camera into its own transparent PNG
(`overlays/.../<stem>.<layer>.png`) so a viewer can switch them on and off
without any sky maths — and without the camera's coordinates.
"""

from __future__ import annotations

from typing import Any

#: In stacking order, bottom first.
LAYER_IDS: tuple[str, ...] = ("grid", "constellations", "stars", "planets", "compass")

#: The plugin setting that switches each layer on; all default to on.
_SETTING = {
    "grid": "show_grid",
    "constellations": "show_constellations",
    "stars": "show_stars",
    "planets": "show_planets",
    "compass": "show_compass",
}


def sky_overlay_layers(settings: dict[str, Any]) -> list[str]:
    """The layers a `sky_overlay` plugin with these settings renders."""
    return [layer for layer in LAYER_IDS if settings.get(_SETTING[layer], True)]
