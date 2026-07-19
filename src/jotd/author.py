"""Per-machine author identity for the team layer.

Author identity is deliberately NOT stored in jotd.toml: that file is committed
and synced between machines, so "who am I" cannot live there without every
machine fighting over it. Resolution precedence: explicit flag > $JOTD_AUTHOR >
~/.config/jotd/author (the canonical setup) > slugified `git config user.name` >
OS username > literal "user". Any layer whose value slugs to empty falls
through to the next — a non-Latin git name must not resolve to "".

Resolution happens only in the CLI/hook layer and is passed down explicitly;
library callers (and the eval harness) that pass author=None keep the legacy
single-file inbox behavior.
"""

from __future__ import annotations

import getpass
import os
import re
import shutil
import subprocess
from pathlib import Path

AUTHOR_FILE = Path.home() / ".config" / "jotd" / "author"
MAX_AUTHOR_CHARS = 32

_NON_SLUG = re.compile(r"[^a-z0-9-]+")


def slugify(name: str) -> str:
    """Lowercase [a-z0-9-] slug, hyphens collapsed, <= 32 chars; "" when nothing survives."""
    slug = _NON_SLUG.sub("-", name.lower())
    slug = re.sub(r"-{2,}", "-", slug).strip("-")
    return slug[:MAX_AUTHOR_CHARS].rstrip("-")


def _git_user_name() -> str:
    git = shutil.which("git")
    if not git:
        return ""
    try:
        proc = subprocess.run(
            [git, "config", "--get", "user.name"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return proc.stdout.strip() if proc.returncode == 0 else ""


def _os_user() -> str:
    try:
        return getpass.getuser()
    except (KeyError, OSError):
        return ""


def resolve_author_with_rule(flag: str | None = None) -> tuple[str, str]:
    """Resolve this machine's author slug; returns (slug, rule-that-resolved-it).

    The rule string exists for `jotd whoami`: when two machines collide on a
    slug, seeing WHERE each got its identity is the whole debugging story.
    """
    layers: list[tuple[str, str]] = [
        ("--author flag", flag or ""),
        ("$JOTD_AUTHOR", os.environ.get("JOTD_AUTHOR", "")),
    ]
    if AUTHOR_FILE.is_file():
        try:
            layers.append((str(AUTHOR_FILE), AUTHOR_FILE.read_text(encoding="utf-8").strip()))
        except OSError:
            pass
    layers.append(("git config user.name", _git_user_name()))
    layers.append(("OS username", _os_user()))
    for rule, raw in layers:
        slug = slugify(raw)
        if slug:
            return slug, rule
    return "user", "fallback (nothing else resolved)"


def resolve_author(flag: str | None = None) -> str:
    return resolve_author_with_rule(flag)[0]
