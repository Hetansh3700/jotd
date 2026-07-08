"""state/pulse-log.md — the append-only event source behind the pulse.

One line per decision, human-readable AND regex-parseable. The spec's headline
artifact is "an agent that logs why it chose silence": suppress events carry a
reason just like nudges do. This module is the ONLY writer (the pulse runner
and the feedback CLI call into it); agents are denied write access to state/.

Grammar (one event per line, after an optional '# ...' header):
  - <ts> nudge <loop-id> "<text>" reason="<why now>"
  - <ts> suppress <loop-id> reason="<why not>"
  - <ts> response <loop-id> done|snooze|drop [until=YYYY-MM-DD] via=<cli|...>
  - <ts> heartbeat slot=<slot> status=<ok|error|skipped> nudges=<n> suppressed=<n> [err="..."]
"""

from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

from vault.inbox import _append_line

HEADER = (
    "# pulse log — one line per decision, including decisions to stay silent.\n"
    "# Written by `vault pulse` and `vault done|snooze|drop`. Do not hand-edit.\n"
)

_PREFIX = re.compile(r"^- (?P<ts>\S+) (?P<kind>nudge|suppress|response|heartbeat) (?P<rest>.*)$")
_NUDGE = re.compile(r'^(?P<id>\S+) "(?P<text>[^"]*)" reason="(?P<reason>[^"]*)"$')
_SUPPRESS = re.compile(r'^(?P<id>\S+) reason="(?P<reason>[^"]*)"$')
_RESPONSE = re.compile(
    r"^(?P<id>\S+) (?P<action>done|snooze|drop)(?: until=(?P<until>\S+))? via=(?P<via>\S+)$"
)
_HEARTBEAT = re.compile(
    r"^slot=(?P<slot>\S+) status=(?P<status>\S+) nudges=(?P<nudges>\d+) "
    r'suppressed=(?P<suppressed>\d+)(?: err="(?P<err>[^"]*)")?$'
)

DROPS_TO_SILENCE = 2


def _quote(text: str) -> str:
    """Sanitize free text for the one-line grammar (quotes/newlines flattened)."""
    return text.replace('"', "'").replace("\n", " ").strip()


def log_path(data_dir: Path) -> Path:
    return data_dir / "state" / "pulse-log.md"


def append_event(data_dir: Path, kind: str, ts: str, **fields: Any) -> str:
    if kind == "nudge":
        rest = f'{fields["loop_id"]} "{_quote(fields["text"])}" reason="{_quote(fields["reason"])}"'
    elif kind == "suppress":
        rest = f'{fields["loop_id"]} reason="{_quote(fields["reason"])}"'
    elif kind == "response":
        until = f" until={fields['until']}" if fields.get("until") else ""
        rest = f"{fields['loop_id']} {fields['action']}{until} via={fields.get('via', 'cli')}"
    elif kind == "heartbeat":
        err = f' err="{_quote(fields["err"])}"' if fields.get("err") else ""
        rest = (
            f"slot={fields['slot']} status={fields['status']} "
            f"nudges={fields.get('nudges', 0)} suppressed={fields.get('suppressed', 0)}{err}"
        )
    else:
        raise ValueError(f"unknown event kind: {kind}")
    line = f"- {ts} {kind} {rest}\n"
    parsed = parse_line(line)  # round-trip guard: never append an unparseable line
    if parsed is None:
        raise ValueError(f"event does not round-trip: {line!r}")
    path = log_path(data_dir)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        _append_line(path, HEADER)
    _append_line(path, line)
    return line


def parse_line(line: str) -> dict[str, Any] | None:
    m = _PREFIX.match(line.strip())
    if not m:
        return None
    kind, ts, rest = m.group("kind"), m.group("ts"), m.group("rest")
    body = {"nudge": _NUDGE, "suppress": _SUPPRESS, "response": _RESPONSE, "heartbeat": _HEARTBEAT}[
        kind
    ].match(rest)
    if not body:
        return None
    event: dict[str, Any] = {"kind": kind, "ts": ts, **body.groupdict()}
    if kind in ("nudge", "suppress", "response"):
        event["loop_id"] = event.pop("id")
    return event


def read_events(data_dir: Path) -> list[dict[str, Any]]:
    path = log_path(data_dir)
    if not path.is_file():
        return []
    events = []
    for line in path.read_text(encoding="utf-8").splitlines():
        parsed = parse_line(line)
        if parsed:
            events.append(parsed)
    return events


def fold(events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Collapse the event stream into per-loop state (the pulse's memory)."""
    state: dict[str, dict[str, Any]] = {}

    def slot(loop_id: str) -> dict[str, Any]:
        return state.setdefault(
            loop_id,
            {
                "drops": 0,
                "done": False,
                "snoozed_until": None,
                "nudges": 0,
                "last_nudged": None,
                "suppressed": 0,
            },
        )

    for e in events:
        if e["kind"] == "nudge":
            s = slot(e["loop_id"])
            s["nudges"] += 1
            s["last_nudged"] = e["ts"]
        elif e["kind"] == "suppress":
            slot(e["loop_id"])["suppressed"] += 1
        elif e["kind"] == "response":
            s = slot(e["loop_id"])
            if e["action"] == "done":
                s["done"] = True
            elif e["action"] == "drop":
                s["drops"] += 1
            elif e["action"] == "snooze" and e.get("until"):
                s["snoozed_until"] = e["until"]
    for s in state.values():
        s["silenced"] = s["drops"] >= DROPS_TO_SILENCE
    return state


def is_snoozed(loop_state: dict[str, Any], today: date) -> bool:
    until = loop_state.get("snoozed_until")
    if not until:
        return False
    return today < datetime.strptime(until, "%Y-%m-%d").date()


def nudges_on_day(events: list[dict[str, Any]], day: date) -> int:
    prefix = day.isoformat()
    return sum(1 for e in events if e["kind"] == "nudge" and e["ts"].startswith(prefix))
