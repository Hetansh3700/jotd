"""`jotd sync` — two simulated machines (A, B) sharing a bare 'origin' repo.

Machine identity is just --author per invocation; no network, no LLM. An
autouse fixture strips the runner's real git identity so the commit fallback
path (-c user.email=<author>@jotd.invalid) is exercised by every test.
"""

import shutil
import subprocess

import pytest
from typer.testing import CliRunner

from jotd import inbox
from jotd import init as vinit
from jotd import sync as vsync
from jotd.cli import app

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git required")
runner = CliRunner()


@pytest.fixture(autouse=True)
def no_git_identity(monkeypatch, tmp_path_factory):
    empty = tmp_path_factory.mktemp("gitcfg") / "empty"
    empty.write_text("")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(empty))
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", str(empty))


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=False)


def make_machine_a(tmp_path, monkeypatch):
    monkeypatch.setattr(vinit, "POINTER_FILE", tmp_path / "pointer")
    a = tmp_path / "a"
    assert runner.invoke(app, ["init", str(a)]).exit_code == 0  # --git by default
    origin = tmp_path / "origin.git"
    subprocess.run(
        ["git", "init", "--bare", "-q", "-b", "main", str(origin)],
        check=True,
        capture_output=True,
    )
    _git(a, "remote", "add", "origin", str(origin))
    return a, origin


def sync(d, author):
    return runner.invoke(app, ["sync", "--dir", str(d), "--author", author])


def add(d, text, author):
    result = runner.invoke(app, ["add", text, "--author", author, "--dir", str(d)])
    assert result.exit_code == 0, result.output


def clone(origin, dest):
    subprocess.run(["git", "clone", "-q", str(origin), str(dest)], check=True, capture_output=True)
    return dest


def test_sync_requires_git_repo(tmp_path, monkeypatch):
    monkeypatch.setattr(vinit, "POINTER_FILE", tmp_path / "pointer")
    d = tmp_path / "v"
    runner.invoke(app, ["init", str(d), "--no-git"])
    result = sync(d, "ana")
    assert result.exit_code == 2 and "not a git repository" in result.output


def test_sync_requires_remote(tmp_path, monkeypatch):
    monkeypatch.setattr(vinit, "POINTER_FILE", tmp_path / "pointer")
    d = tmp_path / "v"
    runner.invoke(app, ["init", str(d)])
    result = sync(d, "ana")
    assert result.exit_code == 2 and "no 'origin' remote" in result.output


def test_leftover_rebase_refuses(tmp_path, monkeypatch):
    a, _ = make_machine_a(tmp_path, monkeypatch)
    (a / ".git" / "rebase-merge").mkdir()
    result = sync(a, "ana")
    assert result.exit_code == 2 and "rebase is already in progress" in result.output


def test_first_sync_and_two_machine_roundtrip(tmp_path, monkeypatch):
    a, origin = make_machine_a(tmp_path, monkeypatch)
    add(a, "ana thought one", "ana")
    result = sync(a, "ana")  # first push against an empty remote
    assert result.exit_code == 0, result.output
    assert "synced with origin/main" in result.output

    b = clone(origin, tmp_path / "b")
    assert (b / "jotd.toml").is_file()  # the whole data dir travels
    add(b, "ben thought one", "ben")
    assert sync(b, "ben").exit_code == 0

    assert sync(a, "ana").exit_code == 0  # A pulls B's capture
    texts = {r["text"] for r in inbox.iter_captures(a)}
    assert texts == {"ana thought one", "ben thought one"}
    names = {p.name for p in (a / "inbox").glob("*.jsonl")}
    assert any(".ana." in n for n in names) and any(".ben." in n for n in names)


def test_concurrent_captures_never_conflict(tmp_path, monkeypatch):
    a, origin = make_machine_a(tmp_path, monkeypatch)
    add(a, "seed", "ana")
    assert sync(a, "ana").exit_code == 0
    b = clone(origin, tmp_path / "b")

    add(a, "ana offline", "ana")  # both capture before either syncs
    add(b, "ben offline", "ben")
    assert sync(a, "ana").exit_code == 0
    assert sync(b, "ben").exit_code == 0
    assert sync(a, "ana").exit_code == 0
    assert len(inbox.iter_captures(a)) == 3 == len(inbox.iter_captures(b))


def test_conflict_aborts_cleanly_and_keeps_local_commits(tmp_path, monkeypatch):
    a, origin = make_machine_a(tmp_path, monkeypatch)
    add(a, "seed", "ana")
    assert sync(a, "ana").exit_code == 0
    b = clone(origin, tmp_path / "b")

    # same line region of the same note edited on both machines
    (a / "notes" / "topics" / "unsorted.md").write_text("frontmatter\nA's line\n")
    assert sync(a, "ana").exit_code == 0
    (b / "notes" / "topics" / "unsorted.md").write_text("frontmatter\nB's line\n")
    result = sync(b, "ben")
    assert result.exit_code == 2 and "sync conflict" in result.output
    assert not (b / ".git" / "rebase-merge").exists()  # abort ran
    assert _git(b, "status", "--porcelain").stdout.strip() == ""  # tree restored clean
    assert "jotd sync: ben" in _git(b, "log", "-1", "--format=%s").stdout  # commit kept


def test_noop_sync_creates_no_empty_commit(tmp_path, monkeypatch):
    a, _ = make_machine_a(tmp_path, monkeypatch)
    add(a, "one", "ana")
    assert sync(a, "ana").exit_code == 0
    before = _git(a, "rev-list", "--count", "HEAD").stdout.strip()
    result = sync(a, "ana")
    assert result.exit_code == 0 and "committed local changes" not in result.output
    assert _git(a, "rev-list", "--count", "HEAD").stdout.strip() == before


def test_gitignore_keeps_logs_and_lock_untracked(tmp_path, monkeypatch):
    a, _ = make_machine_a(tmp_path, monkeypatch)
    (a / "state" / "logs").mkdir(parents=True, exist_ok=True)
    (a / "state" / "logs" / "session-hook.log").write_text("log line\n")
    (a / "state" / ".pulse.lock").write_text("")
    add(a, "one", "ana")
    result = sync(a, "ana")
    assert result.exit_code == 0
    assert "warning: state/logs" not in result.output
    assert _git(a, "ls-files", "state/logs").stdout.strip() == ""


def test_push_race_retries_exactly_once(tmp_path, monkeypatch):
    a, _ = make_machine_a(tmp_path, monkeypatch)
    add(a, "one", "ana")
    real = vsync._run_git
    pushes = {"n": 0}

    def flaky(data_dir, *args):
        if args and args[0] == "push":
            pushes["n"] += 1
            if pushes["n"] == 1:
                proc = subprocess.CompletedProcess(args, 1)
                proc.stdout, proc.stderr = "", "! [rejected] main -> main (non-fast-forward)"
                return proc
        return real(data_dir, *args)

    monkeypatch.setattr(vsync, "_run_git", flaky)
    assert sync(a, "ana").exit_code == 0
    assert pushes["n"] == 2  # one rejection, one successful retry


def test_librarian_sync_autoderives_and_ships_state(tmp_path, monkeypatch):
    a, origin = make_machine_a(tmp_path, monkeypatch)
    with (a / "jotd.toml").open("a") as f:
        f.write('\n[team]\nlibrarian = "ana"\n')
    note = a / "notes" / "topics" / "unsorted.md"
    note.write_text(note.read_text() + "\n- [ ] hand-written loop\n")

    assert sync(a, "ana").exit_code == 0
    assert (a / "state" / "open-loops.json").is_file()
    subjects = _git(a, "log", "--format=%s").stdout
    assert "jotd sync: derive ana" in subjects
    b = clone(origin, tmp_path / "b")
    assert (b / "state" / "open-loops.json").is_file()  # derived state travels


def test_non_librarian_sync_never_derives(tmp_path, monkeypatch):
    a, _ = make_machine_a(tmp_path, monkeypatch)
    with (a / "jotd.toml").open("a") as f:
        f.write('\n[team]\nlibrarian = "ana"\n')
    add(a, "from ben's machine", "ben")
    result = sync(a, "ben")
    assert result.exit_code == 0, result.output
    assert "derived state refreshed" not in result.output
    assert not (a / "state" / "open-loops.json").exists()


def test_slug_collision_warns_on_clean_pull(tmp_path, monkeypatch):
    a, origin = make_machine_a(tmp_path, monkeypatch)
    add(a, "seed", "ana")
    assert sync(a, "ana").exit_code == 0
    b = clone(origin, tmp_path / "b")
    add(b, "same-slug capture", "ana")  # second machine claiming 'ana'
    assert sync(b, "ana").exit_code == 0
    result = sync(a, "ana")  # nothing local — pull replays cleanly, warning fires
    assert result.exit_code == 0
    assert "warning: the remote also writes inbox files for author 'ana'" in result.output


def test_slug_collision_conflict_names_the_cause(tmp_path, monkeypatch):
    a, origin = make_machine_a(tmp_path, monkeypatch)
    add(a, "seed", "ana")
    assert sync(a, "ana").exit_code == 0
    b = clone(origin, tmp_path / "b")
    add(b, "b capture", "ana")
    assert sync(b, "ana").exit_code == 0
    add(a, "a capture", "ana")  # both machines appended to the SAME author file
    result = sync(a, "ana")
    assert result.exit_code == 2
    assert "sync conflict" in result.output
    assert "same author id" in result.output  # the collision diagnosis
    assert not (a / ".git" / "rebase-merge").exists()
