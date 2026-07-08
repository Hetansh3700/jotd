"""launchd scheduling for the pulse (macOS).

`vault schedule install` writes one plist per slot into ~/Library/LaunchAgents
and bootstraps them into the user's gui domain — the same domain that owns the
login keychain, which the claude CLI needs for headless auth.
"""

from __future__ import annotations

import os
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

from vault.config import load_config

LABEL_PREFIX = "com.vault.pulse"


def launch_agents_dir() -> Path:
    return Path.home() / "Library" / "LaunchAgents"


def plist_path(slot: str) -> Path:
    return launch_agents_dir() / f"{LABEL_PREFIX}.{slot}.plist"


def _vault_bin() -> str:
    sibling = Path(sys.executable).parent / "vault"
    if sibling.is_file():
        return str(sibling)
    found = shutil.which("vault")
    if not found:
        raise RuntimeError("cannot resolve the vault binary for the plist")
    return found


def _env_path(vault_bin: str) -> str:
    dirs = [str(Path(vault_bin).parent)]
    claude = shutil.which("claude")
    if claude:
        dirs.append(str(Path(claude).parent))
    dirs += ["/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin"]
    seen: list[str] = []
    for d in dirs:
        if d not in seen:
            seen.append(d)
    return os.pathsep.join(seen)


def render_plist(slot: str, hhmm: str, vault_bin: str, data_dir: Path) -> bytes:
    hour, minute = (int(x) for x in hhmm.split(":"))
    payload = {
        "Label": f"{LABEL_PREFIX}.{slot}",
        "ProgramArguments": [vault_bin, "pulse", "--slot", slot],
        "StartCalendarInterval": {"Hour": hour, "Minute": minute},
        "WorkingDirectory": str(data_dir),
        "StandardOutPath": str(data_dir / "state" / "logs" / f"pulse-{slot}.log"),
        "StandardErrorPath": str(data_dir / "state" / "logs" / f"pulse-{slot}.log"),
        "EnvironmentVariables": {"PATH": _env_path(vault_bin), "VAULT_DIR": str(data_dir)},
    }
    return plistlib.dumps(payload)


def _launchctl(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["launchctl", *args], capture_output=True, text=True, check=False)


def install(data_dir: Path) -> list[str]:
    cfg = load_config(data_dir)
    vault_bin = _vault_bin()
    uid = os.getuid()
    launch_agents_dir().mkdir(parents=True, exist_ok=True)
    actions = []
    for slot, hhmm in cfg.slots.items():
        path = plist_path(slot)
        path.write_bytes(render_plist(slot, hhmm, vault_bin, data_dir))
        lint = subprocess.run(
            ["plutil", "-lint", str(path)], capture_output=True, text=True, check=False
        )
        if lint.returncode != 0:
            raise RuntimeError(f"generated plist failed lint: {lint.stdout}{lint.stderr}")
        _launchctl("bootout", f"gui/{uid}", str(path))  # tolerate "not loaded"
        boot = _launchctl("bootstrap", f"gui/{uid}", str(path))
        if boot.returncode != 0:
            raise RuntimeError(f"launchctl bootstrap failed for {slot}: {boot.stderr.strip()}")
        actions.append(f"scheduled {slot} at {hhmm} ({path.name})")
    return actions


def uninstall() -> list[str]:
    uid = os.getuid()
    actions = []
    for path in sorted(launch_agents_dir().glob(f"{LABEL_PREFIX}.*.plist")):
        _launchctl("bootout", f"gui/{uid}", str(path))
        path.unlink()
        actions.append(f"removed {path.name}")
    return actions or ["nothing scheduled"]


def status() -> list[str]:
    uid = os.getuid()
    lines = []
    for path in sorted(launch_agents_dir().glob(f"{LABEL_PREFIX}.*.plist")):
        label = path.stem
        out = _launchctl("print", f"gui/{uid}/{label}")
        state = "loaded" if out.returncode == 0 else "NOT loaded"
        lines.append(f"{label}: {state}")
    return lines or ["no pulse schedules installed"]
