"""Release manifest: a static JSON file listing available releases.

    {"releases": [{"version": "0.3.0", "wheel": "caelum-0.3.0-py3-none-any.whl",
                   "sha256": "...", "notes": "..."}]}

`wheel` is resolved relative to the manifest's own URL (an absolute URL works
too), so publishing a channel anywhere means copying the files
`scripts/build-release.sh` produces, nothing more.
"""

from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass
from urllib.parse import urljoin

from packaging.version import InvalidVersion, Version

_TIMEOUT_S = 15
_MAX_MANIFEST_BYTES = 1024 * 1024


@dataclass(frozen=True)
class Release:
    version: str
    wheel_url: str
    sha256: str | None
    notes: str


class ManifestError(Exception):
    pass


def parse_manifest(data: dict, manifest_url: str) -> list[Release]:
    releases = []
    for item in data.get("releases", []):
        try:
            Version(item["version"])
            releases.append(
                Release(
                    version=item["version"],
                    wheel_url=urljoin(manifest_url, item["wheel"]),
                    sha256=item.get("sha256"),
                    notes=item.get("notes", ""),
                )
            )
        except (KeyError, TypeError, InvalidVersion) as exc:
            raise ManifestError(f"Malformed release entry {item!r}: {exc}") from exc
    return releases


def fetch_manifest(url: str) -> list[Release]:
    try:
        with urllib.request.urlopen(url, timeout=_TIMEOUT_S) as response:
            body = response.read(_MAX_MANIFEST_BYTES + 1)
    except OSError as exc:
        raise ManifestError(f"Cannot fetch {url}: {exc}") from exc
    if len(body) > _MAX_MANIFEST_BYTES:
        raise ManifestError(f"{url} is larger than a manifest should be")
    try:
        data = json.loads(body)
    except ValueError as exc:
        raise ManifestError(f"{url} is not valid JSON: {exc}") from exc
    return parse_manifest(data, url)


def latest_newer(releases: list[Release], current: str) -> Release | None:
    """The newest release strictly newer than `current`, if any."""
    try:
        current_version = Version(current)
    except InvalidVersion:
        current_version = Version("0")
    candidates = [r for r in releases if Version(r.version) > current_version]
    return max(candidates, key=lambda r: Version(r.version), default=None)
