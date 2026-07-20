"""`jotd sync --auto` — the scheduled propagation run (D13).

Deterministic runner around run_sync: flock overlap guard, one-shot conflict
notification, librarian-only backlog → headless /organize → re-sync, and the
post-organize code guards (D5 — the model routes notes, code owns recovery).
Never raises to the caller; every outcome is one line in
state/logs/sync-auto.log. sync.py stays pure transport — no locks, no
notifications, no LLM there.

All markers and the lock live under state/logs/ (git-ignored): run_sync does
`git add -A`, so anything outside it would get committed and synced.
"""

from __future__ import annotations

import fcntl
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from jotd import headless, inbox, notify
from jotd.config import load_config, load_sync, load_team
from jotd.formats import parse_capture_line
from jotd.inbox import JotdError
from jotd.sync import _run_git, run_sync

LOG_NAME = "sync-auto.log"
LOCK_NAME = ".sync-auto.lock"
CONFLICT_MARKER = "sync-auto.conflict"
COOLDOWN_MARKER = "organize.cooldown"
ORGANIZE_COOLDOWN_HOURS = 4  # a failing organize must not burn tokens every tick
ORGANIZE_MAX_TURNS = 250  # matches evals/run_routing.py
ORGANIZE_ALLOWED_TOOLS = (
    "Bash(jotd unprocessed:*)",
    "Bash(jotd mark-processed:*)",
    "Bash(jotd derive:*)",
)


def _logs(data_dir: Path) -> Path:
    return data_dir / "state" / "logs"


def _log(data_dir: Path, status: str, detail: str) -> None:
    """Same line convention as session-hook.log; logging never takes the run down."""
    try:
        ts = datetime.now().astimezone().isoformat(timespec="seconds")
        detail = " ".join(detail.split())[:400]
        inbox._append_line(_logs(data_dir) / LOG_NAME, f"{ts} auto-sync {status}: {detail}\n")
    except OSError:
        pass


def _notify_once(data_dir: Path, channel: str, message: str) -> None:
    """First failure of an episode notifies; the marker mutes every later tick."""
    marker = _logs(data_dir) / CONFLICT_MARKER
    if marker.exists():
        return
    try:
        ts = datetime.now().astimezone().isoformat(timespec="seconds")
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(f"{ts} {' '.join(message.split())[:400]}\n", encoding="utf-8")
    except OSError:
        pass
    try:
        notify.send("jotd sync", message, channel=channel)
    except Exception:  # noqa: BLE001 — a failed notification must not fail the run
        pass


def _clear_conflict(data_dir: Path) -> None:
    marker = _logs(data_dir) / CONFLICT_MARKER
    if marker.exists():
        try:
            marker.unlink()
            _log(data_dir, "recovered", "clean sync after conflict")
        except OSError:
            pass


def _cooldown_active(data_dir: Path, now: datetime) -> bool:
    marker = _logs(data_dir) / COOLDOWN_MARKER
    if not marker.is_file():
        return False
    try:
        last = datetime.fromisoformat(marker.read_text(encoding="utf-8").strip())
    except (ValueError, OSError):
        try:  # unparseable content — treat as expired
            marker.unlink()
        except OSError:
            pass
        return False
    return now - last < timedelta(hours=ORGANIZE_COOLDOWN_HOURS)


def _set_cooldown(data_dir: Path, now: datetime) -> None:
    try:
        marker = _logs(data_dir) / COOLDOWN_MARKER
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(now.isoformat(timespec="seconds"), encoding="utf-8")
    except OSError:
        pass


def _clear_cooldown(data_dir: Path) -> None:
    try:
        (_logs(data_dir) / COOLDOWN_MARKER).unlink(missing_ok=True)
    except OSError:
        pass


def _inbox_snapshot(data_dir: Path) -> dict[str, bytes]:
    box = data_dir / "inbox"
    if not box.is_dir():
        return {}
    return {p.name: p.read_bytes() for p in sorted(box.glob("*.jsonl"))}


def _guard_inbox(data_dir: Path, before: dict[str, bytes]) -> list[str]:
    """Restore any non-append change to inbox/*.jsonl; returns restored names.

    Append-aware on purpose: a legit `jotd add` landing mid-organize appends to
    a snapshotted file and must survive. Anything else (rewrite, truncate,
    delete) is restored from git — lossless, sync #1 committed it moments ago.
    A NEW inbox file is kept only if every line parses as a capture (month
    rollover mid-organize is legitimate); otherwise it is unlinked.
    """
    restored: list[str] = []
    after = _inbox_snapshot(data_dir)
    for name, old in before.items():
        new = after.get(name)
        if new is not None and new.startswith(old):
            continue  # unchanged or pure append — a legit concurrent capture
        _run_git(data_dir, "checkout", "--", f"inbox/{name}")
        restored.append(name)
    for name in after.keys() - before.keys():
        path = data_dir / "inbox" / name
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    parse_capture_line(line)
        except (ValueError, json.JSONDecodeError, OSError):
            try:
                path.unlink()
            except OSError:
                pass
            restored.append(name)
    return restored


def _run_organize(data_dir: Path, model: str, timeout_s: int) -> str:
    """The one LLM call. Everything around it is deterministic (D5)."""
    return headless.invoke_claude(
        "/organize",
        cwd=data_dir,  # the cwd rule makes `jotd unprocessed` Just Work
        model=model,
        allowed_tools=ORGANIZE_ALLOWED_TOOLS,
        disallowed_tools=(),  # librarian subagent needs Edit/Write, via acceptEdits
        permission_mode="acceptEdits",
        max_turns=ORGANIZE_MAX_TURNS,
        timeout_s=timeout_s,
        extra_env={headless.HOOK_ENV_GUARD: "1", "JOTD_DIR": str(data_dir)},
    )


def run_auto_sync(data_dir: Path, author: str, *, now: datetime | None = None) -> dict[str, Any]:
    """One scheduled tick: sync, maybe organize (librarian only), sync again."""
    now = now or datetime.now().astimezone()
    pulse_cfg = load_config(data_dir)
    sync_cfg = load_sync(data_dir)
    result: dict[str, Any] = {"status": "ok", "organize": None, "actions": []}

    lock_path = _logs(data_dir) / LOCK_NAME
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_fd = open(lock_path, "w")
    try:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            _log(data_dir, "skip", "another auto-sync holds the lock")
            return {"status": "skipped", "organize": None, "actions": []}

        # ---- sync #1 -----------------------------------------------------
        try:
            result["actions"] += run_sync(data_dir, author)
        except JotdError as e:
            status = "conflict" if "sync conflict" in str(e) else "error"
            _log(data_dir, status, str(e))
            _notify_once(
                data_dir,
                pulse_cfg.channel,
                f"auto-sync failing: {str(e)[:120]} — run `jotd sync` by hand",
            )
            return {"status": status, "organize": None, "actions": result["actions"]}
        except Exception as e:  # noqa: BLE001 — unknown failure: log, never notify-loop
            _log(data_dir, "error", f"unexpected: {e}")
            return {"status": "error", "organize": None, "actions": result["actions"]}
        _clear_conflict(data_dir)

        # ---- organize eligibility (all deterministic, in code) ------------
        backlog_before = len(inbox.unprocessed(data_dir))
        if load_team(data_dir).librarian != author or sync_cfg.organize_backlog <= 0:
            _log(data_dir, "ok", f"backlog={backlog_before} (no organize on this machine)")
            return result
        if backlog_before < sync_cfg.organize_backlog:
            _log(
                data_dir,
                "ok",
                f"backlog={backlog_before} below threshold {sync_cfg.organize_backlog}",
            )
            return result
        if _cooldown_active(data_dir, now):
            _log(data_dir, "organize-skip", "cooldown after a failed organize attempt")
            result["organize"] = "skipped: cooldown"
            return result

        # a pulse mid-flight must not race organize's note edits (skip, don't wait)
        pulse_lock = open(data_dir / "state" / ".pulse.lock", "w")
        try:
            try:
                fcntl.flock(pulse_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                _log(data_dir, "organize-skip", "pulse in flight")
                result["organize"] = "skipped: pulse in flight"
                return result

            # ---- organize + code guards (D5) ---------------------------
            before = _inbox_snapshot(data_dir)
            organize_failed = False
            try:
                output = _run_organize(
                    data_dir,
                    sync_cfg.organize_model or pulse_cfg.model,
                    sync_cfg.organize_timeout_s,
                )
            except Exception as e:  # noqa: BLE001 — partial progress still ships below
                organize_failed = True
                output = ""
                _set_cooldown(data_dir, now)
                _log(data_dir, "organize-error", str(e))

            restored = _guard_inbox(data_dir, before)
            if restored:
                _log(
                    data_dir,
                    "guard",
                    f"organize modified inbox/{','.join(restored)} — restored from git",
                )
                try:
                    notify.send(
                        "jotd sync",
                        "auto-organize touched the inbox — restored; "
                        "check state/logs/sync-auto.log",
                        channel=pulse_cfg.channel,
                    )
                except Exception:  # noqa: BLE001
                    pass

            backlog_after = len(inbox.unprocessed(data_dir))
            if not organize_failed:
                if backlog_after >= backlog_before:
                    _set_cooldown(data_dir, now)
                    _log(
                        data_dir,
                        "organize-error",
                        f"backlog did not decrease ({backlog_before} -> {backlog_after}; "
                        "mark-processed never ran?)",
                    )
                    result["organize"] = "failed"
                else:
                    _clear_cooldown(data_dir)
                    _log(
                        data_dir,
                        "organize-ok",
                        f"backlog {backlog_before} -> {backlog_after}, {len(output)} result chars",
                    )
                    result["organize"] = "ok"
            else:
                result["organize"] = "failed"

            # ---- sync #2: derive re-runs in code, routed notes ship ------
            try:
                result["actions"] += run_sync(data_dir, author)
            except JotdError as e:
                status = "conflict" if "sync conflict" in str(e) else "error"
                _log(data_dir, status, str(e))
                _notify_once(
                    data_dir,
                    pulse_cfg.channel,
                    f"auto-sync failing: {str(e)[:120]} — run `jotd sync` by hand",
                )
                result["status"] = status
        finally:
            pulse_lock.close()
        return result
    finally:
        lock_fd.close()
