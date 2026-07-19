import json
from datetime import datetime

import pytest

from jotd import author as vauthor
from jotd.formats import dump_capture_line, new_capture, parse_capture_line


def test_slugify_cases():
    assert vauthor.slugify("Dev") == "dev"
    assert vauthor.slugify("Sarah Chen") == "sarah-chen"
    assert vauthor.slugify("宇宙") == ""  # non-Latin slugs to empty → caller falls through
    assert vauthor.slugify("--a---b--") == "a-b"
    assert vauthor.slugify("x" * 100) == "x" * vauthor.MAX_AUTHOR_CHARS
    assert vauthor.slugify("A" * 31 + "-junk")[-1] != "-"  # cap never leaves a trailing hyphen


@pytest.fixture()
def isolated(monkeypatch, tmp_path):
    """No machine identity leaks into resolution: every layer starts empty."""
    monkeypatch.delenv("JOTD_AUTHOR", raising=False)
    monkeypatch.setattr(vauthor, "AUTHOR_FILE", tmp_path / "author")
    monkeypatch.setattr(vauthor, "_git_user_name", lambda: "")
    monkeypatch.setattr(vauthor, "_os_user", lambda: "")
    return tmp_path


def test_precedence_flag_env_file_git_os(isolated, monkeypatch):
    monkeypatch.setattr(vauthor, "_os_user", lambda: "Os User")
    assert vauthor.resolve_author_with_rule(None) == ("os-user", "OS username")

    monkeypatch.setattr(vauthor, "_git_user_name", lambda: "Git Person")
    assert vauthor.resolve_author_with_rule(None) == ("git-person", "git config user.name")

    vauthor.AUTHOR_FILE.write_text("File Person\n")
    slug, rule = vauthor.resolve_author_with_rule(None)
    assert slug == "file-person" and rule == str(vauthor.AUTHOR_FILE)

    monkeypatch.setenv("JOTD_AUTHOR", "Env Person")
    assert vauthor.resolve_author(None) == "env-person"

    assert vauthor.resolve_author("Flag Person") == "flag-person"


def test_empty_layers_fall_through_to_terminal_fallback(isolated):
    slug, rule = vauthor.resolve_author_with_rule(None)
    assert slug == "user" and "fallback" in rule


def test_non_latin_flag_falls_through(isolated, monkeypatch):
    monkeypatch.setenv("JOTD_AUTHOR", "dev")
    assert vauthor.resolve_author("宇宙") == "dev"


def test_authored_record_roundtrip_and_key_order():
    now = datetime(2026, 7, 19, 10, 0, 0).astimezone()
    rec = new_capture(
        "hello", now=now, rand_hex="deadbeefcafe", author="ana", context={"method": "region"}
    )
    line = dump_capture_line(rec)
    assert parse_capture_line(line) == rec
    assert list(json.loads(line)) == ["id", "ts", "text", "source", "author", "context"]


def test_invalid_author_slug_rejected_before_write():
    now = datetime(2026, 7, 19, 10, 0, 0).astimezone()
    for bad in ("Bob Smith", "UPPER", "-lead-hyphen", "a" * 33):
        with pytest.raises(ValueError, match="slug"):
            new_capture("x", now=now, rand_hex="deadbeefcafe", author=bad)
