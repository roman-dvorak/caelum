"""The web package ships data generated from the backend's (`scripts/export_sky_*.py`).
These fail when the backend's catalog or maths changed and the export was not re-run."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKY_WEB = ROOT / "web" / "packages" / "sky"


def _script(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_web_catalog_and_constellations_are_current():
    stars, figures = _script("export_sky_web_data").build()
    assert json.loads((SKY_WEB / "src" / "data" / "stars.json").read_text()) == stars
    assert json.loads((SKY_WEB / "src" / "data" / "constellations.json").read_text()) == figures


def test_web_test_fixtures_are_current():
    built = _script("export_sky_fixtures").build()
    assert json.loads((SKY_WEB / "test" / "fixtures.json").read_text()) == built
