import json
from datetime import date
from pathlib import Path

import pytest

from vault.feedback import respond
from vault.inbox import VaultError

TODAY = date(2026, 7, 8)


def make_vault(tmp_path: Path) -> Path:
    (tmp_path / "vault.toml").write_text("")
    (tmp_path / "state").mkdir()
    projects = tmp_path / "notes" / "projects"
    projects.mkdir(parents=True)
    (projects / "atlas.md").write_text(
        "---\ntype: project\ntitle: Atlas\naliases: []\ncreated: 2026-06-01\n---\n"
        "## Open loops\n"
        "- [ ] send the q3 numbers <!-- loop:cap-20260701-090000-aaaa1111 -->\n"
        "- [ ] write the postmortem <!-- loop:cap-20260703-090000-bbbb2222 -->\n"
    )
    return tmp_path


def loop_status(vault, loop_id):
    loops = json.loads((vault / "state" / "open-loops.json").read_text())["loops"]
    return next(lp["status"] for lp in loops if lp["id"] == loop_id)


def test_done_flips_checkbox_and_folds(tmp_path):
    vault = make_vault(tmp_path)
    message = respond(vault, "aaaa1111", "done", today=TODAY)
    assert "done: send the q3 numbers" in message
    note = (vault / "notes" / "projects" / "atlas.md").read_text()
    assert "- [x] send the q3 numbers" in note
    assert loop_status(vault, "cap-20260701-090000-aaaa1111") == "done"


def test_snooze_until_config_days(tmp_path):
    vault = make_vault(tmp_path)
    message = respond(vault, "bbbb2222", "snooze", today=TODAY)  # default 3 days
    assert "until 2026-07-11" in message
    assert loop_status(vault, "cap-20260703-090000-bbbb2222") == "snoozed"


def test_two_drops_silence_permanently(tmp_path):
    vault = make_vault(tmp_path)
    first = respond(vault, "bbbb2222", "drop", today=TODAY)
    assert "never mention" not in first
    second = respond(vault, "bbbb2222", "drop", today=TODAY)
    assert "never mention it again" in second
    assert loop_status(vault, "cap-20260703-090000-bbbb2222") == "silenced"


def test_ambiguous_fragment_lists_candidates(tmp_path):
    vault = make_vault(tmp_path)
    with pytest.raises(VaultError, match="ambiguous"):
        respond(vault, "cap-2026070", "drop", today=TODAY)


def test_unknown_fragment_errors(tmp_path):
    vault = make_vault(tmp_path)
    with pytest.raises(VaultError, match="no open loop"):
        respond(vault, "zzzz", "done", today=TODAY)
