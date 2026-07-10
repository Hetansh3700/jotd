"""Local notification delivery. The pulse's ONLY side-effect channel.

channel=macos uses terminal-notifier when installed (it can survive Focus
modes better and shows an app name), else osascript — both local, zero deps.
channel=stdout exists for tests, dry runs, and headless CI.
"""

from __future__ import annotations

import json
import shutil
import subprocess


def send(title: str, message: str, channel: str = "macos") -> str:
    """Deliver a notification; returns the mechanism used (for logs/tests)."""
    if channel == "stdout":
        print(f"[{title}] {message}")
        return "stdout"
    if channel != "macos":
        raise ValueError(f"unknown channel: {channel} (macos|stdout)")
    if shutil.which("terminal-notifier"):
        subprocess.run(
            ["terminal-notifier", "-title", title, "-message", message, "-group", "jotd"],
            check=False,
            capture_output=True,
            timeout=10,
        )
        return "terminal-notifier"
    # json.dumps produces a double-quoted, fully escaped literal — valid AppleScript string
    script = f"display notification {json.dumps(message)} with title {json.dumps(title)}"
    subprocess.run(["osascript", "-e", script], check=False, capture_output=True, timeout=10)
    return "osascript"
