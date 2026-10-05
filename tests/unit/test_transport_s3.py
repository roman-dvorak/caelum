from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import pytest
from botocore.exceptions import ClientError, EndpointConnectionError

from caelum.config.schema import UploadConfig
from caelum.upload import transport_s3


class FakeS3:
    """In-memory stand-in for the handful of boto3 client calls the
    transport makes. `page_size` forces list_objects_v2 pagination."""

    def __init__(self, page_size: int = 1000) -> None:
        self.objects: dict[str, dict] = {}
        self.uploads: list[str] = []
        self.page_size = page_size
        self.fail_with: Exception | None = None

    def list_objects_v2(self, Bucket, Prefix, ContinuationToken=None):  # noqa: N803
        if self.fail_with:
            raise self.fail_with
        keys = sorted(k for k in self.objects if k.startswith(Prefix))
        start = int(ContinuationToken or 0)
        page = keys[start : start + self.page_size]
        result = {
            "Contents": [
                {"Key": k, "Size": len(self.objects[k]["body"]), "LastModified": self.objects[k]["mtime"]}
                for k in page
            ],
            "IsTruncated": start + self.page_size < len(keys),
        }
        if result["IsTruncated"]:
            result["NextContinuationToken"] = str(start + self.page_size)
        return result

    def upload_file(self, filename, bucket, key, ExtraArgs=None):  # noqa: N803
        if self.fail_with:
            raise self.fail_with
        with open(filename, "rb") as f:
            body = f.read()
        self.objects[key] = {"body": body, "mtime": datetime.now(UTC), "extra": ExtraArgs or {}}
        self.uploads.append(key)

    def download_file(self, bucket, key, filename):
        if key not in self.objects:
            raise ClientError({"Error": {"Code": "404", "Message": "Not Found"}}, "HeadObject")
        with open(filename, "wb") as f:
            f.write(self.objects[key]["body"])


@pytest.fixture
def fake_s3(monkeypatch):
    fake = FakeS3()
    monkeypatch.setattr(transport_s3, "_client", lambda cfg: fake)
    return fake


def _cfg(**overrides) -> UploadConfig:
    return UploadConfig(**{"transport": "s3", "s3_bucket": "allsky", "s3_prefix": "data", **overrides})


def _tree(tmp_path):
    root = tmp_path / "local"
    (root / "thumbnails" / "2026" / "01" / "01").mkdir(parents=True)
    (root / "thumbnails" / "2026" / "01" / "01" / "120000.jpg").write_bytes(b"jpeg")
    (root / "thumbnails" / "2026" / "01" / "01" / "120000.json").write_text("{}")
    (root / "raw" / "2026" / "01" / "01").mkdir(parents=True)
    (root / "raw" / "2026" / "01" / "01" / ".120000.dng.tmp").write_bytes(b"half-written")
    return root


def test_push_tree_uploads_everything_under_prefix_and_skips_tmp_files(tmp_path, fake_s3):
    root = _tree(tmp_path)

    assert transport_s3.push_tree(_cfg(), root, "cam0")

    assert sorted(fake_s3.objects) == [
        "data/cam0/thumbnails/2026/01/01/120000.jpg",
        "data/cam0/thumbnails/2026/01/01/120000.json",
    ]
    jpg = fake_s3.objects["data/cam0/thumbnails/2026/01/01/120000.jpg"]["extra"]
    meta = fake_s3.objects["data/cam0/thumbnails/2026/01/01/120000.json"]["extra"]
    assert jpg == {"ContentType": "image/jpeg"}
    assert meta == {"ContentType": "application/json", "CacheControl": "no-cache"}


def test_push_tree_is_incremental(tmp_path, fake_s3):
    root = _tree(tmp_path)
    cfg = _cfg()
    transport_s3.push_tree(cfg, root, "cam0")
    fake_s3.uploads.clear()

    assert transport_s3.push_tree(cfg, root, "cam0")
    assert fake_s3.uploads == []

    # A rewritten file (same size, newer mtime) is re-uploaded; a new one too.
    meta = root / "thumbnails" / "2026" / "01" / "01" / "120000.json"
    meta.write_text("[]")
    future = (datetime.now(UTC) + timedelta(minutes=1)).timestamp()
    os.utime(meta, (future, future))
    (root / "thumbnails" / "2026" / "01" / "01" / "120100.jpg").write_bytes(b"jpeg2")

    assert transport_s3.push_tree(cfg, root, "cam0")
    assert sorted(fake_s3.uploads) == [
        "data/cam0/thumbnails/2026/01/01/120000.json",
        "data/cam0/thumbnails/2026/01/01/120100.jpg",
    ]


def test_push_tree_follows_listing_pagination(tmp_path, fake_s3):
    fake_s3.page_size = 1
    root = _tree(tmp_path)
    transport_s3.push_tree(_cfg(), root, "cam0")
    fake_s3.uploads.clear()

    transport_s3.push_tree(_cfg(), root, "cam0")
    assert fake_s3.uploads == []


def test_push_tree_reports_failure_when_endpoint_unreachable(tmp_path, fake_s3):
    fake_s3.fail_with = EndpointConnectionError(endpoint_url="https://s3.example")
    assert transport_s3.push_tree(_cfg(), _tree(tmp_path), "cam0") is False


def test_acl_is_applied_when_configured(tmp_path, fake_s3):
    path = tmp_path / "manifest.json"
    path.write_text("{}")
    assert transport_s3.push_file(_cfg(s3_acl="public-read"), path, "cam0/manifest.json")
    assert fake_s3.objects["data/cam0/manifest.json"]["extra"]["ACL"] == "public-read"


def test_pull_file_round_trip_and_missing_object(tmp_path, fake_s3):
    cfg = _cfg(s3_prefix="")
    src = tmp_path / "cameras.json"
    src.write_text('{"cameras": []}')
    transport_s3.push_file(cfg, src, "cameras.json")

    dest = tmp_path / "pulled.json"
    assert transport_s3.pull_file(cfg, "cameras.json", dest)
    assert dest.read_text() == '{"cameras": []}'
    assert transport_s3.pull_file(cfg, "nope.json", tmp_path / "nope.json") is False
