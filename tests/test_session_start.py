"""`jotd hook session-start` — the deterministic brief and its skip posture.

Mirrors test_session_hook.py's structure: JOTD_DIR points at a scaffold-free
data dir, payloads arrive as dicts, and the CLI wrapper must never fail."""

import json
import os
import time
from datetime import datetime
from pathlib import Path

from typer.testing import CliRunner

from jotd import brief as vbrief
from jotd import headless, inbox
from jotd.cli import app
from jotd.formats import format_processed_line

runner = CliRunner()

NOW = datetime.now().astimezone()
TODAY = NOW.date().isoformat()


def make_jotd_dir(tmp_path: Path, monkeypatch) -> Path:
    d = tmp_path / "jotd"
    (d / "inbox").mkdir(parents=True)
    (d / "state" / "logs").mkdir(parents=True)
    (d / "jotd.toml").write_text("[pulse]\n")
    monkeypatch.setenv("JOTD_DIR", str(d))
    monkeypatch.delenv(headless.HOOK_ENV_GUARD, raising=False)
    return d


def loop(loop_id, text, *, owner="me", stale=False, age=1, status="open"):
    return {
        "id": loop_id,
        "text": text,
        "note": "notes/projects/jotd.md",
        "owner": owner,
        "status": status,
        "age_days": age,
        "stale": stale,
    }


def seed_state(d: Path, loops=None):
    (d / "state").mkdir(exist_ok=True)
    loops = (
        loops
        if loops is not None
        else [
            loop(
                "cap-20260715-100000-aaaaaaaa", "ship the sync PR", owner="ana", stale=True, age=4
            ),
            loop("l-abc123", "email the supplier", age=1),
            loop("cap-20260101-100000-bbbbbbbb", "old done thing", status="done"),
        ]
    )
    (d / "state" / "open-loops.json").write_text(json.dumps({"generated": TODAY, "loops": loops}))


def payload(source="startup", cwd="/tmp/someproject", session_id="s-test"):
    return {"session_id": session_id, "source": source, "cwd": cwd}


def hook_log(d: Path) -> str:
    path = d / "state" / "logs" / "session-hook.log"
    return path.read_text() if path.is_file() else ""


def test_happy_path_brief_content(tmp_path, monkeypatch):
    d = make_jotd_dir(tmp_path, monkeypatch)
    seed_state(d)
    inbox.append_capture(d, "decided to relicense to MIT", author="ana")
    inbox.append_capture(d, "investigate flaky auth test", author="ben")
    inbox.append_capture(d, "a legacy capture with no author")
    ts = NOW.isoformat(timespec="seconds")
    inbox._append_line(
        d / "state" / "processed.log",
        format_processed_line("cap-20260719-090000-aabbccdd", ["notes/projects/jotd.md"], ts),
    )

    out = vbrief.run_session_start(payload())
    assert out is not None
    assert "ship the sync PR" in out and "STALE" in out and "[ana]" in out
    assert "old done thing" not in out  # non-open loops never shown
    assert "**ana**" in out and "**ben**" in out and "**unknown**" in out
    assert "notes/projects/jotd.md" in out
    assert "hook=start ok:" in hook_log(d)


def test_budget_enforced_whole_lines_only(tmp_path, monkeypatch):
    d = make_jotd_dir(tmp_path, monkeypatch)
    seed_state(d, loops=[loop(f"l-{i:06x}", f"loop {i}: " + "x" * 90, age=i) for i in range(300)])
    out = vbrief.build_brief(d)
    assert out is not None and len(out) <= vbrief.BRIEF_CHAR_BUDGET + 1
    assert out.endswith("\n")


def test_source_filtering(tmp_path, monkeypatch):
    d = make_jotd_dir(tmp_path, monkeypatch)
    seed_state(d)
    assert vbrief.run_session_start(payload(source="startup")) is not None
    assert vbrief.run_session_start(payload(source="clear")) is not None
    assert vbrief.run_session_start(payload(source="resume")) is None
    assert vbrief.run_session_start(payload(source="compact")) is None
    assert hook_log(d).count("skip: source=") == 2


def test_env_guard_blocks_recursion(tmp_path, monkeypatch):
    d = make_jotd_dir(tmp_path, monkeypatch)
    seed_state(d)
    monkeypatch.setenv(headless.HOOK_ENV_GUARD, "1")
    assert vbrief.run_session_start(payload()) is None
    assert hook_log(d) == ""  # silent — headless children don't even log


def test_session_in_data_dir_skips(tmp_path, monkeypatch):
    d = make_jotd_dir(tmp_path, monkeypatch)
    seed_state(d)
    assert vbrief.run_session_start(payload(cwd=str(d))) is None
    assert "jotd directory itself" in hook_log(d)


def test_unresolvable_data_dir_is_silent(tmp_path, monkeypatch):
    monkeypatch.delenv("JOTD_DIR", raising=False)
    monkeypatch.delenv(headless.HOOK_ENV_GUARD, raising=False)
    monkeypatch.setattr("jotd.config.POINTER_FILE", tmp_path / "nope")
    monkeypatch.setattr("jotd.config.DEFAULT_DATA_DIR", tmp_path / "absent")
    monkeypatch.chdir(tmp_path)
    assert vbrief.run_session_start(payload()) is None


def test_empty_state_prints_nothing(tmp_path, monkeypatch):
    d = make_jotd_dir(tmp_path, monkeypatch)
    assert vbrief.run_session_start(payload()) is None
    assert "nothing to brief" in hook_log(d)


def test_fresh_daily_brief_pointer_and_stale_exclusion(tmp_path, monkeypatch):
    d = make_jotd_dir(tmp_path, monkeypatch)
    seed_state(d)
    daily = d / "state" / "briefs" / f"{TODAY}.md"
    daily.parent.mkdir(parents=True)
    daily.write_text("# Daily brief\n")
    assert f"state/briefs/{TODAY}.md" in vbrief.build_brief(d)
    old = time.time() - 25 * 3600
    os.utime(daily, (old, old))
    assert f"state/briefs/{TODAY}.md" not in vbrief.build_brief(d)


def test_no_crash_without_git(tmp_path, monkeypatch):
    d = make_jotd_dir(tmp_path, monkeypatch)  # not a git repo at all
    seed_state(d)
    assert vbrief.build_brief(d) is not None
    monkeypatch.setattr(vbrief, "_git", lambda *a: None)  # no git binary
    assert vbrief.build_brief(d) is not None


def test_cli_hook_never_fails_and_is_silent_on_garbage(tmp_path, monkeypatch):
    monkeypatch.setenv("JOTD_DIR", str(tmp_path / "nowhere"))
    for stdin in ("not json", "", "[1,2,3]", json.dumps({"source": "startup"})):
        result = runner.invoke(app, ["hook", "session-start"], input=stdin)
        assert result.exit_code == 0, (stdin, result.output)
        assert result.output == ""


def test_cli_hook_prints_brief(tmp_path, monkeypatch):
    d = make_jotd_dir(tmp_path, monkeypatch)
    seed_state(d)
    result = runner.invoke(app, ["hook", "session-start"], input=json.dumps(payload()))
    assert result.exit_code == 0
    assert result.output.startswith("# jotd brief")


def seed_entities(d: Path, entities: dict):
    (d / "state").mkdir(exist_ok=True)
    (d / "state" / "entities.json").write_text(
        json.dumps({"generated": TODAY, "entities": entities})
    )


ATLAS = {"type": "project", "title": "Atlas", "aliases": [], "path": "notes/projects/atlas.md"}


def test_cwd_focus_reorders_loops_and_headers(tmp_path, monkeypatch):
    d = make_jotd_dir(tmp_path, monkeypatch)
    seed_entities(d, {"atlas": ATLAS, "jotd": {**ATLAS, "path": "notes/projects/jotd.md"}})
    atlas_loop = dict(loop("l-atlas1", "wire the atlas ingest"), note="notes/projects/atlas.md")
    seed_state(
        d,
        loops=[
            loop("l-jotd1", "ship the sync PR", stale=True, age=9),  # normally ranked first
            atlas_loop,
        ],
    )
    out = vbrief.run_session_start(payload(cwd="/Users/x/dev/atlas"))
    assert out is not None
    assert "focus: atlas (notes/projects/atlas.md)" in out
    assert out.index("wire the atlas ingest") < out.index("ship the sync PR")


def test_cwd_git_remote_matches_when_basename_does_not(tmp_path, monkeypatch):
    import shutil as _shutil
    import subprocess

    if _shutil.which("git") is None:
        import pytest

        pytest.skip("git required")
    d = make_jotd_dir(tmp_path, monkeypatch)
    seed_entities(d, {"atlas": ATLAS})
    seed_state(d, loops=[dict(loop("l-a", "atlas thing"), note="notes/projects/atlas.md")])
    checkout = tmp_path / "work-checkout"  # basename matches nothing
    checkout.mkdir()
    subprocess.run(["git", "init", "-q", str(checkout)], check=True)
    subprocess.run(
        ["git", "-C", str(checkout), "remote", "add", "origin", "git@github.com:me/atlas.git"],
        check=True,
    )
    out = vbrief.build_brief(d, cwd=str(checkout))
    assert out is not None and "focus: atlas" in out


def test_alias_and_containment_matching(tmp_path, monkeypatch):
    d = make_jotd_dir(tmp_path, monkeypatch)
    seed_state(d, loops=[dict(loop("l-a", "a loop"), note="notes/projects/atlas.md")])

    # exact slugified-alias match
    seed_entities(d, {"deep-research": {**ATLAS, "aliases": ["DR Project"]}})
    assert "focus: deep-research" in vbrief.build_brief(d, cwd="/dev/dr-project")

    # containment either direction, shorter side >= 4 chars
    seed_entities(d, {"atlas": ATLAS})
    assert "focus: atlas" in vbrief.build_brief(d, cwd="/dev/atlas-api")

    # 3-char slugs never containment-match
    seed_entities(d, {"api": {**ATLAS, "path": "notes/projects/api.md"}})
    assert "focus:" not in vbrief.build_brief(d, cwd="/dev/api-gateway")


def test_no_match_is_byte_identical(tmp_path, monkeypatch):
    d = make_jotd_dir(tmp_path, monkeypatch)
    seed_entities(d, {"atlas": ATLAS})
    seed_state(d)
    inbox.append_capture(d, "a capture", author="ana")
    baseline = vbrief.build_brief(d, now=NOW)
    assert vbrief.build_brief(d, now=NOW, cwd="/tmp/zzz-unrelated") == baseline
    assert vbrief.build_brief(d, now=NOW, cwd=None) == baseline


def test_focus_prefers_routed_captures(tmp_path, monkeypatch):
    d = make_jotd_dir(tmp_path, monkeypatch)
    seed_entities(d, {"atlas": ATLAS})
    seed_state(d, loops=[dict(loop("l-a", "a loop"), note="notes/projects/atlas.md")])
    routed = inbox.append_capture(d, "the atlas decision", author="ana")
    for i in range(3):
        inbox.append_capture(d, f"newer noise {i}", author="ana")
    ts = NOW.isoformat(timespec="seconds")
    inbox._append_line(
        d / "state" / "processed.log",
        format_processed_line(routed["id"], ["notes/projects/atlas.md"], ts),
    )
    plain = vbrief.build_brief(d, now=NOW)
    assert "the atlas decision" not in plain  # newest-3 default drops the oldest
    focused = vbrief.build_brief(d, now=NOW, cwd="/dev/atlas")
    assert "the atlas decision" in focused


def test_entities_missing_falls_back_to_project_filenames(tmp_path, monkeypatch):
    d = make_jotd_dir(tmp_path, monkeypatch)  # no entities.json at all
    (d / "notes" / "projects").mkdir(parents=True)
    (d / "notes" / "projects" / "atlas.md").write_text("---\ntitle: Atlas\n---\n")
    seed_state(d, loops=[dict(loop("l-a", "a loop"), note="notes/projects/atlas.md")])
    assert "focus: atlas (notes/projects/atlas.md)" in vbrief.build_brief(d, cwd="/dev/atlas")


def test_focus_budget_still_enforced(tmp_path, monkeypatch):
    d = make_jotd_dir(tmp_path, monkeypatch)
    seed_entities(d, {"atlas": ATLAS})
    seed_state(
        d,
        loops=[
            dict(
                loop(f"l-{i:06x}", f"loop {i}: " + "x" * 90, age=i),
                note="notes/projects/atlas.md",
            )
            for i in range(300)
        ],
    )
    out = vbrief.build_brief(d, cwd="/dev/atlas")
    assert out is not None and len(out) <= vbrief.BRIEF_CHAR_BUDGET + 1
    assert "focus: atlas" in out


def test_pulse_child_carries_env_guard(tmp_path, monkeypatch):
    from jotd import pulse as vpulse
    from jotd.config import PulseConfig

    seen = {}

    def fake_invoke(prompt, **kwargs):
        seen.update(kwargs)
        return "{}"

    monkeypatch.setattr(vpulse.headless, "invoke_claude", fake_invoke)
    vpulse._invoke_claude(tmp_path, PulseConfig(), "packet", "body")
    assert seen["extra_env"] == {headless.HOOK_ENV_GUARD: "1"}
