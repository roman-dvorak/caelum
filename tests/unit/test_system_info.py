from __future__ import annotations

import subprocess

import pytest

from caelum.control import system_info


def test_collect_returns_sane_live_values(tmp_path):
    info = system_info.collect(data_dir=str(tmp_path))

    assert info.hostname
    assert info.uptime_s >= 0
    assert 0.0 <= info.cpu_percent <= 100.0
    assert info.cpu_count >= 1
    assert 0.0 <= info.mem_percent <= 100.0
    assert info.mem_used_bytes <= info.mem_total_bytes
    paths = {d.path for d in info.disks}
    assert "/" in paths
    assert str(tmp_path) in paths
    assert all(0.0 <= d.percent <= 100.0 for d in info.disks)


def test_power_action_wraps_failed_command(monkeypatch):
    def fake_run(command, **kwargs):
        raise subprocess.CalledProcessError(returncode=1, cmd=command, stderr="poweroff refused")

    monkeypatch.setattr(system_info.subprocess, "run", fake_run)

    with pytest.raises(system_info.PowerActionError, match="poweroff refused"):
        system_info.shutdown()
