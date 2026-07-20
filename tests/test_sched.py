import plistlib
import subprocess
import sys
from pathlib import Path

import pytest

from jotd import sched
from jotd.sched import render_plist, render_sync_plist


def test_plist_roundtrips_and_carries_the_contract(tmp_path):
    raw = render_plist("morning", "09:00", "/usr/local/bin/jotd", Path("/Users/x/jotd"))
    payload = plistlib.loads(raw)
    assert payload["Label"] == "com.jotd.pulse.morning"
    assert payload["ProgramArguments"][:4] == ["/usr/local/bin/jotd", "pulse", "--slot", "morning"]
    assert payload["StartCalendarInterval"] == {"Hour": 9, "Minute": 0}
    assert payload["WorkingDirectory"] == "/Users/x/jotd"
    assert payload["EnvironmentVariables"]["JOTD_DIR"] == "/Users/x/jotd"
    assert "/usr/bin" in payload["EnvironmentVariables"]["PATH"]
    assert payload["StandardOutPath"].endswith("state/logs/pulse-morning.log")


@pytest.mark.skipif(sys.platform != "darwin", reason="plutil is macOS-only")
def test_generated_plist_passes_plutil_lint(tmp_path):
    path = tmp_path / "test.plist"
    path.write_bytes(render_plist("evening", "17:30", "/usr/local/bin/jotd", tmp_path))
    proc = subprocess.run(["plutil", "-lint", str(path)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_sync_plist_roundtrips_and_carries_the_contract():
    raw = render_sync_plist(15, "/usr/local/bin/jotd", Path("/Users/x/jotd"))
    payload = plistlib.loads(raw)
    assert payload["Label"] == "com.jotd.sync.auto"
    assert payload["ProgramArguments"] == ["/usr/local/bin/jotd", "sync", "--auto"]
    assert payload["StartInterval"] == 900
    assert "StartCalendarInterval" not in payload
    assert payload["WorkingDirectory"] == "/Users/x/jotd"
    assert payload["EnvironmentVariables"]["JOTD_DIR"] == "/Users/x/jotd"
    assert payload["StandardOutPath"].endswith("state/logs/sync-auto.log")
    assert payload["StandardErrorPath"].endswith("state/logs/sync-auto.log")


@pytest.mark.skipif(sys.platform != "darwin", reason="plutil is macOS-only")
def test_sync_plist_passes_plutil_lint(tmp_path):
    path = tmp_path / "test.plist"
    path.write_bytes(render_sync_plist(30, "/usr/local/bin/jotd", tmp_path))
    proc = subprocess.run(["plutil", "-lint", str(path)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr


class _FakeLaunchctl:
    def __init__(self):
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, *args: str):
        self.calls.append(args)
        return subprocess.CompletedProcess(["launchctl", *args], 0, "", "")


def test_uninstall_and_status_cover_both_families(tmp_path, monkeypatch):
    fake = _FakeLaunchctl()
    monkeypatch.setattr(sched, "launch_agents_dir", lambda: tmp_path)
    monkeypatch.setattr(sched, "_launchctl", fake)
    (tmp_path / "com.jotd.pulse.morning.plist").write_bytes(b"x")
    (tmp_path / "com.jotd.sync.auto.plist").write_bytes(b"x")
    (tmp_path / "com.other.thing.plist").write_bytes(b"x")  # never ours to touch

    lines = sched.status()
    assert lines == ["com.jotd.pulse.morning: loaded", "com.jotd.sync.auto: loaded"]

    removed = sched.uninstall()
    assert removed == ["removed com.jotd.pulse.morning.plist", "removed com.jotd.sync.auto.plist"]
    assert not (tmp_path / "com.jotd.pulse.morning.plist").exists()
    assert not (tmp_path / "com.jotd.sync.auto.plist").exists()
    assert (tmp_path / "com.other.thing.plist").exists()
    booted_out = [c for c in fake.calls if c[0] == "bootout"]
    assert len(booted_out) == 2


def test_install_sync_skips_without_git_or_origin(tmp_path):
    assert sched.install_sync(tmp_path, 15) == [
        "auto-sync skipped: data dir is not a git repository"
    ]
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    out = sched.install_sync(tmp_path, 15)
    assert out == ["auto-sync skipped: no 'origin' remote (a scheduled sync would fail every tick)"]


@pytest.mark.skipif(sys.platform != "darwin", reason="plutil is macOS-only")
def test_install_sync_writes_lints_and_bootstraps(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    subprocess.run(["git", "init", "-q", str(data_dir)], check=True)
    subprocess.run(
        ["git", "-C", str(data_dir), "remote", "add", "origin", str(tmp_path / "origin.git")],
        check=True,
    )
    agents = tmp_path / "agents"
    agents.mkdir()
    fake = _FakeLaunchctl()
    monkeypatch.setattr(sched, "launch_agents_dir", lambda: agents)
    monkeypatch.setattr(sched, "_launchctl", fake)
    monkeypatch.setattr(sched, "_jotd_bin", lambda: "/usr/local/bin/jotd")

    out = sched.install_sync(data_dir, 20)
    assert out == ["scheduled auto-sync every 20 min (com.jotd.sync.auto.plist)"]
    payload = plistlib.loads((agents / "com.jotd.sync.auto.plist").read_bytes())
    assert payload["StartInterval"] == 1200
    assert [c[0] for c in fake.calls] == ["bootout", "bootstrap"]
