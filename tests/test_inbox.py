import threading
from datetime import datetime

import pytest

from jotd import inbox
from jotd.formats import CAPTURE_ID_RE, MAX_CAPTURE_BYTES, parse_capture_line


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
    with pytest.raises(inbox.JotdError, match="empty"):
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


def test_concurrent_processes_append(tmp_path):
    """True cross-process O_APPEND proof: parallel `jotd` console-script
    subprocesses (the screen client's write path) interleave at line
    granularity with unique ids — the thread test can't prove this."""
    import subprocess
    import sys
    from pathlib import Path

    (tmp_path / "jotd.toml").write_text("")
    jotd_bin = Path(sys.executable).parent / "jotd"
    procs = [
        subprocess.Popen(
            [str(jotd_bin), "capture", f"probe {i}", "--method", "region", "--dir", str(tmp_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        for i in range(8)
    ]
    for p in procs:
        assert p.wait(timeout=30) == 0, p.stderr.read()
    records = inbox.iter_captures(tmp_path)  # raises if any line is torn
    assert len(records) == 8
    assert len({r["id"] for r in records}) == 8
    assert all(r["context"] == {"method": "region"} for r in records)


def test_authored_capture_gets_per_author_file_and_field(tmp_path):
    now = datetime(2026, 7, 8, 14, 32, 5).astimezone()
    record = inbox.append_capture(tmp_path, "team thought", author="ana", now=now)
    assert record["author"] == "ana"
    path = tmp_path / "inbox" / "2026-07.ana.jsonl"
    assert parse_capture_line(path.read_text().splitlines()[0]) == record
    assert not (tmp_path / "inbox" / "2026-07.jsonl").exists()


def test_mixed_legacy_and_authored_files_read_together(tmp_path):
    now = datetime(2026, 7, 8, 14, 32, 5).astimezone()
    legacy = inbox.append_capture(tmp_path, "old style", now=now)
    a = inbox.append_capture(tmp_path, "from ana", author="ana", now=now)
    b = inbox.append_capture(tmp_path, "from ben", author="ben", now=now)
    assert len(list((tmp_path / "inbox").glob("*.jsonl"))) == 3
    ids = {r["id"] for r in inbox.iter_captures(tmp_path)}
    assert ids == {legacy["id"], a["id"], b["id"]}

    note = tmp_path / "notes" / "topics" / "unsorted.md"
    note.parent.mkdir(parents=True)
    note.write_text("stub")
    inbox.mark_processed(tmp_path, a["id"], ["notes/topics/unsorted.md"])
    assert {r["id"] for r in inbox.unprocessed(tmp_path)} == {legacy["id"], b["id"]}


def test_invalid_author_rejected_nothing_written(tmp_path):
    with pytest.raises(ValueError, match="slug"):
        inbox.append_capture(tmp_path, "hello", author="Bob Smith")
    assert not list((tmp_path / "inbox").glob("*.jsonl"))


def test_concurrent_authored_appends_share_one_file(tmp_path):
    n_threads, per_thread = 4, 25

    def worker(t):
        for i in range(per_thread):
            inbox.append_capture(tmp_path, f"t{t} c{i}", author="ana")

    threads = [threading.Thread(target=worker, args=(t,)) for t in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    files = list((tmp_path / "inbox").glob("*.jsonl"))
    assert len(files) == 1 and ".ana." in files[0].name
    records = inbox.iter_captures(tmp_path)  # raises if any line is torn
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
    with pytest.raises(inbox.JotdError, match="unknown capture id"):
        inbox.mark_processed(tmp_path, "cap-20990101-000000-dead", ["notes/x.md"])
    with pytest.raises(inbox.JotdError, match="does not exist"):
        inbox.mark_processed(tmp_path, rec["id"], ["notes/people/ghost.md"])
    with pytest.raises(inbox.JotdError, match="under notes/"):
        inbox.mark_processed(tmp_path, rec["id"], ["state/processed.log"])

    note = tmp_path / "notes" / "people" / "sarah.md"
    note.parent.mkdir(parents=True)
    note.write_text("x")
    inbox.mark_processed(tmp_path, rec["id"], ["notes/people/sarah.md"])
    with pytest.raises(inbox.JotdError, match="already processed"):
        inbox.mark_processed(tmp_path, rec["id"], ["notes/people/sarah.md"])
