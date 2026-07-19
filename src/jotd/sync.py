"""`jotd sync` — git transport for a shared data dir (D12).

Deterministic and conservative: stage → commit → pull --rebase → (librarian
only) derive → push. Per-author inbox files make concurrent captures
conflict-free; anything git cannot replay cleanly is an abort-and-tell, never
an auto-resolve. Everything here is git's own state mutation — jotd's file
invariants (append-only inbox, single-writer state) are untouched.
"""

from __future__ import annotations

import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from jotd.config import load_team
from jotd.inbox import JotdError

_NON_FF_MARKERS = ("non-fast-forward", "fetch first", "[rejected]")


def _run_git(data_dir: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=data_dir, capture_output=True, text=True, check=False)


def _head(data_dir: Path) -> str | None:
    proc = _run_git(data_dir, "rev-parse", "HEAD")
    return proc.stdout.strip() if proc.returncode == 0 else None


def _rebase_in_progress(data_dir: Path) -> bool:
    git_dir = data_dir / ".git"
    return (git_dir / "rebase-merge").exists() or (git_dir / "rebase-apply").exists()


def _commit(data_dir: Path, author: str, message: str) -> None:
    identity: list[str] = []
    if not _run_git(data_dir, "config", "user.email").stdout.strip():
        # committing must not fail on a machine without a git identity
        identity = ["-c", f"user.name={author}", "-c", f"user.email={author}@jotd.invalid"]
    proc = _run_git(data_dir, *identity, "commit", "-q", "-m", message)
    if proc.returncode != 0:
        raise JotdError(f"git commit failed: {proc.stderr.strip()[-300:]}")


def _pull(data_dir: Path, branch: str, actions: list[str]) -> None:
    proc = _run_git(data_dir, "pull", "--rebase", "origin", branch)
    if proc.returncode == 0:
        return
    err = proc.stderr + proc.stdout
    if "couldn't find remote ref" in err.lower():
        actions.append("remote is empty — nothing to pull yet")
        return
    if _rebase_in_progress(data_dir):
        conflicted = _run_git(data_dir, "diff", "--name-only", "--diff-filter=U").stdout.split()
        _run_git(data_dir, "rebase", "--abort")
        hint = ""
        if any(c.startswith("inbox/") for c in conflicted):
            # per-author files never conflict unless two machines share one slug
            hint = (
                " An inbox file conflicted — two machines are almost certainly using "
                "the same author id; check `jotd whoami` on both."
            )
        raise JotdError(
            "sync conflict: the remote and this machine changed the same lines. "
            f"Your commits are safe locally — resolve by hand in {data_dir} "
            "(git pull --rebase, fix conflicts, git rebase --continue), then `jotd sync` again."
            + hint
        )
    raise JotdError(f"git pull failed: {err.strip()[-300:]}")


def run_sync(data_dir: Path, author: str, *, derive_after_pull: bool = True) -> list[str]:
    """Sync the data dir with origin; returns human-readable action lines."""
    actions: list[str] = []
    if not shutil.which("git"):
        raise JotdError("git is not installed")
    if not (data_dir / ".git").is_dir():
        raise JotdError(
            f"{data_dir} is not a git repository — `git -C {data_dir} init -b main` "
            "(jotd init does this by default)"
        )
    if _rebase_in_progress(data_dir):
        raise JotdError(
            f"a rebase is already in progress in {data_dir} — finish it "
            "(git rebase --continue) or abort it (git rebase --abort) first"
        )
    if "origin" not in _run_git(data_dir, "remote").stdout.split():
        raise JotdError(
            "no 'origin' remote — create a PRIVATE repo and add it: "
            f"git -C {data_dir} remote add origin <url>"
        )
    branch_proc = _run_git(data_dir, "symbolic-ref", "--short", "HEAD")
    if branch_proc.returncode != 0:
        raise JotdError("detached HEAD in the data dir — check out a branch first")
    branch = branch_proc.stdout.strip()

    ts = datetime.now().astimezone().isoformat(timespec="seconds")
    _run_git(data_dir, "add", "-A")
    if _run_git(data_dir, "ls-files", "state/logs").stdout.strip():
        actions.append("warning: state/logs is tracked by git — the data dir .gitignore is missing")
    if _run_git(data_dir, "status", "--porcelain").stdout.strip():
        _commit(data_dir, author, f"jotd sync: {author} {ts}")
        actions.append("committed local changes")

    before = _head(data_dir)
    _pull(data_dir, branch, actions)
    if before and _head(data_dir) != before:
        actions.append("pulled remote changes")
        remote_files = _run_git(
            data_dir, "diff", "--name-only", f"{before}...FETCH_HEAD"
        ).stdout.splitlines()
        if any(f.endswith(f".{author}.jsonl") for f in remote_files):
            actions.append(
                f"warning: the remote also writes inbox files for author '{author}' — "
                "two machines sharing one author id will conflict (check `jotd whoami` on both)"
            )

    if derive_after_pull and load_team(data_dir).librarian == author:
        # only the librarian's machine derives (D12) — synced state stays fresh
        # without two machines ever racing to write it
        from jotd.derive import derive as run_derive

        run_derive(data_dir)
        _run_git(data_dir, "add", "-A")
        if _run_git(data_dir, "status", "--porcelain").stdout.strip():
            _commit(data_dir, author, f"jotd sync: derive {author} {ts}")
            actions.append("derived state refreshed")

    push = _run_git(data_dir, "push", "-q", "-u", "origin", branch)
    if push.returncode != 0 and any(m in (push.stderr + push.stdout) for m in _NON_FF_MARKERS):
        _pull(data_dir, branch, actions)  # someone pushed since our pull — exactly one retry
        push = _run_git(data_dir, "push", "-q", "-u", "origin", branch)
    if push.returncode != 0:
        raise JotdError(f"git push failed: {(push.stderr + push.stdout).strip()[-300:]}")
    actions.append(f"synced with origin/{branch}")
    return actions
