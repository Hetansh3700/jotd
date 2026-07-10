"""`jotd init` — scaffold or upgrade a personal jotd data dir from packaged templates.

Upgrade safety: init records a sha256 manifest of every file it installs
(.claude/.jotd-manifest.json). `--upgrade` overwrites a file only when its
current content still matches the recorded hash — i.e. the user never touched
it. Hand-edited files are skipped with a warning, never clobbered.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from jotd.config import POINTER_FILE

TEMPLATES = Path(__file__).parent / "templates"
MANIFEST = ".claude/.jotd-manifest.json"

NOTE_DIRS = ["people", "projects", "topics", "meetings", "journal"]

UNSORTED = """---
type: topic
title: Unsorted
aliases: []
created: {today}
---
Captures that had no clear home. The librarian routes here on purpose when a
fragment is genuinely ambiguous — review occasionally and promote what matters.

## Log

## Open loops
"""


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _template_files() -> dict[str, Path]:
    """template source -> install path relative to the data dir."""
    out: dict[str, Path] = {}
    for src in sorted(TEMPLATES.rglob("*")):
        if not src.is_file():
            continue
        rel = src.relative_to(TEMPLATES)
        if rel.parts[0] in ("agents", "commands"):
            out[str(Path(".claude") / rel)] = src
        elif rel.name == "gitignore":
            out[".gitignore"] = src
        elif rel.name == "settings.json":
            out[".claude/settings.json"] = src
        else:
            out[rel.name] = src
    return out


def scaffold(
    data_dir: Path,
    *,
    git: bool = True,
    upgrade: bool = False,
    set_default: bool = False,
    pointer: bool = True,
    today: str | None = None,
) -> list[str]:
    """Create/upgrade the data dir. Returns human-readable action lines."""
    actions: list[str] = []
    data_dir = data_dir.expanduser().resolve()
    for sub in ["inbox", "state/briefs", "state/logs", ".claude/agents", ".claude/commands"]:
        (data_dir / sub).mkdir(parents=True, exist_ok=True)
    for sub in NOTE_DIRS:
        (data_dir / "notes" / sub).mkdir(parents=True, exist_ok=True)

    manifest_path = data_dir / MANIFEST
    manifest: dict[str, str] = {}
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    for rel, src in _template_files().items():
        target = data_dir / rel
        content = src.read_bytes()
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
            manifest[rel] = _sha(content)
            actions.append(f"installed {rel}")
        elif upgrade:
            current = _sha(target.read_bytes())
            if current == manifest.get(rel):
                if current != _sha(content):
                    target.write_bytes(content)
                    manifest[rel] = _sha(content)
                    actions.append(f"upgraded {rel}")
            else:
                actions.append(f"skipped {rel} (hand-edited; diff against the packaged template)")

    unsorted = data_dir / "notes" / "topics" / "unsorted.md"
    if not unsorted.exists():
        from datetime import date

        unsorted.write_text(UNSORTED.format(today=today or date.today().isoformat()))
        actions.append("installed notes/topics/unsorted.md")

    manifest_path.write_text(json.dumps(manifest, indent=1, sort_keys=True), encoding="utf-8")

    if git and not (data_dir / ".git").exists() and shutil.which("git"):
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=data_dir, check=False)
        actions.append("git init (your notes stay local unless you add a private remote)")

    if pointer:
        if set_default or not POINTER_FILE.exists():
            POINTER_FILE.parent.mkdir(parents=True, exist_ok=True)
            POINTER_FILE.write_text(str(data_dir) + "\n", encoding="utf-8")
            actions.append(f"default jotd directory -> {data_dir}")
        elif POINTER_FILE.read_text(encoding="utf-8").strip() != str(data_dir):
            actions.append(
                f"note: default jotd directory is {POINTER_FILE.read_text().strip()} "
                "(rerun with --set-default to switch)"
            )

    foreign = _foreign_jotd_binary()
    if foreign:
        actions.append(
            f"warning: another `jotd` binary shadows or trails this one on PATH ({foreign}); "
            "likely a stale install — remove or alias one of them"
        )
    return actions


def _foreign_jotd_binary() -> str | None:
    ours = Path(sys.prefix)
    for d in os.environ.get("PATH", "").split(os.pathsep):
        candidate = Path(d) / "jotd"
        if candidate.is_file() and os.access(candidate, os.X_OK):
            if not candidate.resolve().is_relative_to(ours):
                return str(candidate)
    return None
