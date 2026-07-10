import json
from datetime import date
from pathlib import Path

from jotd import pulse as pulse_mod
from jotd import pulselog
from jotd.config import load_config
from jotd.pulse import build_packet, run_pulse, validate_output

TODAY = date(2026, 7, 8)

AGENT_MD = """---
name: pulse
tools: Read, Grep, Glob
---
You are the pulse. (test stub)
"""


def make_jotd_dir(tmp_path: Path) -> Path:
    (tmp_path / "jotd.toml").write_text('[pulse]\nchannel = "stdout"\n')
    (tmp_path / "state").mkdir()
    agents = tmp_path / ".claude" / "agents"
    agents.mkdir(parents=True)
    (agents / "pulse.md").write_text(AGENT_MD)
    projects = tmp_path / "notes" / "projects"
    projects.mkdir(parents=True)
    (projects / "atlas.md").write_text(
        "---\ntype: project\ntitle: Atlas\naliases: []\ncreated: 2026-06-01\n---\n"
        "## Log\n\n## Open loops\n"
        "- [ ] send sarah the q3 numbers by wednesday <!-- loop:cap-20260701-090000-aaaaaaaa -->\n"
        "- [ ] write the postmortem <!-- loop:cap-20260703-090000-bbbbbbbb -->\n"
        "- [ ] renew pagerduty <!-- loop:cap-20260705-090000-cccccccc -->\n"
        "- [ ] check the numbers <!-- loop:cap-20260706-090000-dddddddd -->\n"
    )
    (tmp_path / "state" / "processed.log").write_text(
        "cap-20260701-090000-aaaaaaaa notes/projects/atlas.md 2026-07-01T09:05:00-07:00\n"
    )
    (tmp_path / "inbox").mkdir()
    return tmp_path


def model_reply(nudges=None, suppressed=None, brief=None):
    def fake_invoke(data_dir, cfg, prompt, agent_body):
        return json.dumps({"nudges": nudges or [], "suppressed": suppressed or [], "brief": brief})

    return fake_invoke


def read_kinds(jotd_dir):
    return [e["kind"] for e in pulselog.read_events(jotd_dir)]


def test_happy_path_nudge_and_suppress(tmp_path, monkeypatch, capsys):
    jotd_dir = make_jotd_dir(tmp_path)
    monkeypatch.setattr(
        pulse_mod,
        "_invoke_claude",
        model_reply(
            nudges=[
                {
                    "loop_id": "cap-20260701-090000-aaaaaaaa",
                    "text": "send Sarah the Q3 numbers",
                    "reason": "7d stale, deadline",
                },
                {"loop_id": "cap-99999999-000000-ffffffff", "text": "hallucinated", "reason": "x"},
            ],
            suppressed=[
                {"loop_id": "cap-20260706-090000-dddddddd", "reason": "2d old, no deadline"}
            ],
        ),
    )
    result = run_pulse(jotd_dir, "midday", today=TODAY)
    assert result["status"] == "ok"
    assert [n["loop_id"] for n in result["nudges"]] == ["cap-20260701-090000-aaaaaaaa"]
    assert result["runner_rejected"][0]["reason"] == "runner: unknown or ineligible loop id"
    out = capsys.readouterr().out
    assert "jotd done|snooze|drop aaaaaaaa" in out  # notification carries the responder id
    events = pulselog.read_events(jotd_dir)
    kinds = [e["kind"] for e in events]
    assert kinds.count("nudge") == 1 and kinds.count("suppress") == 2
    assert kinds[-1] == "heartbeat"
    hb = events[-1]
    assert hb["status"] == "ok" and hb["nudges"] == "1" and hb["suppressed"] == "2"


def test_budget_enforced_in_code_not_prompts(tmp_path, monkeypatch, capsys):
    jotd_dir = make_jotd_dir(tmp_path)
    ids = [
        "cap-20260701-090000-aaaaaaaa",
        "cap-20260703-090000-bbbbbbbb",
        "cap-20260705-090000-cccccccc",
        "cap-20260706-090000-dddddddd",
    ]
    monkeypatch.setattr(
        pulse_mod,
        "_invoke_claude",
        model_reply(nudges=[{"loop_id": i, "text": "t", "reason": "r"} for i in ids]),
    )
    result = run_pulse(jotd_dir, "midday", today=TODAY)
    assert len(result["nudges"]) == 3  # max_nudges_per_run
    assert [r["reason"] for r in result["runner_rejected"]] == ["runner: over budget"]
    assert capsys.readouterr().out.count("[jotd]") == 3


def test_daily_cap_spans_runs(tmp_path, monkeypatch):
    jotd_dir = make_jotd_dir(tmp_path)
    for i in range(5):
        pulselog.append_event(
            jotd_dir,
            "nudge",
            f"2026-07-08T08:0{i}:00-07:00",
            loop_id=f"cap-old-{i}",
            text="t",
            reason="r",
        )
    monkeypatch.setattr(
        pulse_mod,
        "_invoke_claude",
        model_reply(
            nudges=[
                {"loop_id": "cap-20260701-090000-aaaaaaaa", "text": "a", "reason": "r"},
                {"loop_id": "cap-20260703-090000-bbbbbbbb", "text": "b", "reason": "r"},
            ]
        ),
    )
    result = run_pulse(jotd_dir, "evening", today=TODAY)
    assert len(result["nudges"]) == 1  # 6/day cap minus 5 already sent


def test_model_garbage_sends_nothing(tmp_path, monkeypatch, capsys):
    jotd_dir = make_jotd_dir(tmp_path)
    monkeypatch.setattr(pulse_mod, "_invoke_claude", lambda *a: "I think you should relax today.")
    result = run_pulse(jotd_dir, "midday", today=TODAY)
    assert result["status"] == "error"
    assert capsys.readouterr().out == ""  # no notifications
    events = pulselog.read_events(jotd_dir)
    assert [e["kind"] for e in events] == ["heartbeat"]
    assert events[0]["status"] == "error"


def test_schema_violation_sends_nothing(tmp_path, monkeypatch):
    jotd_dir = make_jotd_dir(tmp_path)
    monkeypatch.setattr(
        pulse_mod,
        "_invoke_claude",
        lambda *a: json.dumps({"nudges": [{"loop_id": "cap-x"}], "suppressed": []}),
    )
    result = run_pulse(jotd_dir, "midday", today=TODAY)
    assert result["status"] == "error"
    assert "schema" in result["error"]


def test_morning_writes_brief_even_with_empty_jotd_dir(tmp_path, monkeypatch, capsys):
    jotd_dir = make_jotd_dir(tmp_path)
    monkeypatch.setattr(
        pulse_mod,
        "_invoke_claude",
        model_reply(
            suppressed=[{"loop_id": "cap-20260701-090000-aaaaaaaa", "reason": "brief covers it"}],
            brief="## Today\ncalendar not connected\n",
        ),
    )
    result = run_pulse(jotd_dir, "morning", today=TODAY)
    assert result["status"] == "ok"
    brief = jotd_dir / "state" / "briefs" / "2026-07-08.md"
    assert brief.is_file() and "calendar not connected" in brief.read_text()
    assert "daily brief" in capsys.readouterr().out


def test_quiet_nonmorning_slot_skips_the_llm(tmp_path, monkeypatch):
    jotd_dir = make_jotd_dir(tmp_path)
    (jotd_dir / "notes" / "projects" / "atlas.md").write_text(
        "---\ntype: project\ntitle: Atlas\naliases: []\ncreated: 2026-06-01\n---\n## Log\n"
    )

    def boom(*a):
        raise AssertionError("LLM must not be invoked when nothing is eligible")

    monkeypatch.setattr(pulse_mod, "_invoke_claude", boom)
    result = run_pulse(jotd_dir, "evening", today=TODAY)
    assert result["status"] == "ok" and result.get("skipped_llm") is True
    assert read_kinds(jotd_dir) == ["heartbeat"]


def test_dry_run_writes_and_sends_nothing(tmp_path, monkeypatch, capsys):
    jotd_dir = make_jotd_dir(tmp_path)
    monkeypatch.setattr(
        pulse_mod,
        "_invoke_claude",
        model_reply(
            nudges=[{"loop_id": "cap-20260701-090000-aaaaaaaa", "text": "t", "reason": "r"}]
        ),
    )
    result = run_pulse(jotd_dir, "midday", dry_run=True, today=TODAY)
    assert result["status"] == "ok"
    assert any("would nudge" in a for a in result["actions"])
    assert pulselog.read_events(jotd_dir) == []
    assert "[jotd]" not in capsys.readouterr().out


def test_concurrent_run_skips_via_lock(tmp_path, monkeypatch):
    import fcntl

    jotd_dir = make_jotd_dir(tmp_path)
    holder = open(jotd_dir / "state" / ".pulse.lock", "w")
    fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)
    monkeypatch.setattr(pulse_mod, "_invoke_claude", model_reply())
    result = run_pulse(jotd_dir, "midday", today=TODAY)
    assert result["status"] == "skipped"
    events = pulselog.read_events(jotd_dir)
    assert events[-1]["status"] == "skipped"
    holder.close()


def test_packet_excludes_snoozed_and_silenced(tmp_path):
    jotd_dir = make_jotd_dir(tmp_path)
    ts = "2026-07-07T09:00:00-07:00"
    pulselog.append_event(
        jotd_dir, "response", ts, loop_id="cap-20260703-090000-bbbbbbbb", action="drop"
    )
    pulselog.append_event(
        jotd_dir, "response", ts, loop_id="cap-20260703-090000-bbbbbbbb", action="drop"
    )
    pulselog.append_event(
        jotd_dir,
        "response",
        ts,
        loop_id="cap-20260705-090000-cccccccc",
        action="snooze",
        until="2026-07-12",
    )
    from jotd.derive import derive

    derive(jotd_dir, today=TODAY)
    packet = build_packet(jotd_dir, load_config(jotd_dir), "midday", TODAY)
    ids = {lp["id"] for lp in packet["eligible_loops"]}
    assert "cap-20260703-090000-bbbbbbbb" not in ids  # silenced
    assert "cap-20260705-090000-cccccccc" not in ids  # snoozed
    assert "cap-20260701-090000-aaaaaaaa" in ids


def test_validate_output_rejects_bad_shapes():
    assert validate_output([]) == ["output is not an object"]
    assert validate_output({"nudges": {}, "suppressed": []}) == ["nudges is not a list"]
    ok = {"nudges": [{"loop_id": "a", "text": "b", "reason": "c"}], "suppressed": [], "brief": None}
    assert validate_output(ok) == []
