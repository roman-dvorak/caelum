"""Formatting of thermal values into text, shared by the thermal overlay
plugin and the overlay editor's `{placeholders}`."""

from __future__ import annotations

import string
from typing import Any

from caelum.telemetry.thermal import THERMAL_FIELDS


class _Missing:
    """Stands in for a value the frame has no reading for; formats as an
    en dash whatever the format spec (`{dome_temp:.1f}` included)."""

    def __format__(self, format_spec: str) -> str:
        return "–"


_MISSING = _Missing()


def thermal_kwargs(thermal: dict[str, Any] | None) -> dict[str, Any]:
    values = thermal or {}
    return {
        name: values[name] if values.get(name) is not None else _MISSING
        for name in THERMAL_FIELDS
    }


def format_thermal(template: str, thermal: dict[str, Any] | None) -> str:
    try:
        return string.Formatter().format(template, **thermal_kwargs(thermal))
    except (KeyError, AttributeError, IndexError, ValueError, TypeError):
        # A bad placeholder shows the raw template so the mistake is visible.
        return template
