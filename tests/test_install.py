import json

from typer.testing import CliRunner

from jotd import init as vinit
from jotd import install as vinstall
from jotd.cli import app

runner = CliRunner()

MARKER = vinstall.HOOK_MARKER


def _isolate(monkeypatch, tmp_path):
    claude_dir = tmp_path / "claude-user"
    monkeypatch.setattr(vinstall, "CLAUDE_USER_DIR", claude_dir)
    monkeypatch.setattr(vinstall, "SETTINGS_PATH", claude_dir / "settings.json")
    monkeypatch.setattr(vinstall, "GLOBAL_MANIFEST", tmp_path / "config" / "manifest.json")
    monkeypatch.setattr(vinstall, "_jotd_bin", lambda: "/fake/bin/jotd")
    return claude_dir


def _session_end_entries():
    settings = json.loads(vinstall.SETTINGS_PATH.read_text())
    return settings.get("hooks", {}).get("SessionEnd", [])


def test_global_templates_never_leak_into_data_dir_scaffold():
    # regression for the rglob trap: templates/global/** must be invisible to init
    assert vinstall.global_files(), "global templates missing from the package"
    for rel in vinit._template_files():
        assert "session.md" not in rel and "global" not in rel


def test_fresh_install_writes_command_and_manifest_only(tmp_path, monkeypatch):
    claude_dir = _isolate(monkeypatch, tmp_path)
    actions = vinstall.install_claude_code()
    assert (claude_dir / "commands" / "jotd" / "session.md").is_file()
    manifest = json.loads(vinstall.GLOBAL_MANIFEST.read_text())
    assert "commands/jotd/session.md" in manifest
    assert not vinstall.SETTINGS_PATH.exists()  # no --hook, settings untouched
    assert any(a.startswith("installed") for a in actions)


def test_hook_install_is_idempotent(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    vinstall.install_claude_code(hook=True)
    entries = _session_end_entries()
    assert len(entries) == 1
    hook = entries[0]["hooks"][0]
    assert MARKER in hook["command"] and hook["command"].startswith("/fake/bin/jotd")
    assert hook["timeout"] == vinstall.HOOK_TIMEOUT_S

    actions = vinstall.install_claude_code(hook=True)  # rerun
    assert len(_session_end_entries()) == 1
    assert any("already installed" in a for a in actions)


def test_hook_merge_preserves_existing_settings(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    vinstall.SETTINGS_PATH.parent.mkdir(parents=True)
    vinstall.SETTINGS_PATH.write_text(
        json.dumps(
            {
                "model": "opus",
                "hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": []}]},
            }
        )
    )
    vinstall.install_claude_code(hook=True)
    settings = json.loads(vinstall.SETTINGS_PATH.read_text())
    assert settings["model"] == "opus"
    assert settings["hooks"]["PreToolUse"] == [{"matcher": "Bash", "hooks": []}]
    assert len(settings["hooks"]["SessionEnd"]) == 1


def test_unparseable_settings_left_untouched(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    vinstall.SETTINGS_PATH.parent.mkdir(parents=True)
    vinstall.SETTINGS_PATH.write_text("{not json")
    actions = vinstall.install_claude_code(hook=True)
    assert any(a.startswith("error: cannot parse") for a in actions)
    assert vinstall.SETTINGS_PATH.read_text() == "{not json"


def test_upgrade_skips_hand_edited_command(tmp_path, monkeypatch):
    claude_dir = _isolate(monkeypatch, tmp_path)
    vinstall.install_claude_code()
    session_md = claude_dir / "commands" / "jotd" / "session.md"
    session_md.write_text(session_md.read_text() + "\nmy tweak\n")
    actions = vinstall.install_claude_code(upgrade=True)
    assert any(a.startswith("skipped commands/jotd/session.md") for a in actions)
    assert "my tweak" in session_md.read_text()


def test_upgrade_replaces_unmodified_outdated_command(tmp_path, monkeypatch):
    claude_dir = _isolate(monkeypatch, tmp_path)
    vinstall.install_claude_code()
    session_md = claude_dir / "commands" / "jotd" / "session.md"
    session_md.write_text("old template\n")
    manifest = json.loads(vinstall.GLOBAL_MANIFEST.read_text())
    manifest["commands/jotd/session.md"] = vinit._sha(b"old template\n")
    vinstall.GLOBAL_MANIFEST.write_text(json.dumps(manifest))
    actions = vinstall.install_claude_code(upgrade=True)
    assert any(a.startswith("upgraded commands/jotd/session.md") for a in actions)
    assert "old template" not in session_md.read_text()


def test_uninstall_removes_files_hook_and_manifest(tmp_path, monkeypatch):
    claude_dir = _isolate(monkeypatch, tmp_path)
    vinstall.SETTINGS_PATH.parent.mkdir(parents=True)
    vinstall.SETTINGS_PATH.write_text(json.dumps({"model": "opus"}))
    vinstall.install_claude_code(hook=True)
    actions = vinstall.uninstall_claude_code()
    assert not (claude_dir / "commands" / "jotd").exists()  # file gone, dir pruned
    assert not vinstall.GLOBAL_MANIFEST.exists()
    settings = json.loads(vinstall.SETTINGS_PATH.read_text())
    assert "hooks" not in settings and settings["model"] == "opus"
    assert any(a.startswith("removed commands/jotd/session.md") for a in actions)


def test_uninstall_keeps_hand_edited_file_and_its_manifest_entry(tmp_path, monkeypatch):
    claude_dir = _isolate(monkeypatch, tmp_path)
    vinstall.install_claude_code()
    session_md = claude_dir / "commands" / "jotd" / "session.md"
    session_md.write_text("precious hand edits\n")
    actions = vinstall.uninstall_claude_code()
    assert session_md.read_text() == "precious hand edits\n"
    assert any(a.startswith("kept commands/jotd/session.md") for a in actions)
    assert "commands/jotd/session.md" in json.loads(vinstall.GLOBAL_MANIFEST.read_text())


def test_uninstall_preserves_unrelated_session_end_hooks(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    vinstall.SETTINGS_PATH.parent.mkdir(parents=True)
    other = {"hooks": [{"type": "command", "command": "say goodbye"}]}
    vinstall.SETTINGS_PATH.write_text(json.dumps({"hooks": {"SessionEnd": [other]}}))
    vinstall.install_claude_code(hook=True)
    assert len(_session_end_entries()) == 2
    vinstall.uninstall_claude_code()
    assert _session_end_entries() == [other]


def test_cli_rejects_unknown_target(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    for verb in ("install", "uninstall"):
        result = runner.invoke(app, [verb, "vscode"])
        assert result.exit_code == 2
        assert "unknown install target" in result.output


def test_cli_install_happy_path(tmp_path, monkeypatch):
    claude_dir = _isolate(monkeypatch, tmp_path)
    result = runner.invoke(app, ["install", "claude-code"])
    assert result.exit_code == 0, result.output
    assert (claude_dir / "commands" / "jotd" / "session.md").is_file()
