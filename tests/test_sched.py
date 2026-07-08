import plistlib
import subprocess
import sys
from pathlib import Path

import pytest

from vault.sched import render_plist


def test_plist_roundtrips_and_carries_the_contract(tmp_path):
    raw = render_plist("morning", "09:00", "/usr/local/bin/vault", Path("/Users/x/vault"))
    payload = plistlib.loads(raw)
    assert payload["Label"] == "com.vault.pulse.morning"
    assert payload["ProgramArguments"][:4] == ["/usr/local/bin/vault", "pulse", "--slot", "morning"]
    assert payload["StartCalendarInterval"] == {"Hour": 9, "Minute": 0}
    assert payload["WorkingDirectory"] == "/Users/x/vault"
    assert payload["EnvironmentVariables"]["VAULT_DIR"] == "/Users/x/vault"
    assert "/usr/bin" in payload["EnvironmentVariables"]["PATH"]
    assert payload["StandardOutPath"].endswith("state/logs/pulse-morning.log")


@pytest.mark.skipif(sys.platform != "darwin", reason="plutil is macOS-only")
def test_generated_plist_passes_plutil_lint(tmp_path):
    path = tmp_path / "test.plist"
    path.write_bytes(render_plist("evening", "17:30", "/usr/local/bin/vault", tmp_path))
    proc = subprocess.run(["plutil", "-lint", str(path)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr
