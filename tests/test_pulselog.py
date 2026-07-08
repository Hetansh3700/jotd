from datetime import date

import pytest

from vault import pulselog

TS = "2026-07-08T09:00:00-07:00"


def test_every_kind_roundtrips(tmp_path):
    pulselog.append_event(tmp_path, "nudge", TS, loop_id="cap-1", text="send it", reason="4d stale")
    pulselog.append_event(tmp_path, "suppress", TS, loop_id="cap-2", reason="too fresh")
    pulselog.append_event(tmp_path, "response", TS, loop_id="cap-1", action="done")
    pulselog.append_event(
        tmp_path, "response", TS, loop_id="cap-2", action="snooze", until="2026-07-11"
    )
    pulselog.append_event(
        tmp_path, "heartbeat", TS, slot="morning", status="ok", nudges=1, suppressed=1
    )
    pulselog.append_event(
        tmp_path, "heartbeat", TS, slot="evening", status="error", err='schema "mismatch"'
    )
    events = pulselog.read_events(tmp_path)
    assert [e["kind"] for e in events] == [
        "nudge",
        "suppress",
        "response",
        "response",
        "heartbeat",
        "heartbeat",
    ]
    assert events[0]["text"] == "send it"
    assert events[3]["until"] == "2026-07-11"
    assert events[5]["err"] == "schema 'mismatch'"  # quotes sanitized, not lost
    # human-readable header present exactly once
    text = pulselog.log_path(tmp_path).read_text()
    assert text.count("# pulse log") == 1


def test_freetext_never_breaks_the_grammar(tmp_path):
    nasty = 'multi\nline "quoted" reason="fake"'
    pulselog.append_event(tmp_path, "nudge", TS, loop_id="cap-1", text=nasty, reason=nasty)
    (event,) = pulselog.read_events(tmp_path)
    assert "\n" not in event["text"] and '"' not in event["text"]


def test_unroundtrippable_event_refused(tmp_path):
    with pytest.raises(ValueError, match="round-trip"):
        pulselog.append_event(tmp_path, "nudge", TS, loop_id="has space", text="x", reason="y")
    assert not pulselog.log_path(tmp_path).exists()


def test_fold_two_drops_silences(tmp_path):
    for _ in range(2):
        pulselog.append_event(tmp_path, "response", TS, loop_id="cap-9", action="drop")
    state = pulselog.fold(pulselog.read_events(tmp_path))
    assert state["cap-9"]["drops"] == 2
    assert state["cap-9"]["silenced"] is True


def test_fold_done_snooze_and_nudge_counts(tmp_path):
    pulselog.append_event(tmp_path, "nudge", TS, loop_id="a", text="t", reason="r")
    pulselog.append_event(
        tmp_path, "nudge", "2026-07-09T09:00:00-07:00", loop_id="a", text="t", reason="r"
    )
    pulselog.append_event(tmp_path, "response", TS, loop_id="a", action="done")
    pulselog.append_event(
        tmp_path, "response", TS, loop_id="b", action="snooze", until="2026-07-11"
    )
    state = pulselog.fold(pulselog.read_events(tmp_path))
    assert state["a"]["nudges"] == 2 and state["a"]["done"] is True
    assert pulselog.is_snoozed(state["b"], date(2026, 7, 10)) is True
    assert pulselog.is_snoozed(state["b"], date(2026, 7, 11)) is False  # until day = eligible


def test_nudges_on_day_counts_only_that_day(tmp_path):
    pulselog.append_event(tmp_path, "nudge", TS, loop_id="a", text="t", reason="r")
    pulselog.append_event(
        tmp_path, "nudge", "2026-07-09T13:30:00-07:00", loop_id="b", text="t", reason="r"
    )
    events = pulselog.read_events(tmp_path)
    assert pulselog.nudges_on_day(events, date(2026, 7, 8)) == 1
    assert pulselog.nudges_on_day(events, date(2026, 7, 9)) == 1
    assert pulselog.nudges_on_day(events, date(2026, 7, 7)) == 0
