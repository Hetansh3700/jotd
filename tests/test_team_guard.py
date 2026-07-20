"""The single-librarian guard (D12): with [team] set, state writers refuse on
non-librarian machines; `done` degrades to a checkbox flip; solo mode and the
capture/sync/read commands are never guarded."""

import json

from typer.testing import CliRunner

from jotd import init as vinit
from jotd.cli import app
from jotd.config import load_team

runner = CliRunner()


def make_team_dir(tmp_path, monkeypatch, librarian="ana"):
    monkeypatch.setattr(vinit, "POINTER_FILE", tmp_path / "pointer")
    target = tmp_path / "v"
    result = runner.invoke(app, ["init", str(target), "--no-git"])
    assert result.exit_code == 0, result.output
    if librarian:
        with (target / "jotd.toml").open("a") as f:
            f.write(f'\n[team]\nlibrarian = "{librarian}"\n')
    return target


def as_author(monkeypatch, slug):
    monkeypatch.setenv("JOTD_AUTHOR", slug)


def test_load_team_parsing(tmp_path, monkeypatch):
    d = make_team_dir(tmp_path, monkeypatch, librarian="ana")
    assert load_team(d).librarian == "ana"
    solo = make_team_dir(tmp_path / "solo", monkeypatch, librarian=None)
    assert load_team(solo).librarian is None
    assert load_team(tmp_path / "nowhere").librarian is None


def test_state_writers_refuse_on_non_librarian_machine(tmp_path, monkeypatch):
    d = make_team_dir(tmp_path, monkeypatch)
    as_author(monkeypatch, "ben")
    for cmd in (
        ["mark-processed", "cap-20990101-000000-dead", "notes/x.md"],
        ["derive"],
        ["pulse", "--dry-run"],
        ["snooze", "whatever"],
        ["drop", "whatever"],
    ):
        result = runner.invoke(app, [*cmd, "--dir", str(d)])
        assert result.exit_code == 2, (cmd, result.output)
        assert "librarian" in result.output, cmd
    assert not (d / "state" / "open-loops.json").exists()
    assert not (d / "state" / "pulse-log.md").exists()


def test_schedule_install_split_gate(tmp_path, monkeypatch):
    """D13: pulse installs only where it can run; the sync job installs anywhere
    [sync] auto is on. Nothing installable on a non-librarian machine exits 2."""
    from jotd import sched

    pulse_calls, sync_calls = [], []
    monkeypatch.setattr(sched, "install", lambda d: pulse_calls.append(d) or ["pulse scheduled"])
    monkeypatch.setattr(
        sched, "install_sync", lambda d, m: sync_calls.append((d, m)) or ["auto-sync scheduled"]
    )

    d = make_team_dir(tmp_path, monkeypatch, librarian="ana")

    # non-librarian, auto off -> nothing installable, old guard behavior
    as_author(monkeypatch, "ben")
    result = runner.invoke(app, ["schedule", "install", "--dir", str(d)])
    assert result.exit_code == 2
    assert "librarian" in result.output
    assert pulse_calls == [] and sync_calls == []

    # non-librarian, auto on -> sync only, exit 0 (the template already has [sync])
    toml = (d / "jotd.toml").read_text()
    (d / "jotd.toml").write_text(
        toml.replace("auto = false", "auto = true").replace(
            "interval_minutes = 15", "interval_minutes = 20"
        )
    )
    result = runner.invoke(app, ["schedule", "install", "--dir", str(d)])
    assert result.exit_code == 0, result.output
    assert "pulse schedule skipped" in result.output
    assert pulse_calls == [] and sync_calls == [(d, 20)]

    # librarian -> both
    as_author(monkeypatch, "ana")
    result = runner.invoke(app, ["schedule", "install", "--dir", str(d)])
    assert result.exit_code == 0, result.output
    assert pulse_calls == [d] and sync_calls == [(d, 20), (d, 20)]


def test_librarian_machine_passes_the_gate(tmp_path, monkeypatch):
    d = make_team_dir(tmp_path, monkeypatch)
    as_author(monkeypatch, "ana")
    assert runner.invoke(app, ["derive", "--dir", str(d)]).exit_code == 0
    # gate passed → the NEXT validation layer speaks (exit 1, not the gate's 2)
    result = runner.invoke(
        app, ["mark-processed", "cap-20990101-000000-dead", "notes/x.md", "--dir", str(d)]
    )
    assert result.exit_code == 1 and "unknown capture id" in result.output


def test_solo_mode_is_unrestricted(tmp_path, monkeypatch):
    d = make_team_dir(tmp_path, monkeypatch, librarian=None)
    as_author(monkeypatch, "anyone")
    assert runner.invoke(app, ["derive", "--dir", str(d)]).exit_code == 0


def test_capture_and_read_commands_never_guarded(tmp_path, monkeypatch):
    d = make_team_dir(tmp_path, monkeypatch)
    as_author(monkeypatch, "ben")
    assert runner.invoke(app, ["add", "a thought", "--dir", str(d)]).exit_code == 0
    assert runner.invoke(app, ["capture", "seen", "--dir", str(d)]).exit_code == 0
    assert runner.invoke(app, ["unprocessed", "--dir", str(d)]).exit_code == 0
    assert runner.invoke(app, ["whoami"]).exit_code == 0


def test_non_librarian_done_flips_checkbox_without_touching_state(tmp_path, monkeypatch):
    d = make_team_dir(tmp_path, monkeypatch)
    note = d / "notes" / "topics" / "unsorted.md"
    note.write_text(note.read_text() + "\n- [ ] call sam about the deck\n")

    as_author(monkeypatch, "ana")  # librarian derives: stamps the loop, writes state
    assert runner.invoke(app, ["derive", "--dir", str(d)]).exit_code == 0
    loops = json.loads((d / "state" / "open-loops.json").read_text())["loops"]
    (loop,) = [lp for lp in loops if "call sam" in lp["text"]]
    assert loop["status"] == "open"

    as_author(monkeypatch, "ben")
    result = runner.invoke(app, ["done", loop["id"], "--dir", str(d)])
    assert result.exit_code == 0, result.output
    assert "checkbox flipped" in result.output
    assert "- [x] call sam" in note.read_text()
    assert not (d / "state" / "pulse-log.md").exists()  # no second pulse-log writer (D6)

    as_author(monkeypatch, "ana")  # librarian's next derive folds the flip into status
    assert runner.invoke(app, ["derive", "--dir", str(d)]).exit_code == 0
    loops = json.loads((d / "state" / "open-loops.json").read_text())["loops"]
    (loop,) = [lp for lp in loops if "call sam" in lp["text"]]
    assert loop["status"] == "done"
