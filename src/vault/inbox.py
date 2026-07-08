"""The append-only inbox and the processed pointer log.

This module is the ONLY writer for inbox/*.jsonl and state/processed.log.
Both writes are single O_APPEND syscalls of one newline-terminated line, so
concurrent captures interleave at line granularity and nothing ever rewrites
history. Agents reach these files exclusively through `vault add`,
`vault unprocessed`, and `vault mark-processed`.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from vault.formats import (
    dump_capture_line,
    format_processed_line,
    new_capture,
    parse_capture_line,
    parse_processed_line,
)


class VaultError(Exception):
    pass


def _append_line(path: Path, line: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o644)
    try:
        os.write(fd, line.encode("utf-8"))
    finally:
        os.close(fd)


def append_capture(
    data_dir: Path,
    text: str,
    *,
    source: str = "cli",
    context: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    text = text.strip()
    if not text:
        raise VaultError("empty capture")
    now = now or datetime.now().astimezone()
    record = new_capture(text, now=now, rand_hex=uuid.uuid4().hex, source=source, context=context)
    line = dump_capture_line(record)  # raises on oversize BEFORE anything is written
    _append_line(data_dir / "inbox" / f"{now.strftime('%Y-%m')}.jsonl", line)
    return record


def iter_captures(data_dir: Path) -> list[dict[str, Any]]:
    records = []
    inbox = data_dir / "inbox"
    for path in sorted(inbox.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                records.append(parse_capture_line(line))
    return records


def processed_entries(data_dir: Path) -> dict[str, list[str]]:
    log = data_dir / "state" / "processed.log"
    entries: dict[str, list[str]] = {}
    if log.is_file():
        for line in log.read_text(encoding="utf-8").splitlines():
            if line.strip():
                cap_id, paths, _ts = parse_processed_line(line)
                entries.setdefault(cap_id, paths)
    return entries


def unprocessed(data_dir: Path) -> list[dict[str, Any]]:
    done = processed_entries(data_dir)
    return [r for r in iter_captures(data_dir) if r["id"] not in done]


def mark_processed(data_dir: Path, capture_id: str, paths: list[str]) -> None:
    known = {r["id"] for r in iter_captures(data_dir)}
    if capture_id not in known:
        raise VaultError(f"unknown capture id: {capture_id}")
    if capture_id in processed_entries(data_dir):
        raise VaultError(f"already processed: {capture_id}")
    for p in paths:
        if not p.startswith("notes/"):
            raise VaultError(f"routed path must live under notes/: {p}")
        if not (data_dir / p).is_file():
            raise VaultError(f"routed path does not exist (write the note first): {p}")
    ts = datetime.now().astimezone().isoformat(timespec="seconds")
    _append_line(data_dir / "state" / "processed.log", format_processed_line(capture_id, paths, ts))
