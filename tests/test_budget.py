from datetime import date

from vault import pulselog
from vault.budget import eligible_loops, enforce, remaining_budget
from vault.config import PulseConfig

TODAY = date(2026, 7, 8)
CFG = PulseConfig()


def _nudge_events(n, day="2026-07-08"):
    return [
        {"kind": "nudge", "ts": f"{day}T09:00:0{i % 10}-07:00", "loop_id": f"cap-{i}"}
        for i in range(n)
    ]


def test_budget_fresh_day():
    assert remaining_budget(CFG, [], TODAY) == 3


def test_budget_daily_cap_spans_slots():
    assert remaining_budget(CFG, _nudge_events(4), TODAY) == 2
    assert remaining_budget(CFG, _nudge_events(6), TODAY) == 0
    assert remaining_budget(CFG, _nudge_events(9), TODAY) == 0  # never negative


def test_budget_yesterday_does_not_count():
    assert remaining_budget(CFG, _nudge_events(6, day="2026-07-07"), TODAY) == 3


def test_eligible_only_open():
    loops = [
        {"id": "a", "status": "open"},
        {"id": "b", "status": "snoozed"},
        {"id": "c", "status": "silenced"},
        {"id": "d", "status": "done"},
    ]
    assert [lp["id"] for lp in eligible_loops(loops)] == ["a"]


def test_enforce_truncates_and_explains():
    nudges = [{"loop_id": f"cap-{i}", "text": "t", "reason": "r"} for i in range(5)]
    kept, rejected = enforce(nudges, {f"cap-{i}" for i in range(5)}, budget=3)
    assert len(kept) == 3
    assert [r["reason"] for r in rejected] == ["runner: over budget"] * 2


def test_enforce_rejects_hallucinated_and_duplicate_ids():
    nudges = [
        {"loop_id": "cap-real", "text": "t", "reason": "r"},
        {"loop_id": "cap-invented", "text": "t", "reason": "r"},
        {"loop_id": "cap-real", "text": "again", "reason": "r"},
    ]
    kept, rejected = enforce(nudges, {"cap-real"}, budget=3)
    assert [n["loop_id"] for n in kept] == ["cap-real"]
    reasons = {r["reason"] for r in rejected}
    assert reasons == {
        "runner: unknown or ineligible loop id",
        "runner: duplicate nudge for one loop",
    }


def test_silenced_loops_never_reach_the_packet(tmp_path):
    """Structural guarantee: after two drops, derive marks the loop silenced and
    eligible_loops excludes it — the model cannot renudge what it cannot see."""
    ts = "2026-07-08T09:00:00-07:00"
    pulselog.append_event(tmp_path, "response", ts, loop_id="cap-x", action="drop")
    pulselog.append_event(tmp_path, "response", ts, loop_id="cap-x", action="drop")
    folded = pulselog.fold(pulselog.read_events(tmp_path))
    assert folded["cap-x"]["silenced"] is True
