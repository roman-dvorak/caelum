"""The scp transport against fake `ssh`/`scp` that act on the local
filesystem (so the real commands, listing and comparison run), the shared
SSH options, and what the reconciliation pass uploads."""

from __future__ import annotations

import json
import os
import sys
import textwrap
from datetime import UTC, datetime
from pathlib import Path

import pytest

from caelum.config.schema import UploadConfig
from caelum.upload import transport_rsync, transport_scp
from caelum.upload.uploader import UploadWorker

FAKE_SSH = """
import subprocess, sys, json, os
log = os.environ["FAKE_SSH_LOG"]
args = sys.argv[1:]
with open(log, "a") as f: f.write(json.dumps(["ssh"] + args) + "\\n")
i = 0
while args[i].startswith("-"):
    i += 2 if args[i] in ("-i", "-o", "-p", "-l", "-F") else 1
command = " ".join(args[i + 1:])
sys.exit(subprocess.run(["sh", "-c", command]).returncode)
"""

FAKE_SCP = """
import shutil, sys, json, os
log = os.environ["FAKE_SSH_LOG"]
args = sys.argv[1:]
with open(log, "a") as f: f.write(json.dumps(["scp"] + args) + "\\n")
i, rest = 0, []
while i < len(args):
    if args[i] in ("-i", "-o", "-P", "-l", "-F"): i += 2; continue
    if args[i].startswith("-"): i += 1; continue
    rest.append(args[i].split(":", 1)[1] if ":" in args[i] else args[i]); i += 1
*sources, target = rest
for src in sources:
    if not os.path.exists(src):
        sys.stderr.write(f"{src}: No such file"); sys.exit(1)
    shutil.copy2(src, target)  # -p: keep times
"""


@pytest.fixture
def fake_ssh(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in (("ssh", FAKE_SSH), ("scp", FAKE_SCP)):
        script = bin_dir / name
        script.write_text(f"#!{sys.executable}\n" + textwrap.dedent(body))
        script.chmod(0o755)
    log = tmp_path / "calls.log"
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_SSH_LOG", str(log))

    def calls(kind=None):
        if not log.exists():
            return []
        entries = [json.loads(line) for line in log.read_text().splitlines()]
        return [e for e in entries if kind is None or e[0] == kind]

    return calls


def _cfg(remote: Path, **kw) -> UploadConfig:
    return UploadConfig(transport="scp", remote_host="archive.example", remote_user="cam",
                        remote_base_path=str(remote), ssh_key_path="/etc/caelum/upload_key", **kw)


def _tree(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_scp_push_tree_copies_only_what_is_missing_or_changed(tmp_path, fake_ssh):
    local, remote = tmp_path / "local", tmp_path / "remote"
    (local / "2026/10/05/x_set").mkdir(parents=True)
    (local / "2026/10/05/a.webp").write_bytes(b"a")
    (local / "2026/10/05/a.json").write_text("{}")
    (local / "2026/10/05/x_set/m.webp").write_bytes(b"m")
    (local / "2026/10/05/.b.dng.tmp").write_bytes(b"partial")
    cfg = _cfg(remote, ssh_port=2222, bandwidth_limit_kbps=100)

    assert transport_scp.push_tree(cfg, local, "cam0/thumbnails")
    assert _tree(remote / "cam0/thumbnails") == {
        "2026/10/05/a.webp": b"a", "2026/10/05/a.json": b"{}", "2026/10/05/x_set/m.webp": b"m",
    }
    scp_calls = fake_ssh("scp")
    assert all(c[1:4] == ["-p", "-q", "-B"] for c in scp_calls)
    assert all(["-P", "2222"] == c[c.index("-P"):c.index("-P") + 2] for c in scp_calls)
    assert all("800" in c for c in scp_calls)  # 100 KiB/s = 800 Kbit/s
    assert all(c[-1].startswith("cam@archive.example:") for c in scp_calls)
    assert any(["-p", "2222"] == c[c.index("-p"):c.index("-p") + 2] for c in fake_ssh("ssh"))

    # Second pass: nothing changed, nothing copied.
    before = len(fake_ssh("scp"))
    assert transport_scp.push_tree(cfg, local, "cam0/thumbnails")
    assert len(fake_ssh("scp")) == before

    # A changed file (size) and a new one go up; the rest doesn't.
    (local / "2026/10/05/a.json").write_text('{"x": 1}')
    (local / "2026/10/05/c.webp").write_bytes(b"c")
    assert transport_scp.push_tree(cfg, local, "cam0/thumbnails")
    new_calls = fake_ssh("scp")[before:]
    sent = {Path(arg).name for call in new_calls for arg in call if arg.startswith(str(local))}
    assert sent == {"a.json", "c.webp"}
    assert (remote / "cam0/thumbnails/2026/10/05/a.json").read_text() == '{"x": 1}'


def test_scp_push_and_pull_file(tmp_path, fake_ssh):
    remote = tmp_path / "remote"
    cfg = _cfg(remote)
    src = tmp_path / "cameras.json"
    src.write_text('{"cameras": []}')
    assert transport_scp.push_file(cfg, src, "cameras.json")
    assert (remote / "cameras.json").read_text() == '{"cameras": []}'
    back = tmp_path / "back.json"
    assert transport_scp.pull_file(cfg, "cameras.json", back)
    assert back.read_text() == '{"cameras": []}'
    assert not transport_scp.pull_file(cfg, "missing.json", tmp_path / "nope.json")


def test_scp_without_host_refuses(tmp_path):
    local = tmp_path / "local"
    local.mkdir()
    (local / "a").write_text("x")
    assert not transport_scp.push_tree(UploadConfig(transport="scp"), local, "cam0")


def test_rsync_uses_port_and_bandwidth_limit():
    cfg = UploadConfig(remote_host="h", remote_user="u", ssh_port=2222, bandwidth_limit_kbps=50)
    options = transport_rsync._ssh_option(cfg)
    assert options[0] == "--bwlimit=50"
    assert options[1] == "-e" and "-p 2222" in options[2] and "BatchMode=yes" in options[2]
    assert transport_rsync._target(cfg, "x") == "u@h:/var/www/allsky-data/x"


class _Holder:
    def __init__(self, upload: UploadConfig) -> None:
        from caelum.config.schema import AppConfig

        self.current = AppConfig().model_copy(update={"upload": upload})


@pytest.mark.parametrize("transport", ["rsync", "scp"])
def test_reconcile_uploads_only_published_captures(tmp_path, fake_ssh, transport):
    from caelum.events import EventBus

    data, remote = tmp_path / "data", tmp_path / "remote"
    for rel in ("thumbnails/2026/10/05/a.webp", "raw/2026/10/05/a.dng", "derivatives/2026/10/05/k/x.png",
                "capture-programs/mine.py", "program-tests/run/report.json", "overlay_assets/logo.png"):
        (data / rel).parent.mkdir(parents=True, exist_ok=True)
        (data / rel).write_bytes(b"x")
    cfg = _cfg(remote) if transport == "scp" else UploadConfig(
        remote_base_path=str(remote), transport="rsync")
    worker = UploadWorker(_Holder(cfg), EventBus(), data)
    worker._reconcile(cfg)
    uploaded = set(_tree(remote / "cam0"))
    assert {"thumbnails/2026/10/05/a.webp", "raw/2026/10/05/a.dng", "derivatives/2026/10/05/k/x.png",
            "manifest.json"} <= uploaded
    assert not [p for p in uploaded if p.startswith(("capture-programs", "program-tests", "overlay_assets"))]
    assert (remote / "cameras.json").exists()
    assert worker.uploaded_before() is not None and worker.uploaded_before() <= datetime.now(UTC)
