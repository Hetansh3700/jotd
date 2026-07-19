"""`jotd hook session-end` — auto-distill an ended Claude Code session into captures.

Same split as the pulse (D5): the model only DRAFTS fragments from a transcript
digest; deterministic code owns every guard, the fragment budget, the size cap,
and the append. A hook must never break the user's session end, so every
failure path here is a logged skip and the CLI wrapper always exits 0.

Recursion matters: the scribe's own `claude -p` run (and the pulse's) fires
SessionEnd too. Two independent breakers: the JOTD_SESSION_HOOK env marker on
the scribe subprocess, and skipping any session whose cwd is the data dir.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from jotd import headless, inbox
from jotd.author import resolve_author
from jotd.config import load_config, resolve_data_dir

MAX_FRAGMENTS = 6
MAX_FRAGMENT_CHARS = 1500  # atomicity cap; the hard 4096-byte line cap is dump_capture_line's
MIN_USER_MESSAGES = 2  # fewer = a one-shot/trivial session, not worth a scribe run
DIGEST_CHAR_BUDGET = 24_000
PER_MESSAGE_CHARS = 1500
HOOK_ENV_GUARD = headless.HOOK_ENV_GUARD  # shared with the pulse and the start hook
SCRIBE_TIMEOUT_S = 90  # must stay under the settings.json hook timeout (120s)

SCRIBE_PROMPT = (
    "You are jotd's session scribe. Below is a compacted transcript of a Claude Code "
    "session in project {project!r}. Reply with ONLY a JSON object, no prose, no code "
    'fences: {{"captures": [{{"text": str}}]}}. 0-{max_fragments} items. Each fragment: '
    "self-contained, under 600 characters, names the project and any people/entities in "
    "the text itself, imperative phrasing for action items. Capture only durable "
    "information — decisions with their rationale, unresolved TODOs, learnings/gotchas, "
    "important facts. Never routine mechanics, diffs, or transient errors. An empty list "
    "is the right answer when nothing durable happened.\n\nTRANSCRIPT DIGEST:\n"
)


def _log(data_dir: Path, session_id: str, status: str, detail: str) -> None:
    try:
        ts = datetime.now().astimezone().isoformat(timespec="seconds")
        detail = " ".join(detail.split())[:400]
        inbox._append_line(
            data_dir / "state" / "logs" / "session-hook.log",
            f"{ts} session={session_id or '?'} {status}: {detail}\n",
        )
    except OSError:
        pass  # logging must never take the hook down


def _message_text(entry: dict[str, Any]) -> str:
    """Text content of a transcript entry; tool_use/tool_result blocks are skipped."""
    message = entry.get("message")
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    parts: list[str] = []
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
    return "\n".join(p for p in parts if p).strip()


def manual_capture_ran(transcript_path: Path) -> bool:
    """True when the session already ran /jotd:session (a Bash `jotd capture
    --source claude-code` tool call) — checked on tool_use blocks, not raw text,
    so file contents mentioning the command don't false-positive."""
    for line in transcript_path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(entry, dict) or entry.get("type") != "assistant":
            continue
        content = entry.get("message", {}).get("content")
        for block in content if isinstance(content, list) else []:
            if (
                isinstance(block, dict)
                and block.get("type") == "tool_use"
                and block.get("name") == "Bash"
                and "--source claude-code" in str(block.get("input", {}).get("command", ""))
            ):
                return True
    return False


def extract_digest(transcript_path: Path, budget: int = DIGEST_CHAR_BUDGET) -> tuple[str, int]:
    """Compact the transcript JSONL to (digest, user_message_count)."""
    rendered: list[str] = []
    user_count = 0
    for line in transcript_path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(entry, dict) or entry.get("type") not in ("user", "assistant"):
            continue
        text = _message_text(entry)
        if not text:
            continue
        if entry["type"] == "user":
            user_count += 1
        role = entry["type"].upper()
        rendered.append(f"{role}: {text[:PER_MESSAGE_CHARS]}")

    digest = "\n\n".join(rendered)
    if len(digest) > budget:
        # keep the first user message (the task) plus as much tail as fits
        head = next((r for r in rendered if r.startswith("USER:")), "")
        tail_budget = budget - len(head)
        digest = head + "\n[...]\n" + digest[-tail_budget:]
    return digest, user_count


def validate_scribe_output(obj: Any) -> list[str]:
    if not isinstance(obj, dict):
        return ["output is not an object"]
    captures = obj.get("captures")
    if not isinstance(captures, list):
        return ["captures is not a list"]
    errors = []
    for i, item in enumerate(captures):
        if not isinstance(item, dict) or not isinstance(item.get("text"), str):
            errors.append(f"captures[{i}] has no string text")
        elif not item["text"].strip():
            errors.append(f"captures[{i}] text is empty")
    return errors


def _invoke_scribe(data_dir: Path, model: str, prompt: str) -> str:
    return headless.invoke_claude(
        prompt,
        cwd=data_dir,  # the one directory we know is trusted for headless runs (D7)
        model=model,
        allowed_tools=(),
        max_turns=1,
        timeout_s=SCRIBE_TIMEOUT_S,
        extra_env={HOOK_ENV_GUARD: "1"},
    )


def run_session_end(payload: dict[str, Any]) -> dict[str, Any]:
    """Core of the hook. Every guard is a skip; callers must treat nothing as fatal."""
    session_id = str(payload.get("session_id", ""))
    reason = str(payload.get("reason", ""))
    cwd = str(payload.get("cwd", ""))
    transcript = payload.get("transcript_path")

    def skip(detail: str, *, log_dir: Path | None = None) -> dict[str, Any]:
        if log_dir is not None:
            _log(log_dir, session_id, "skip", detail)
        return {"status": "skip", "detail": detail, "appended": []}

    if os.environ.get(HOOK_ENV_GUARD):
        return skip("scribe/pulse subprocess session")
    if reason == "clear":
        return skip("session cleared, not ended")

    data_dir = resolve_data_dir(None)
    if not (data_dir / "jotd.toml").is_file():
        return skip(f"{data_dir} is not a jotd directory")

    if cwd and Path(cwd).expanduser().resolve() == data_dir:
        return skip("session ran in the jotd directory itself", log_dir=data_dir)
    if not transcript or not Path(str(transcript)).is_file():
        return skip("transcript missing", log_dir=data_dir)

    transcript_path = Path(str(transcript))
    if manual_capture_ran(transcript_path):
        return skip("session already captured manually via /jotd:session", log_dir=data_dir)

    digest, user_count = extract_digest(transcript_path)
    if user_count < MIN_USER_MESSAGES or not digest:
        return skip(f"too small ({user_count} user messages)", log_dir=data_dir)

    project = Path(cwd).name if cwd else "unknown"
    prompt = SCRIBE_PROMPT.format(project=project, max_fragments=MAX_FRAGMENTS) + digest
    try:
        model = load_config(data_dir).model
        output = headless.extract_json(_invoke_scribe(data_dir, model, prompt))
        errors = validate_scribe_output(output)
        if errors:
            raise ValueError("scribe output failed schema: " + "; ".join(errors))
    except Exception as e:  # noqa: BLE001 — any failure means: write NOTHING (D5)
        _log(data_dir, session_id, "error", str(e))
        return {"status": "error", "detail": str(e), "appended": []}

    fragments = [c["text"].strip() for c in output["captures"]]
    if len(fragments) > MAX_FRAGMENTS:
        _log(data_dir, session_id, "skip", f"dropped {len(fragments) - MAX_FRAGMENTS} over budget")
        fragments = fragments[:MAX_FRAGMENTS]

    appended: list[str] = []
    rejected = 0
    author_slug = resolve_author(None)
    context = {"app": "Claude Code", "title": project, "method": "session-end"}
    for text in fragments:
        if len(text) > MAX_FRAGMENT_CHARS:
            rejected += 1
            _log(data_dir, session_id, "reject", f"fragment over {MAX_FRAGMENT_CHARS} chars")
            continue
        try:
            record = inbox.append_capture(
                data_dir, text, source="claude-code", author=author_slug, context=context
            )
            appended.append(record["id"])
        except (inbox.JotdError, ValueError) as e:
            # dump_capture_line raises BEFORE writing on the 4096-byte cap — never truncate
            rejected += 1
            _log(data_dir, session_id, "reject", str(e))

    _log(data_dir, session_id, "ok", f"appended={len(appended)} rejected={rejected}")
    return {"status": "ok", "detail": "", "appended": appended}
