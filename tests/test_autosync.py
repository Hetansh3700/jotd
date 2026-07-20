"""`jotd sync --auto` — the scheduled propagation run (D13): config parsing,
lock/marker discipline, the one-shot conflict notification, the librarian-only
backlog trigger, and the post-organize code guards.

Same two-machine harness as test_sync.py (bare origin, --author identity).
The LLM seam is autosync._run_organize, monkeypatched one level above the
subprocess exactly like test_pulse.py does with _invoke_claude."""

import fcntl
import shutil
import subprocess
from datetime import datetime, timedelta

import pytest
from typer.testing import CliRunner

from jotd import autosync, inbox
from jotd import init as vinit
from jotd.autosync import run_auto_sync
from jotd.cli import app
from jotd.config import load_sync

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git required")
runner = CliRunner()


@pytest.fixture(autouse=True)
def no_git_identity(monkeypatch, tmp_path_factory):
    empty = tmp_path_factory.mktemp("gitcfg") / "empty"
    empty.write_text("")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(empty))
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", str(empty))


@pytest.fixture(autouse=True)
def sent(monkeypatch):
    """Notifications must never actually fire in tests; record them instead."""
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        autosync.notify,
        "send",
        lambda title, message, channel="macos": calls.append((title, message)),
    )
    return calls


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=False)


def make_machine(tmp_path, monkeypatch, librarian=None):
    monkeypatch.setattr(vinit, "POINTER_FILE", tmp_path / "pointer")
    a = tmp_path / "a"
    assert runner.invoke(app, ["init", str(a)]).exit_code == 0
    origin = tmp_path / "origin.git"
    subprocess.run(
        ["git", "init", "--bare", "-q", "-b", "main", str(origin)],
        check=True,
        capture_output=True,
    )
    _git(a, "remote", "add", "origin", str(origin))
    if librarian:
        with (a / "jotd.toml").open("a") as f:
            f.write(f'\n[team]\nlibrarian = "{librarian}"\n')
    return a, origin


def add(d, text, author):
    assert runner.invoke(app, ["add", text, "--author", author, "--dir", str(d)]).exit_code == 0


def log_text(d):
    path = d / "state" / "logs" / "sync-auto.log"
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def boom(*args, **kwargs):
    raise AssertionError("organize must not run here")


def test_auto_flag_exits_zero_and_prints_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(vinit, "POINTER_FILE", tmp_path / "pointer")
    d = tmp_path / "v"
    runner.invoke(app, ["init", str(d)])  # git repo but NO origin remote
    result = runner.invoke(app, ["sync", "--auto", "--author", "ana", "--dir", str(d)])
    assert result.exit_code == 0
    assert result.output == ""
    assert "auto-sync error: no 'origin' remote" in log_text(d)


def test_auto_happy_path_logs_ok(tmp_path, monkeypatch, sent):
    a, _ = make_machine(tmp_path, monkeypatch)
    add(a, "a thought", "ana")
    out = run_auto_sync(a, "ana")
    assert out["status"] == "ok" and out["organize"] is None
    assert "auto-sync ok: backlog=1" in log_text(a)
    assert sent == []


def test_conflict_notifies_once_and_recovers(tmp_path, monkeypatch, sent):
    a, origin = make_machine(tmp_path, monkeypatch)
    add(a, "seed", "ana")
    assert run_auto_sync(a, "ana")["status"] == "ok"
    b = tmp_path / "b"
    subprocess.run(["git", "clone", "-q", str(origin), str(b)], check=True, capture_output=True)

    (a / "notes" / "topics" / "unsorted.md").write_text("frontmatter\nA's line\n")
    assert run_auto_sync(a, "ana")["status"] == "ok"
    (b / "notes" / "topics" / "unsorted.md").write_text("frontmatter\nB's line\n")

    out = run_auto_sync(b, "ben")
    assert out["status"] == "conflict"
    assert len(sent) == 1  # first tick of the episode notifies
    marker = b / "state" / "logs" / "sync-auto.conflict"
    assert marker.is_file()

    assert run_auto_sync(b, "ben")["status"] == "conflict"
    assert len(sent) == 1  # later ticks stay quiet

    # human resolves by taking the remote side, next tick recovers
    _git(b, "checkout", "--theirs", ".")
    proc = _git(b, "pull", "--rebase", "origin", "main")
    if proc.returncode != 0:
        _git(b, "checkout", "--theirs", "notes/topics/unsorted.md")
        _git(b, "add", "-A")
        _git(b, "rebase", "--continue")
    out = run_auto_sync(b, "ben")
    assert out["status"] == "ok"
    assert not marker.exists()
    assert "auto-sync recovered: clean sync after conflict" in log_text(b)
    assert len(sent) == 1


def test_lock_skips_overlap(tmp_path, monkeypatch):
    a, _ = make_machine(tmp_path, monkeypatch)
    lock_path = a / "state" / "logs" / ".sync-auto.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    holder = open(lock_path, "w")
    fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        out = run_auto_sync(a, "ana")
    finally:
        holder.close()
    assert out["status"] == "skipped"
    assert "auto-sync skip: another auto-sync holds the lock" in log_text(a)


def test_below_threshold_never_invokes_organize(tmp_path, monkeypatch):
    a, _ = make_machine(tmp_path, monkeypatch, librarian="ana")
    monkeypatch.setattr(autosync, "_run_organize", boom)
    add(a, "only one capture", "ana")
    out = run_auto_sync(a, "ana")  # threshold is 5 (template default)
    assert out["status"] == "ok" and out["organize"] is None
    assert "below threshold 5" in log_text(a)


def test_non_librarian_never_invokes_organize(tmp_path, monkeypatch):
    a, _ = make_machine(tmp_path, monkeypatch, librarian="ana")
    monkeypatch.setattr(autosync, "_run_organize", boom)
    for i in range(6):
        add(a, f"capture {i}", "ben")
    out = run_auto_sync(a, "ben")
    assert out["status"] == "ok" and out["organize"] is None
    assert "no organize on this machine" in log_text(a)


def test_backlog_triggers_organize_then_pushes(tmp_path, monkeypatch):
    a, origin = make_machine(tmp_path, monkeypatch, librarian="ana")
    for i in range(5):
        add(a, f"capture {i}", "ana")

    def fake_organize(data_dir, model, timeout_s):
        note = data_dir / "notes" / "topics" / "unsorted.md"
        with note.open("a") as f:
            f.write("\n## Log\n- routed by fake organize\n")
        for r in inbox.unprocessed(data_dir):
            inbox.mark_processed(data_dir, r["id"], ["notes/topics/unsorted.md"])
        return "done"

    monkeypatch.setattr(autosync, "_run_organize", fake_organize)
    out = run_auto_sync(a, "ana")
    assert out["status"] == "ok" and out["organize"] == "ok"
    assert len(inbox.unprocessed(a)) == 0
    assert not (a / "state" / "logs" / "organize.cooldown").exists()
    assert "auto-sync organize-ok: backlog 5 -> 0" in log_text(a)

    fresh = tmp_path / "fresh"
    subprocess.run(["git", "clone", "-q", str(origin), str(fresh)], check=True, capture_output=True)
    assert "routed by fake organize" in (fresh / "notes" / "topics" / "unsorted.md").read_text()
    assert (fresh / "state" / "processed.log").is_file()  # routed result shipped


def test_organize_failure_sets_cooldown_and_still_syncs(tmp_path, monkeypatch):
    a, origin = make_machine(tmp_path, monkeypatch, librarian="ana")
    for i in range(5):
        add(a, f"capture {i}", "ana")

    def failing(data_dir, model, timeout_s):
        raise RuntimeError("claude exited 1: boom")

    monkeypatch.setattr(autosync, "_run_organize", failing)
    out = run_auto_sync(a, "ana")
    assert out["status"] == "ok" and out["organize"] == "failed"  # sync #2 still shipped
    cooldown = a / "state" / "logs" / "organize.cooldown"
    assert cooldown.is_file()
    datetime.fromisoformat(cooldown.read_text().strip())  # parseable ts
    assert "auto-sync organize-error: claude exited 1: boom" in log_text(a)

    # within the cooldown the next tick must not attempt organize
    monkeypatch.setattr(autosync, "_run_organize", boom)
    out = run_auto_sync(a, "ana")
    assert out["organize"] == "skipped: cooldown"

    # a stale cooldown (older than the window) retries
    stale = datetime.now().astimezone() - timedelta(hours=autosync.ORGANIZE_COOLDOWN_HOURS + 1)
    cooldown.write_text(stale.isoformat(timespec="seconds"))
    calls = []
    monkeypatch.setattr(
        autosync, "_run_organize", lambda *args: calls.append(args) or "did nothing"
    )
    run_auto_sync(a, "ana")
    assert len(calls) == 1


def test_backlog_not_reduced_counts_as_failure(tmp_path, monkeypatch):
    a, _ = make_machine(tmp_path, monkeypatch, librarian="ana")
    for i in range(5):
        add(a, f"capture {i}", "ana")
    monkeypatch.setattr(autosync, "_run_organize", lambda *args: "looked busy, did nothing")
    out = run_auto_sync(a, "ana")
    assert out["organize"] == "failed"
    assert (a / "state" / "logs" / "organize.cooldown").is_file()
    assert "backlog did not decrease" in log_text(a)


def test_inbox_rewrite_restored_appends_survive(tmp_path, monkeypatch, sent):
    a, _ = make_machine(tmp_path, monkeypatch, librarian="ana")
    for i in range(5):
        add(a, f"capture {i}", "ana")
    add(a, "ben seed", "ben")  # ben's file exists in the snapshot
    ana_file = next(p for p in (a / "inbox").glob("*.ana.jsonl"))
    ben_file = next(p for p in (a / "inbox").glob("*.ben.jsonl"))
    ana_bytes = ana_file.read_bytes()

    def evil_organize(data_dir, model, timeout_s):
        ana_file.write_bytes(b'{"rewritten": true}\n')  # rewrite: must be restored
        (data_dir / "inbox" / "evil.jsonl").write_text("not a capture\n")  # must be unlinked
        # a legit concurrent capture appends to ben's snapshotted file: must survive
        inbox.append_capture(data_dir, "landed mid-organize", author="ben")
        return "done"

    monkeypatch.setattr(autosync, "_run_organize", evil_organize)
    out = run_auto_sync(a, "ana")

    assert ana_file.read_bytes() == ana_bytes  # byte-identical restore
    assert not (a / "inbox" / "evil.jsonl").exists()
    assert "landed mid-organize" in ben_file.read_text()
    assert "auto-sync guard:" in log_text(a)
    assert any("auto-organize touched the inbox" in msg for _, msg in sent)
    assert out["status"] == "ok"  # the run still ships what's valid


def test_pulse_lock_held_skips_organize(tmp_path, monkeypatch):
    a, _ = make_machine(tmp_path, monkeypatch, librarian="ana")
    for i in range(5):
        add(a, f"capture {i}", "ana")
    monkeypatch.setattr(autosync, "_run_organize", boom)
    pulse_lock = open(a / "state" / ".pulse.lock", "w")
    fcntl.flock(pulse_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        out = run_auto_sync(a, "ana")
    finally:
        pulse_lock.close()
    assert out["status"] == "ok"
    assert out["organize"] == "skipped: pulse in flight"
    assert "auto-sync organize-skip: pulse in flight" in log_text(a)


def test_load_sync_defaults_when_absent(tmp_path):
    cfg = load_sync(tmp_path)  # no jotd.toml at all
    assert cfg.auto is False
    assert cfg.interval_minutes == 15
    assert cfg.organize_backlog == 5
    assert cfg.organize_timeout_s == 2400
    assert cfg.organize_model is None


def test_load_sync_parsing(tmp_path):
    (tmp_path / "jotd.toml").write_text(
        "[sync]\n"
        "auto = true\n"
        "interval_minutes = 30\n"
        "organize_backlog = 0\n"
        "organize_timeout_s = 600\n"
        'organize_model = "opus"\n',
        encoding="utf-8",
    )
    cfg = load_sync(tmp_path)
    assert cfg.auto is True
    assert cfg.interval_minutes == 30
    assert cfg.organize_backlog == 0
    assert cfg.organize_timeout_s == 600
    assert cfg.organize_model == "opus"


def test_load_sync_clamps_bad_interval(tmp_path):
    (tmp_path / "jotd.toml").write_text("[sync]\ninterval_minutes = 0\n", encoding="utf-8")
    assert load_sync(tmp_path).interval_minutes == 15
    (tmp_path / "jotd.toml").write_text('[sync]\ninterval_minutes = "soon"\n', encoding="utf-8")
    assert load_sync(tmp_path).interval_minutes == 15
