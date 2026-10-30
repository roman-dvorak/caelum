"""Release manifest selection and the boot guard's rollback."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from caelum.update import releases
from caelum.update.job import Updater
from caelum.update.manifest import ManifestError, latest_newer, parse_manifest

_SHA = "a" * 64
_LAUNCH = Path(releases.__file__).resolve().parents[1] / "deploy" / "caelum-launch"


def test_manifest_picks_newest_newer_release_and_resolves_wheel_url():
    data = {
        "releases": [
            {"version": "0.2.0", "wheel": "caelum-0.2.0-py3-none-any.whl", "sha256": _SHA},
            {"version": "0.10.0", "wheel": "caelum-0.10.0-py3-none-any.whl", "sha256": _SHA},
            {"version": "0.3.0", "wheel": "https://cdn.example/caelum-0.3.0-py3-none-any.whl", "sha256": _SHA},
        ]
    }
    found = parse_manifest(data, "https://example.org/caelum/stable/manifest.json")
    newest = latest_newer(found, "0.2.0")
    assert newest is not None and newest.version == "0.10.0"
    assert newest.wheel_url == "https://example.org/caelum/stable/caelum-0.10.0-py3-none-any.whl"
    assert latest_newer(found, "0.10.0") is None


def test_manifest_refuses_unverifiable_or_insecure_releases():
    url = "https://example.org/manifest.json"
    with pytest.raises(ManifestError, match="sha256"):
        parse_manifest({"releases": [{"version": "1.0.0", "wheel": "caelum-1.0.0-py3-none-any.whl"}]}, url)
    with pytest.raises(ManifestError, match="https"):
        parse_manifest(
            {"releases": [{"version": "1.0.0", "wheel": "http://evil.example/c.whl", "sha256": _SHA}]}, url
        )
    with pytest.raises(ManifestError, match="https"):
        parse_manifest(
            {"releases": [{"version": "1.0.0", "wheel": "file:///tmp/c.whl", "sha256": _SHA}]}, url
        )


def _fake_release(root: Path, version: str, exit_code: int) -> None:
    bin_dir = root / "releases" / version / "venv" / "bin"
    bin_dir.mkdir(parents=True)
    caelum = bin_dir / "caelum"
    caelum.write_text(f"#!/bin/sh\necho {version}\nexit {exit_code}\n")
    caelum.chmod(0o755)


def test_boot_guard_rolls_back_a_release_that_keeps_failing(tmp_path):
    _fake_release(tmp_path, "0.1.0", 0)
    _fake_release(tmp_path, "0.2.0", 1)
    os.symlink("releases/0.1.0", tmp_path / "current")
    layout = releases.ReleaseLayout(tmp_path)
    releases.switch_to(layout, "0.2.0")

    env = {**os.environ, "CAELUM_RELEASES_DIR": str(tmp_path)}
    ran = [subprocess.run([str(_LAUNCH)], env=env, capture_output=True, text=True).stdout.strip() for _ in range(4)]

    # Three tries of the new release, then the guard restores the old one.
    assert ran == ["0.2.0", "0.2.0", "0.2.0", "0.1.0"]
    assert layout.version_of(layout.current) == "0.1.0"
    assert not layout.pending.exists()
    assert releases.read_result(layout)["state"] == "rolled_back"
    assert releases.read_result(layout)["to"] == "0.2.0"


def test_confirm_healthy_keeps_only_current_and_previous(tmp_path):
    for version in ("0.1.0", "0.2.0", "0.3.0"):
        _fake_release(tmp_path, version, 0)
    os.symlink("releases/0.2.0", tmp_path / "current")
    layout = releases.ReleaseLayout(tmp_path)
    releases.switch_to(layout, "0.3.0")

    assert releases.confirm_healthy(layout)
    assert sorted(p.name for p in layout.releases.iterdir()) == ["0.2.0", "0.3.0"]
    result = releases.read_result(layout)
    assert (result["state"], result["from"], result["to"]) == ("success", "0.2.0", "0.3.0")


def test_update_stops_before_installing_when_the_disk_is_too_full(tmp_path, monkeypatch):
    _fake_release(tmp_path, "0.1.0", 0)
    os.symlink("releases/0.1.0", tmp_path / "current")
    layout = releases.ReleaseLayout(tmp_path)
    wheel = tmp_path / "caelum-0.2.0-py3-none-any.whl"
    wheel.write_bytes(b"")
    asked: list[float] = []
    installed: list[Path] = []
    monkeypatch.setattr(releases, "free_space_mb", lambda _path: 50.0)
    monkeypatch.setattr(releases, "install_release", lambda _layout, w, _log: installed.append(w))

    updater = Updater(layout, request_restart=lambda: None, make_room=lambda _path, mb: asked.append(mb))
    updater._run(None, wheel)

    assert asked == [releases.required_space_mb(layout)]
    assert installed == []
    assert updater.state == "failed"
    assert "Not enough disk space" in (updater.error or "")
