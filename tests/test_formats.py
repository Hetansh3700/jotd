from datetime import datetime

import pytest

from vault.formats import (
    CAPTURE_ID_RE,
    MAX_CAPTURE_BYTES,
    dump_capture_line,
    format_loop_line,
    format_processed_line,
    new_capture,
    parse_capture_line,
    parse_loop_line,
    parse_processed_line,
)

NOW = datetime(2026, 7, 8, 14, 32, 5)


def test_capture_roundtrip():
    rec = new_capture("call sarah", now=NOW, rand_hex="3f2a99", context={"cwd": "~/x"})
    assert CAPTURE_ID_RE.match(rec["id"])
    assert rec["id"] == "cap-20260708-143205-3f2a"
    line = dump_capture_line(rec)
    assert line.endswith("\n") and line.count("\n") == 1
    assert parse_capture_line(line) == rec


def test_capture_oversize_rejected_never_truncated():
    rec = new_capture("x" * MAX_CAPTURE_BYTES, now=NOW, rand_hex="abcd")
    with pytest.raises(ValueError, match="exceeds"):
        dump_capture_line(rec)


def test_processed_line_roundtrip():
    line = format_processed_line(
        "cap-20260708-143205-3f2a",
        ["notes/people/sarah-chen.md", "notes/projects/atlas.md"],
        "2026-07-08T14:35:00-07:00",
    )
    cap_id, paths, ts = parse_processed_line(line)
    assert cap_id == "cap-20260708-143205-3f2a"
    assert paths == ["notes/people/sarah-chen.md", "notes/projects/atlas.md"]
    assert ts == "2026-07-08T14:35:00-07:00"


def test_processed_line_rejects_spaces_and_empty():
    with pytest.raises(ValueError):
        format_processed_line("cap-x", [], "ts")
    with pytest.raises(ValueError):
        format_processed_line("cap-x", ["notes/a b.md"], "ts")


def test_loop_line_roundtrip():
    line = format_loop_line("send the numbers", "cap-20260708-143205-3f2a")
    parsed = parse_loop_line(line)
    assert parsed == {
        "id": "cap-20260708-143205-3f2a",
        "text": "send the numbers",
        "state": "open",
        "indent": "",
    }
    done = format_loop_line("send the numbers", "l-8b12aa", done=True, indent="  ")
    parsed = parse_loop_line(done)
    assert parsed["state"] == "done" and parsed["indent"] == "  "


def test_unstamped_checkbox_is_not_a_loop():
    assert parse_loop_line("- [ ] no stamp here") is None
    assert parse_loop_line("plain text") is None
