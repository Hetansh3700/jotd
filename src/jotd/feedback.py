"""`jotd done|snooze|drop` — the response half of the nudge feedback loop.

Responses are pulse-log events; derive folds them into loop status, and the
runner pre-filters on that status. Two drops silence a loop permanently.
`done` also flips the source checkbox so the loop is closed in the note
itself, not just in the log.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Any

from jotd import pulselog
from jotd.config import load_config
from jotd.derive import derive
from jotd.inbox import JotdError


def resolve_loop(data_dir: Path, fragment: str) -> dict[str, Any]:
    import json

    path = data_dir / "state" / "open-loops.json"
    loops = json.loads(path.read_text(encoding="utf-8"))["loops"] if path.is_file() else []
    live = [lp for lp in loops if lp["status"] in ("open", "snoozed", "silenced")]
    matches = [lp for lp in live if fragment in lp["id"]]
    if not matches:
        raise JotdError(f"no open loop matches {fragment!r} (see state/open-loops.md)")
    if len(matches) > 1:
        listing = "\n".join(f"  {lp['id']}  {lp['text'][:50]}" for lp in matches)
        raise JotdError(f"{fragment!r} is ambiguous:\n{listing}")
    return matches[0]


def _flip_checkbox(data_dir: Path, loop: dict[str, Any]) -> None:
    note = data_dir / loop["note"]
    lines = note.read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(lines):
        if f"loop:{loop['id']}" in line and "- [ ]" in line:
            lines[i] = line.replace("- [ ]", "- [x]", 1)
            note.write_text("\n".join(lines) + "\n", encoding="utf-8")
            return
    raise JotdError(f"could not find the open checkbox for {loop['id']} in {loop['note']}")


def flip_only(data_dir: Path, fragment: str) -> str:
    """Non-librarian `done` (D12): flip the note checkbox and stop.

    No pulse-log event and no derive — those writers live on the librarian's
    machine. The flipped checkbox syncs as an ordinary note change and the
    librarian's derive folds it into status=done.
    """
    loop = resolve_loop(data_dir, fragment)
    _flip_checkbox(data_dir, loop)
    return (
        f"done (checkbox flipped): {loop['text']} — "
        "state updates after the next `jotd sync` + librarian derive"
    )


def respond(
    data_dir: Path,
    fragment: str,
    action: str,
    *,
    days: int | None = None,
    today: date | None = None,
    ts: str | None = None,
) -> str:
    from datetime import datetime

    today = today or date.today()
    ts = ts or datetime.now().astimezone().isoformat(timespec="seconds")
    derive(data_dir, today=today)  # fresh state before matching
    loop = resolve_loop(data_dir, fragment)
    cfg = load_config(data_dir)

    if action == "done":
        _flip_checkbox(data_dir, loop)
        pulselog.append_event(data_dir, "response", ts, loop_id=loop["id"], action="done")
        message = f"done: {loop['text']}"
    elif action == "snooze":
        until = (today + timedelta(days=days or cfg.snooze_days)).isoformat()
        pulselog.append_event(
            data_dir, "response", ts, loop_id=loop["id"], action="snooze", until=until
        )
        message = f"snoozed until {until}: {loop['text']}"
    elif action == "drop":
        pulselog.append_event(data_dir, "response", ts, loop_id=loop["id"], action="drop")
        drops = pulselog.fold(pulselog.read_events(data_dir))[loop["id"]]["drops"]
        message = f"dropped: {loop['text']}"
        if drops >= pulselog.DROPS_TO_SILENCE:
            message += " — dropped twice, the pulse will never mention it again"
    else:
        raise JotdError(f"unknown action {action!r}")

    derive(data_dir, today=today)
    return message
