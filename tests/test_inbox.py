import threading
from datetime import datetime

import pytest

from vault import inbox
from vault.formats import CAPTURE_ID_RE, MAX_CAPTURE_BYTES, parse_capture_line


def test_append_creates_monthly_jsonl(tmp_path):
    now = datetime(2026, 7, 8, 14, 32, 5).astimezone()
    record = inbox.append_capture(tmp_path, "  call sarah  ", now=now)
    assert CAPTURE_ID_RE.match(record["id"])
    assert record["text"] == "call sarah"
    path = tmp_path / "inbox" / "2026-07.jsonl"
    lines = path.read_text().splitlines()
    assert len(lines) == 1
    assert parse_capture_line(lines[0]) == record


def test_oversize_rejected_and_nothing_written(tmp_path):
    with pytest.raises(ValueError, match="exceeds"):
        inbox.append_capture(tmp_path, "x" * MAX_CAPTURE_BYTES)
    assert not list((tmp_path / "inbox").glob("*.jsonl")) or not any(
        f.read_text() for f in (tmp_path / "inbox").glob("*.jsonl")
    )


def test_empty_capture_rejected(tmp_path):
    with pytest.raises(inbox.VaultError, match="empty"):
        inbox.append_capture(tmp_path, "   ")


def test_concurrent_appends_interleave_at_line_granularity(tmp_path):
    n_threads, per_thread = 8, 25

    def worker(t):
        for i in range(per_thread):
            inbox.append_capture(tmp_path, f"thread {t} capture {i}")

    threads = [threading.Thread(target=worker, args=(t,)) for t in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    records = inbox.iter_captures(tmp_path)  # raises if any line is torn
    assert len(records) == n_threads * per_thread
    assert len({r["id"] for r in records}) == n_threads * per_thread


def test_unprocessed_is_set_difference(tmp_path):
    a = inbox.append_capture(tmp_path, "first")
    b = inbox.append_capture(tmp_path, "second")
    note = tmp_path / "notes" / "topics" / "unsorted.md"
    note.parent.mkdir(parents=True)
    note.write_text("stub")
    inbox.mark_processed(tmp_path, a["id"], ["notes/topics/unsorted.md"])
    remaining = inbox.unprocessed(tmp_path)
    assert [r["id"] for r in remaining] == [b["id"]]


def test_mark_processed_validations(tmp_path):
    rec = inbox.append_capture(tmp_path, "hello")
    with pytest.raises(inbox.VaultError, match="unknown capture id"):
        inbox.mark_processed(tmp_path, "cap-20990101-000000-dead", ["notes/x.md"])
    with pytest.raises(inbox.VaultError, match="does not exist"):
        inbox.mark_processed(tmp_path, rec["id"], ["notes/people/ghost.md"])
    with pytest.raises(inbox.VaultError, match="under notes/"):
        inbox.mark_processed(tmp_path, rec["id"], ["state/processed.log"])

    note = tmp_path / "notes" / "people" / "sarah.md"
    note.parent.mkdir(parents=True)
    note.write_text("x")
    inbox.mark_processed(tmp_path, rec["id"], ["notes/people/sarah.md"])
    with pytest.raises(inbox.VaultError, match="already processed"):
        inbox.mark_processed(tmp_path, rec["id"], ["notes/people/sarah.md"])
