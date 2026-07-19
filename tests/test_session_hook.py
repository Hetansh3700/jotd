import json
from pathlib import Path

from typer.testing import CliRunner

from jotd import inbox
from jotd import session_capture as sc
from jotd.cli import app

runner = CliRunner()


def make_jotd_dir(tmp_path: Path, monkeypatch) -> Path:
    d = tmp_path / "jotd"
    (d / "inbox").mkdir(parents=True)
    (d / "state" / "logs").mkdir(parents=True)
    (d / "jotd.toml").write_text("[pulse]\n")
    monkeypatch.setenv("JOTD_DIR", str(d))
    monkeypatch.delenv(sc.HOOK_ENV_GUARD, raising=False)
    return d


def _user(text):
    return {"type": "user", "message": {"role": "user", "content": text}}


def _assistant(text):
    return {
        "type": "assistant",
        "message": {"role": "assistant", "content": [{"type": "text", "text": text}]},
    }


def make_transcript(tmp_path: Path, entries) -> Path:
    path = tmp_path / "transcript.jsonl"
    path.write_text("\n".join(json.dumps(e) for e in entries) + "\n")
    return path


DEFAULT_ENTRIES = [
    _user("refactor the atlas auth flow"),
    _assistant("done — moved token refresh into middleware"),
    _user("also file a follow-up for the session bug"),
    _assistant("noted, you should ask Sarah about the session bug"),
]


def payload(transcript: Path | None, cwd="/tmp/someproject", reason="other"):
    p = {"session_id": "s-test", "cwd": cwd, "reason": reason}
    if transcript is not None:
        p["transcript_path"] = str(transcript)
    return p


def scribe_reply(*texts):
    def fake(data_dir, model, prompt):
        return json.dumps({"captures": [{"text": t} for t in texts]})

    return fake


def forbid_scribe(monkeypatch):
    def fail(*a, **k):
        raise AssertionError("scribe must not be invoked")

    monkeypatch.setattr(sc, "_invoke_scribe", fail)


def hook_log(d: Path) -> str:
    path = d / "state" / "logs" / "session-hook.log"
    return path.read_text() if path.is_file() else ""


def test_happy_path_appends_fragments(tmp_path, monkeypatch):
    d = make_jotd_dir(tmp_path, monkeypatch)
    t = make_transcript(tmp_path, DEFAULT_ENTRIES)
    monkeypatch.setattr(
        sc, "_invoke_scribe", scribe_reply("atlas: refactored auth", "ask Sarah about atlas bug")
    )
    result = sc.run_session_end(payload(t))
    assert result["status"] == "ok" and len(result["appended"]) == 2
    records = inbox.unprocessed(d)
    assert [r["text"] for r in records] == ["atlas: refactored auth", "ask Sarah about atlas bug"]
    for r in records:
        assert r["source"] == "claude-code"
        assert r["context"] == {
            "app": "Claude Code",
            "title": "someproject",
            "method": "session-end",
        }
    assert "ok: appended=2 rejected=0" in hook_log(d)


def test_reason_clear_skips_without_scribe(tmp_path, monkeypatch):
    make_jotd_dir(tmp_path, monkeypatch)
    forbid_scribe(monkeypatch)
    t = make_transcript(tmp_path, DEFAULT_ENTRIES)
    assert sc.run_session_end(payload(t, reason="clear"))["status"] == "skip"


def test_env_guard_blocks_recursion(tmp_path, monkeypatch):
    make_jotd_dir(tmp_path, monkeypatch)
    forbid_scribe(monkeypatch)
    monkeypatch.setenv(sc.HOOK_ENV_GUARD, "1")
    result = sc.run_session_end(payload(make_transcript(tmp_path, DEFAULT_ENTRIES)))
    assert result["status"] == "skip" and "subprocess" in result["detail"]


def test_session_in_data_dir_skips(tmp_path, monkeypatch):
    d = make_jotd_dir(tmp_path, monkeypatch)
    forbid_scribe(monkeypatch)
    result = sc.run_session_end(payload(make_transcript(tmp_path, DEFAULT_ENTRIES), cwd=str(d)))
    assert result["status"] == "skip"
    assert "jotd directory itself" in hook_log(d)


def test_unresolvable_data_dir_is_a_clean_skip(tmp_path, monkeypatch):
    monkeypatch.delenv("JOTD_DIR", raising=False)
    monkeypatch.delenv(sc.HOOK_ENV_GUARD, raising=False)
    monkeypatch.setattr("jotd.config.POINTER_FILE", tmp_path / "nope")
    monkeypatch.setattr("jotd.config.DEFAULT_DATA_DIR", tmp_path / "absent")
    monkeypatch.chdir(tmp_path)
    forbid_scribe(monkeypatch)
    result = sc.run_session_end(payload(make_transcript(tmp_path, DEFAULT_ENTRIES)))
    assert result["status"] == "skip" and "not a jotd directory" in result["detail"]


def test_missing_transcript_skips(tmp_path, monkeypatch):
    d = make_jotd_dir(tmp_path, monkeypatch)
    forbid_scribe(monkeypatch)
    assert sc.run_session_end(payload(None))["status"] == "skip"
    assert sc.run_session_end(payload(tmp_path / "ghost.jsonl"))["status"] == "skip"
    assert hook_log(d).count("transcript missing") == 2


def test_manual_capture_dedupe_skips(tmp_path, monkeypatch):
    d = make_jotd_dir(tmp_path, monkeypatch)
    forbid_scribe(monkeypatch)
    entries = DEFAULT_ENTRIES + [
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "name": "Bash",
                        "input": {"command": "jotd capture - --source claude-code <<'EOF'\nx\nEOF"},
                    }
                ],
            },
        }
    ]
    result = sc.run_session_end(payload(make_transcript(tmp_path, entries)))
    assert result["status"] == "skip"
    assert "already captured manually" in hook_log(d)


def test_dedupe_ignores_command_string_in_file_contents(tmp_path, monkeypatch):
    # the marker appearing in a tool_result (e.g. reading jotd's own source) must NOT skip
    make_jotd_dir(tmp_path, monkeypatch)
    entries = DEFAULT_ENTRIES + [
        {
            "type": "user",
            "message": {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "content": "docs say: jotd capture - --source claude-code",
                    }
                ],
            },
        }
    ]
    monkeypatch.setattr(sc, "_invoke_scribe", scribe_reply("one fragment"))
    assert sc.run_session_end(payload(make_transcript(tmp_path, entries)))["status"] == "ok"


def test_trivial_session_skips_scribe(tmp_path, monkeypatch):
    d = make_jotd_dir(tmp_path, monkeypatch)
    forbid_scribe(monkeypatch)
    t = make_transcript(tmp_path, [_user("hi"), _assistant("hello")])
    assert sc.run_session_end(payload(t))["status"] == "skip"
    assert "too small (1 user messages)" in hook_log(d)


def test_scribe_garbage_writes_nothing(tmp_path, monkeypatch):
    d = make_jotd_dir(tmp_path, monkeypatch)
    t = make_transcript(tmp_path, DEFAULT_ENTRIES)
    monkeypatch.setattr(sc, "_invoke_scribe", lambda *a, **k: "sure! here are my thoughts...")
    result = sc.run_session_end(payload(t))
    assert result["status"] == "error" and result["appended"] == []
    assert inbox.unprocessed(d) == []
    assert "error:" in hook_log(d)


def test_fragment_budget_enforced_in_code(tmp_path, monkeypatch):
    d = make_jotd_dir(tmp_path, monkeypatch)
    t = make_transcript(tmp_path, DEFAULT_ENTRIES)
    monkeypatch.setattr(sc, "_invoke_scribe", scribe_reply(*[f"fragment {i}" for i in range(8)]))
    result = sc.run_session_end(payload(t))
    assert len(result["appended"]) == sc.MAX_FRAGMENTS
    assert len(inbox.unprocessed(d)) == sc.MAX_FRAGMENTS


def test_oversize_fragment_rejected_never_truncated(tmp_path, monkeypatch):
    d = make_jotd_dir(tmp_path, monkeypatch)
    t = make_transcript(tmp_path, DEFAULT_ENTRIES)
    # 1200 chars (under MAX_FRAGMENT_CHARS) but 4800 UTF-8 bytes (over the line cap)
    fat = "\U0001f984" * 1200
    monkeypatch.setattr(sc, "_invoke_scribe", scribe_reply("keeper", fat))
    result = sc.run_session_end(payload(t))
    assert len(result["appended"]) == 1
    assert [r["text"] for r in inbox.unprocessed(d)] == ["keeper"]
    assert "ok: appended=1 rejected=1" in hook_log(d)


def test_extract_digest_counts_and_skips_tool_noise(tmp_path):
    entries = [
        _user("first task"),
        {
            "type": "user",
            "message": {
                "role": "user",
                "content": [{"type": "tool_result", "content": "x" * 9999}],
            },
        },
        _assistant("working on it"),
        _user("second ask"),
        {"type": "summary", "summary": "should be ignored"},
    ]
    digest, user_count = sc.extract_digest(make_transcript(tmp_path, entries))
    assert user_count == 2  # tool_result entries are not user messages
    assert "x" * 100 not in digest
    assert "USER: first task" in digest and "ASSISTANT: working on it" in digest


def test_extract_digest_budget_keeps_task_and_tail(tmp_path):
    entries = [_user("the original task statement")] + [
        _assistant(f"progress {i}: " + "y" * 400) for i in range(30)
    ]
    digest, _ = sc.extract_digest(make_transcript(tmp_path, entries), budget=3000)
    assert digest.startswith("USER: the original task statement")
    assert "progress 29" in digest  # the tail survives
    assert len(digest) < 3200


def test_scribe_captures_carry_author(tmp_path, monkeypatch):
    d = make_jotd_dir(tmp_path, monkeypatch)
    monkeypatch.setenv("JOTD_AUTHOR", "zed")
    t = make_transcript(tmp_path, DEFAULT_ENTRIES)
    monkeypatch.setattr(sc, "_invoke_scribe", scribe_reply("a durable fact"))
    assert sc.run_session_end(payload(t))["status"] == "ok"
    (record,) = inbox.unprocessed(d)
    assert record["author"] == "zed"
    assert any(".zed." in p.name for p in (d / "inbox").glob("*.jsonl"))


def test_cli_hook_never_fails(tmp_path, monkeypatch):
    monkeypatch.setenv("JOTD_DIR", str(tmp_path / "nowhere"))
    for stdin in ("not json", "", "[1,2,3]", json.dumps({"reason": "other"})):
        result = runner.invoke(app, ["hook", "session-end"], input=stdin)
        assert result.exit_code == 0, (stdin, result.output)
