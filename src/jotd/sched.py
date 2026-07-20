"""launchd scheduling for the pulse and auto-sync (macOS).

`jotd schedule install` writes one plist per pulse slot (plus one auto-sync
job when [sync] auto is on) into ~/Library/LaunchAgents and bootstraps them
into the user's gui domain — the same domain that owns the login keychain,
which the claude CLI needs for headless auth.
"""

from __future__ import annotations

import os
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

from jotd.config import load_config

LABEL_PREFIX = "com.jotd.pulse"
SYNC_LABEL = "com.jotd.sync.auto"
# Both job families share the com.jotd. namespace; uninstall/status glob it.
GLOB_ALL = "com.jotd.*.plist"


def launch_agents_dir() -> Path:
    return Path.home() / "Library" / "LaunchAgents"


def plist_path(slot: str) -> Path:
    return launch_agents_dir() / f"{LABEL_PREFIX}.{slot}.plist"


def sync_plist_path() -> Path:
    return launch_agents_dir() / f"{SYNC_LABEL}.plist"


def _jotd_bin() -> str:
    sibling = Path(sys.executable).parent / "jotd"
    if sibling.is_file():
        return str(sibling)
    found = shutil.which("jotd")
    if not found:
        raise RuntimeError("cannot resolve the jotd binary for the plist")
    return found


def _env_path(jotd_bin: str) -> str:
    dirs = [str(Path(jotd_bin).parent)]
    claude = shutil.which("claude")
    if claude:
        dirs.append(str(Path(claude).parent))
    dirs += ["/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin"]
    seen: list[str] = []
    for d in dirs:
        if d not in seen:
            seen.append(d)
    return os.pathsep.join(seen)


def _payload(label: str, args: list[str], log_name: str, jotd_bin: str, data_dir: Path) -> dict:
    """The plist shape both job families share; the caller adds its trigger key."""
    return {
        "Label": label,
        "ProgramArguments": [jotd_bin, *args],
        "WorkingDirectory": str(data_dir),
        "StandardOutPath": str(data_dir / "state" / "logs" / log_name),
        "StandardErrorPath": str(data_dir / "state" / "logs" / log_name),
        "EnvironmentVariables": {"PATH": _env_path(jotd_bin), "JOTD_DIR": str(data_dir)},
    }


def render_plist(slot: str, hhmm: str, jotd_bin: str, data_dir: Path) -> bytes:
    hour, minute = (int(x) for x in hhmm.split(":"))
    payload = _payload(
        f"{LABEL_PREFIX}.{slot}", ["pulse", "--slot", slot], f"pulse-{slot}.log", jotd_bin, data_dir
    )
    payload["StartCalendarInterval"] = {"Hour": hour, "Minute": minute}
    return plistlib.dumps(payload)


def render_sync_plist(interval_minutes: int, jotd_bin: str, data_dir: Path) -> bytes:
    """StartInterval, not calendar slots: launchd skips missed ticks during sleep
    and fires ~one interval after bootstrap — a free sync-on-login."""
    payload = _payload(SYNC_LABEL, ["sync", "--auto"], "sync-auto.log", jotd_bin, data_dir)
    payload["StartInterval"] = int(interval_minutes) * 60
    return plistlib.dumps(payload)


def _launchctl(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["launchctl", *args], capture_output=True, text=True, check=False)


def _activate(path: Path, raw: bytes, uid: int, what: str) -> None:
    """Write, lint, and (re)bootstrap one plist into the gui domain."""
    path.write_bytes(raw)
    lint = subprocess.run(
        ["plutil", "-lint", str(path)], capture_output=True, text=True, check=False
    )
    if lint.returncode != 0:
        raise RuntimeError(f"generated plist failed lint: {lint.stdout}{lint.stderr}")
    _launchctl("bootout", f"gui/{uid}", str(path))  # tolerate "not loaded"
    boot = _launchctl("bootstrap", f"gui/{uid}", str(path))
    if boot.returncode != 0:
        raise RuntimeError(f"launchctl bootstrap failed for {what}: {boot.stderr.strip()}")


def install(data_dir: Path) -> list[str]:
    cfg = load_config(data_dir)
    jotd_bin = _jotd_bin()
    uid = os.getuid()
    launch_agents_dir().mkdir(parents=True, exist_ok=True)
    actions = []
    for slot, hhmm in cfg.slots.items():
        path = plist_path(slot)
        _activate(path, render_plist(slot, hhmm, jotd_bin, data_dir), uid, slot)
        actions.append(f"scheduled {slot} at {hhmm} ({path.name})")
    return actions


def install_sync(data_dir: Path, interval_minutes: int) -> list[str]:
    """Install the auto-sync job. Any machine, but only where a sync can work."""
    if not (data_dir / ".git").is_dir():
        return ["auto-sync skipped: data dir is not a git repository"]
    origin = subprocess.run(
        ["git", "-C", str(data_dir), "remote", "get-url", "origin"],
        capture_output=True,
        text=True,
        check=False,
    )
    if origin.returncode != 0:
        return ["auto-sync skipped: no 'origin' remote (a scheduled sync would fail every tick)"]
    jotd_bin = _jotd_bin()
    uid = os.getuid()
    launch_agents_dir().mkdir(parents=True, exist_ok=True)
    path = sync_plist_path()
    _activate(path, render_sync_plist(interval_minutes, jotd_bin, data_dir), uid, "auto-sync")
    return [f"scheduled auto-sync every {interval_minutes} min ({path.name})"]


def uninstall() -> list[str]:
    uid = os.getuid()
    actions = []
    for path in sorted(launch_agents_dir().glob(GLOB_ALL)):
        _launchctl("bootout", f"gui/{uid}", str(path))
        path.unlink()
        actions.append(f"removed {path.name}")
    return actions or ["nothing scheduled"]


def status() -> list[str]:
    uid = os.getuid()
    lines = []
    for path in sorted(launch_agents_dir().glob(GLOB_ALL)):
        label = path.stem
        out = _launchctl("print", f"gui/{uid}/{label}")
        state = "loaded" if out.returncode == 0 else "NOT loaded"
        lines.append(f"{label}: {state}")
    return lines or ["no jotd schedules installed"]
