import json

from jotd import init as vinit


def _isolate_pointer(monkeypatch, tmp_path):
    pointer = tmp_path / "pointer" / "dir"
    monkeypatch.setattr(vinit, "POINTER_FILE", pointer)
    return pointer


def test_scaffold_creates_full_tree(tmp_path, monkeypatch):
    _isolate_pointer(monkeypatch, tmp_path)
    target = tmp_path / "v"
    actions = vinit.scaffold(target, git=False)
    for expected in [
        "jotd.toml",
        "CLAUDE.md",
        ".gitignore",
        ".claude/settings.json",
        ".claude/commands/capture.md",
        "notes/topics/unsorted.md",
        "inbox",
        "state/briefs",
        "state/logs",
    ]:
        assert (target / expected).exists(), expected
    assert not (target / ".git").exists()
    manifest = json.loads((target / vinit.MANIFEST).read_text())
    assert "jotd.toml" in manifest and "CLAUDE.md" in manifest
    assert any(a.startswith("installed") for a in actions)


def test_upgrade_skips_hand_edited_files(tmp_path, monkeypatch):
    _isolate_pointer(monkeypatch, tmp_path)
    target = tmp_path / "v"
    vinit.scaffold(target, git=False)
    claude_md = target / "CLAUDE.md"
    claude_md.write_text(claude_md.read_text() + "\n## My personal additions\n")
    actions = vinit.scaffold(target, git=False, upgrade=True)
    assert any(a.startswith("skipped CLAUDE.md") for a in actions)
    assert "My personal additions" in claude_md.read_text()


def test_upgrade_replaces_unmodified_outdated_files(tmp_path, monkeypatch):
    _isolate_pointer(monkeypatch, tmp_path)
    target = tmp_path / "v"
    vinit.scaffold(target, git=False)
    # simulate an older template version: installed content differs from the
    # packaged template but matches the manifest hash (user never touched it)
    claude_md = target / "CLAUDE.md"
    claude_md.write_text("old template body\n")
    manifest_path = target / vinit.MANIFEST
    manifest = json.loads(manifest_path.read_text())
    manifest["CLAUDE.md"] = vinit._sha(b"old template body\n")
    manifest_path.write_text(json.dumps(manifest))

    actions = vinit.scaffold(target, git=False, upgrade=True)
    assert any(a.startswith("upgraded CLAUDE.md") for a in actions)
    assert "old template body" not in claude_md.read_text()


def test_pointer_written_once_then_respected(tmp_path, monkeypatch):
    pointer = _isolate_pointer(monkeypatch, tmp_path)
    first, second = tmp_path / "one", tmp_path / "two"
    vinit.scaffold(first, git=False)
    assert pointer.read_text().strip() == str(first.resolve())
    actions = vinit.scaffold(second, git=False)
    assert pointer.read_text().strip() == str(first.resolve())
    assert any("--set-default" in a for a in actions)
    vinit.scaffold(second, git=False, set_default=True)
    assert pointer.read_text().strip() == str(second.resolve())
