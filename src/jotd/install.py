"""`jotd install claude-code` — global Claude Code integration.

Installs the /jotd:session command into ~/.claude/commands/jotd/ so it is
available in every Claude Code session, with the same sha256-manifest upgrade
safety as `jotd init`. The manifest lives in jotd's own config dir
(~/.config/jotd/global-manifest.json) — bookkeeping stays out of ~/.claude.

`--hook` merges BOTH session hooks into ~/.claude/settings.json (idempotent
per event; a settings file we cannot parse is never touched): SessionEnd
auto-captures the ended session (D11) and SessionStart injects the team
brief (D12) — the write and read halves of the loop.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from jotd.init import TEMPLATES, sync_managed_files
from jotd.sched import _jotd_bin

GLOBAL_TEMPLATES = TEMPLATES / "global"
CLAUDE_USER_DIR = Path.home() / ".claude"
SETTINGS_PATH = CLAUDE_USER_DIR / "settings.json"
GLOBAL_MANIFEST = Path.home() / ".config" / "jotd" / "global-manifest.json"

# Dedupe/removal match on these substrings, so an entry survives binary moves
# (absolute path prefix may change; the subcommand never does).
HOOK_MARKER = "jotd hook session-end"
START_HOOK_MARKER = "jotd hook session-start"

# The scribe's headless claude run can take ~60s; Claude Code's default hook
# timeout would kill it mid-run. The start hook is deterministic and instant.
HOOK_TIMEOUT_S = 120
START_HOOK_TIMEOUT_S = 10

# (settings event, marker substring, timeout)
HOOK_SPECS = (
    ("SessionEnd", HOOK_MARKER, HOOK_TIMEOUT_S),
    ("SessionStart", START_HOOK_MARKER, START_HOOK_TIMEOUT_S),
)


def global_files() -> dict[str, Path]:
    """packaged global template -> install path relative to ~/.claude."""
    out: dict[str, Path] = {}
    for src in sorted(GLOBAL_TEMPLATES.rglob("*")):
        if src.is_file():
            out[str(src.relative_to(GLOBAL_TEMPLATES))] = src
    return out


def _hook_entries(settings: dict, event: str) -> list[dict]:
    entries = settings.get("hooks", {}).get(event, [])
    return entries if isinstance(entries, list) else []


def _has_jotd_hook(settings: dict, event: str, marker: str) -> bool:
    for entry in _hook_entries(settings, event):
        for h in entry.get("hooks", []) if isinstance(entry, dict) else []:
            if isinstance(h, dict) and marker in str(h.get("command", "")):
                return True
    return False


def _load_settings(settings_path: Path) -> dict | None:
    """Parse settings.json; None means unreadable — never touch the file then."""
    if not settings_path.is_file():
        return {}
    try:
        obj = json.loads(settings_path.read_text(encoding="utf-8"))
        return obj if isinstance(obj, dict) else None
    except (json.JSONDecodeError, OSError):
        return None


def _write_settings(settings_path: Path, settings: dict) -> None:
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")


def merge_hook(settings_path: Path, event: str, marker: str, command: str, timeout: int) -> str:
    settings = _load_settings(settings_path)
    if settings is None:
        return f"error: cannot parse {settings_path} — fix it by hand, file left untouched"
    if _has_jotd_hook(settings, event, marker):
        return f"{event} hook already installed"
    settings.setdefault("hooks", {}).setdefault(event, []).append(
        {"hooks": [{"type": "command", "command": command, "timeout": timeout}]}
    )
    _write_settings(settings_path, settings)
    return f"installed {event} hook ({command})"


def remove_hook(settings_path: Path, event: str, marker: str) -> str:
    settings = _load_settings(settings_path)
    if settings is None:
        return f"error: cannot parse {settings_path} — hook entry (if any) left in place"
    if not _has_jotd_hook(settings, event, marker):
        return f"no {event} hook installed"
    kept = []
    for entry in _hook_entries(settings, event):
        hooks = entry.get("hooks", []) if isinstance(entry, dict) else []
        remaining = [
            h for h in hooks if not (isinstance(h, dict) and marker in str(h.get("command", "")))
        ]
        if remaining == hooks:
            kept.append(entry)
        elif remaining:
            kept.append({**entry, "hooks": remaining})
    if kept:
        settings["hooks"][event] = kept
    else:
        del settings["hooks"][event]
        if not settings["hooks"]:
            del settings["hooks"]
    _write_settings(settings_path, settings)
    return f"removed {event} hook"


def install_claude_code(*, hook: bool = False, upgrade: bool = False) -> list[str]:
    files = global_files()
    if not files:
        raise RuntimeError("no packaged global templates found (broken install?)")
    actions = sync_managed_files(files, CLAUDE_USER_DIR, GLOBAL_MANIFEST, upgrade=upgrade)
    if not actions:
        actions.append("commands up to date (use --upgrade to refresh)")
    if hook:
        jotd_bin = _jotd_bin()
        for event, marker, timeout in HOOK_SPECS:
            subcmd = marker.removeprefix("jotd ")
            actions.append(
                merge_hook(SETTINGS_PATH, event, marker, f"{jotd_bin} {subcmd}", timeout)
            )
    return actions


def uninstall_claude_code() -> list[str]:
    actions: list[str] = []
    manifest: dict[str, str] = {}
    if GLOBAL_MANIFEST.is_file():
        manifest = json.loads(GLOBAL_MANIFEST.read_text(encoding="utf-8"))

    remaining: dict[str, str] = {}
    for rel, sha in sorted(manifest.items()):
        target = CLAUDE_USER_DIR / rel
        if not target.exists():
            continue
        if hashlib.sha256(target.read_bytes()).hexdigest() == sha:
            target.unlink()
            actions.append(f"removed {rel}")
        else:
            remaining[rel] = sha
            actions.append(f"kept {rel} (hand-edited — remove it yourself if you're sure)")

    # prune now-empty directories we own (commands/jotd/), never ~/.claude itself
    for rel in sorted({str(Path(r).parent) for r in manifest}, reverse=True):
        d = CLAUDE_USER_DIR / rel
        if rel not in (".", "") and d.is_dir() and not any(d.iterdir()):
            d.rmdir()

    if GLOBAL_MANIFEST.is_file():
        if remaining:
            GLOBAL_MANIFEST.write_text(
                json.dumps(remaining, indent=1, sort_keys=True), encoding="utf-8"
            )
        else:
            GLOBAL_MANIFEST.unlink()

    for event, marker, _timeout in HOOK_SPECS:
        actions.append(remove_hook(SETTINGS_PATH, event, marker))
    return actions or ["nothing installed"]
