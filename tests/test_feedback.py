import json
from datetime import date
from pathlib import Path

import pytest

from jotd.feedback import respond
from jotd.inbox import JotdError

TODAY = date(2026, 7, 8)


def make_jotd_dir(tmp_path: Path) -> Path:
    (tmp_path / "jotd.toml").write_text("")
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


def loop_status(jotd_dir, loop_id):
    loops = json.loads((jotd_dir / "state" / "open-loops.json").read_text())["loops"]
    return next(lp["status"] for lp in loops if lp["id"] == loop_id)


def test_done_flips_checkbox_and_folds(tmp_path):
    jotd_dir = make_jotd_dir(tmp_path)
    message = respond(jotd_dir, "aaaa1111", "done", today=TODAY)
    assert "done: send the q3 numbers" in message
    note = (jotd_dir / "notes" / "projects" / "atlas.md").read_text()
    assert "- [x] send the q3 numbers" in note
    assert loop_status(jotd_dir, "cap-20260701-090000-aaaa1111") == "done"


def test_snooze_until_config_days(tmp_path):
    jotd_dir = make_jotd_dir(tmp_path)
    message = respond(jotd_dir, "bbbb2222", "snooze", today=TODAY)  # default 3 days
    assert "until 2026-07-11" in message
    assert loop_status(jotd_dir, "cap-20260703-090000-bbbb2222") == "snoozed"


def test_two_drops_silence_permanently(tmp_path):
    jotd_dir = make_jotd_dir(tmp_path)
    first = respond(jotd_dir, "bbbb2222", "drop", today=TODAY)
    assert "never mention" not in first
    second = respond(jotd_dir, "bbbb2222", "drop", today=TODAY)
    assert "never mention it again" in second
    assert loop_status(jotd_dir, "cap-20260703-090000-bbbb2222") == "silenced"


def test_ambiguous_fragment_lists_candidates(tmp_path):
    jotd_dir = make_jotd_dir(tmp_path)
    with pytest.raises(JotdError, match="ambiguous"):
        respond(jotd_dir, "cap-2026070", "drop", today=TODAY)


def test_unknown_fragment_errors(tmp_path):
    jotd_dir = make_jotd_dir(tmp_path)
    with pytest.raises(JotdError, match="no open loop"):
        respond(jotd_dir, "zzzz", "done", today=TODAY)
