import json
from datetime import date
from pathlib import Path

from vault import pulselog
from vault.derive import derive

TODAY = date(2026, 7, 8)


def make_vault(tmp_path: Path) -> Path:
    (tmp_path / "vault.toml").write_text("")
    (tmp_path / "state").mkdir()
    people = tmp_path / "notes" / "people"
    people.mkdir(parents=True)
    (people / "sarah-chen.md").write_text(
        "---\n"
        "type: person\n"
        "title: Sarah Chen\n"
        "aliases: [Sarah, schen]\n"
        "created: 2026-06-02\n"
        "---\n"
        "PM on [[atlas]].\n\n"
        "## Log\n"
        "- 2026-07-03: owes me the security sign-off (cap-20260703-090000-aaaa)\n\n"
        "## Open loops\n"
        "- [ ] chase the security sign-off owner: sarah"
        " <!-- loop:cap-20260703-090000-aaaa -->\n"
        "- [x] send the intro deck <!-- loop:cap-20260620-090000-eeee -->\n"
        "- [ ] hand-written todo with no stamp yet\n"
    )
    projects = tmp_path / "notes" / "projects"
    projects.mkdir(parents=True)
    (projects / "atlas.md").write_text(
        "---\n"
        "type: project\n"
        "title: Atlas\n"
        "aliases: [atlas-api]\n"
        "created: 2026-06-01\n"
        "---\n"
        "Backend platform, PM [[sarah-chen]].\n\n"
        "## Log\n"
        "- 2026-07-05: pooling fix (cap-20260705-090000-bbbb)\n\n"
        "## Open loops\n"
        "- [ ] write the outage postmortem <!-- loop:cap-20260701-090000-cccc -->\n"
        "- [ ] renew pagerduty <!-- loop:cap-20260706-090000-dddd -->\n"
    )
    (tmp_path / "state" / "processed.log").write_text(
        "cap-20260703-090000-aaaa notes/people/sarah-chen.md 2026-07-03T09:05:00-07:00\n"
        "cap-20260701-090000-cccc notes/projects/atlas.md 2026-07-01T09:05:00-07:00\n"
        "cap-20260705-090000-bbbb notes/projects/atlas.md 2026-07-05T09:05:00-07:00\n"
        "cap-20260706-090000-dddd notes/projects/atlas.md 2026-07-06T09:05:00-07:00\n"
    )
    return tmp_path


def test_derive_is_idempotent(tmp_path):
    vault = make_vault(tmp_path)
    first = derive(vault, today=TODAY)
    assert first["stamped"] == 1
    snapshot = {p: p.read_bytes() for p in vault.rglob("*") if p.is_file()}
    second = derive(vault, today=TODAY)
    assert second["stamped"] == 0
    assert {p: p.read_bytes() for p in vault.rglob("*") if p.is_file()} == snapshot


def test_statuses_and_staleness(tmp_path):
    vault = make_vault(tmp_path)
    # two drops on the postmortem loop -> silenced forever
    ts = "2026-07-06T09:00:00-07:00"
    pulselog.append_event(vault, "response", ts, loop_id="cap-20260701-090000-cccc", action="drop")
    pulselog.append_event(vault, "response", ts, loop_id="cap-20260701-090000-cccc", action="drop")
    # pagerduty loop snoozed into the future
    pulselog.append_event(
        vault,
        "response",
        ts,
        loop_id="cap-20260706-090000-dddd",
        action="snooze",
        until="2026-07-11",
    )
    derive(vault, today=TODAY)
    loops = {
        lp["id"]: lp
        for lp in json.loads((vault / "state" / "open-loops.json").read_text())["loops"]
    }
    assert loops["cap-20260620-090000-eeee"]["status"] == "done"
    assert loops["cap-20260701-090000-cccc"]["status"] == "silenced"
    assert loops["cap-20260706-090000-dddd"]["status"] == "snoozed"

    sarah = loops["cap-20260703-090000-aaaa"]
    assert sarah["status"] == "open"
    assert sarah["age_days"] == 5
    assert sarah["stale"] is True  # 5d old, no note activity since
    assert sarah["owner"] == "sarah"

    md = (vault / "state" / "open-loops.md").read_text()
    assert "chase the security sign-off" in md
    assert "Silenced" in md and "postmortem" in md


def test_later_activity_defeats_staleness(tmp_path):
    vault = make_vault(tmp_path)
    log = vault / "state" / "processed.log"
    log.write_text(
        log.read_text()
        + "cap-20260707-100000-ffff notes/people/sarah-chen.md 2026-07-07T10:00:00-07:00\n"
    )
    derive(vault, today=TODAY)
    loops = {
        lp["id"]: lp
        for lp in json.loads((vault / "state" / "open-loops.json").read_text())["loops"]
    }
    assert loops["cap-20260703-090000-aaaa"]["stale"] is False


def test_hand_loop_first_seen_survives_rederive(tmp_path):
    vault = make_vault(tmp_path)
    derive(vault, today=TODAY)
    loops = json.loads((vault / "state" / "open-loops.json").read_text())["loops"]
    hand = next(lp for lp in loops if lp["id"].startswith("l-"))
    assert hand["first_seen"] == TODAY.isoformat()

    later = date(2026, 7, 12)
    derive(vault, today=later)
    loops = json.loads((vault / "state" / "open-loops.json").read_text())["loops"]
    hand2 = next(lp for lp in loops if lp["id"] == hand["id"])
    assert hand2["first_seen"] == TODAY.isoformat()
    assert hand2["age_days"] == 4
    assert hand2["stale"] is True  # aged into staleness across runs


def test_entities_index(tmp_path):
    vault = make_vault(tmp_path)
    derive(vault, today=TODAY)
    entities = json.loads((vault / "state" / "entities.json").read_text())["entities"]
    assert entities["sarah-chen"]["aliases"] == ["Sarah", "schen"]
    assert entities["sarah-chen"]["mentions"] == 1  # [[sarah-chen]] in atlas.md
    assert entities["atlas"]["last_seen"] == "2026-07-06"
    assert entities["atlas"]["type"] == "project"
