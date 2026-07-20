"""The shared one-shot invoker: argv construction is the security surface."""

import json
import subprocess

from jotd import headless


def _capture_run(monkeypatch, result="ok"):
    seen: dict = {}

    def fake_run(cmd, **kwargs):
        seen["cmd"] = cmd
        seen["kwargs"] = kwargs
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps({"result": result}), stderr="")

    monkeypatch.setattr(headless.shutil, "which", lambda name: f"/fake/bin/{name}")
    monkeypatch.setattr(headless.subprocess, "run", fake_run)
    return seen


def test_permission_mode_lands_in_argv(tmp_path, monkeypatch):
    seen = _capture_run(monkeypatch)
    headless.invoke_claude(
        "/organize",
        cwd=tmp_path,
        model="sonnet",
        allowed_tools=("Bash(jotd unprocessed:*)",),
        disallowed_tools=(),
        permission_mode="acceptEdits",
    )
    cmd = seen["cmd"]
    i = cmd.index("--permission-mode")
    assert cmd[i + 1] == "acceptEdits"
    assert "--disallowedTools" not in cmd  # empty tuple must not emit the flag


def test_permission_mode_absent_keeps_argv_unchanged(tmp_path, monkeypatch):
    seen = _capture_run(monkeypatch)
    headless.invoke_claude("hi", cwd=tmp_path, model="sonnet")
    cmd = seen["cmd"]
    assert "--permission-mode" not in cmd
    assert "--disallowedTools" in cmd  # defaults still apply
    for tool in headless.DEFAULT_DISALLOWED_TOOLS:
        assert tool in cmd
