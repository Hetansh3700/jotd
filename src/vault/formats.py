"""Format contracts shared by the capture writer, the grader, and state derivation.

Everything here is deterministic and LLM-free. These grammars are the product's
stable surface: agents are prompted against them, the grader enforces them, and
`derive` rebuilds all of `state/` from them. Change them only with a DECISIONS.md
entry and a golden refresh.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

# A single capture may not exceed this many bytes once serialized (one JSONL line).
# Oversize captures are rejected, never truncated — silent truncation corrupts provenance.
MAX_CAPTURE_BYTES = 4096

# 8 hex chars of randomness: burst captures share the timestamp second, and the
# suffix alone must keep birthday collisions negligible (4 hex ≈ 30% at 200/s).
CAPTURE_ID_RE = re.compile(r"^cap-\d{8}-\d{6}-[0-9a-f]{8}$")

# Loop lines inside notes:  - [ ] text <!-- loop:ID -->   (or "- [x]" once done).
# ID is either the capture id that spawned the loop (stamped by the librarian) or
# an l-<6hex> id stamped by `vault derive` for hand-written loops.
LOOP_LINE_RE = re.compile(
    r"^(?P<indent>\s*)- \[(?P<state>[ x])\] (?P<text>.*?)\s*<!-- loop:(?P<id>[\w-]+) -->\s*$"
)
UNSTAMPED_LOOP_RE = re.compile(r"^(?P<indent>\s*)- \[(?P<state>[ x])\] (?P<text>.*?)\s*$")

# processed.log lines:  <capture-id> <path[,path...]> <iso-ts>
# Paths are vault-relative (notes/...), comma-separated, no spaces inside the field.
PROCESSED_LINE_RE = re.compile(r"^(?P<id>cap-[\w-]+) (?P<paths>\S+) (?P<ts>\S+)$")


def new_capture_id(now: datetime, rand_hex: str) -> str:
    return f"cap-{now.strftime('%Y%m%d-%H%M%S')}-{rand_hex[:8]}"


def new_capture(
    text: str,
    *,
    now: datetime,
    rand_hex: str,
    source: str = "cli",
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "id": new_capture_id(now, rand_hex),
        "ts": now.isoformat(timespec="seconds"),
        "text": text,
        "source": source,
    }
    if context:
        record["context"] = context
    return record


def dump_capture_line(record: dict[str, Any]) -> str:
    """Serialize a capture to its single JSONL line (newline included)."""
    line = json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
    if len(line.encode("utf-8")) > MAX_CAPTURE_BYTES:
        raise ValueError(
            f"capture exceeds {MAX_CAPTURE_BYTES} bytes serialized; "
            "split it or point at a file instead"
        )
    return line


def parse_capture_line(line: str) -> dict[str, Any]:
    record = json.loads(line)
    if not isinstance(record, dict) or "id" not in record or "text" not in record:
        raise ValueError(f"malformed capture line: {line[:80]!r}")
    return record


def format_processed_line(capture_id: str, paths: list[str], ts: str) -> str:
    if not paths:
        raise ValueError("mark-processed requires at least one routed path")
    joined = ",".join(paths)
    if " " in joined:
        raise ValueError(f"routed paths may not contain spaces: {joined!r}")
    return f"{capture_id} {joined} {ts}\n"


def parse_processed_line(line: str) -> tuple[str, list[str], str]:
    m = PROCESSED_LINE_RE.match(line.strip())
    if not m:
        raise ValueError(f"malformed processed.log line: {line[:80]!r}")
    return m.group("id"), m.group("paths").split(","), m.group("ts")


def parse_loop_line(line: str) -> dict[str, str] | None:
    """Return {id, text, state, indent} for a stamped loop line, else None."""
    m = LOOP_LINE_RE.match(line)
    if not m:
        return None
    return {
        "id": m.group("id"),
        "text": m.group("text"),
        "state": "done" if m.group("state") == "x" else "open",
        "indent": m.group("indent"),
    }


def format_loop_line(text: str, loop_id: str, *, done: bool = False, indent: str = "") -> str:
    box = "x" if done else " "
    return f"{indent}- [{box}] {text} <!-- loop:{loop_id} -->"
