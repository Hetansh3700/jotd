import json

from typer.testing import CliRunner

from jotd import init as vinit
from jotd.cli import app

runner = CliRunner()


def make_jotd_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(vinit, "POINTER_FILE", tmp_path / "pointer")
    target = tmp_path / "v"
    result = runner.invoke(app, ["init", str(target), "--no-git"])
    assert result.exit_code == 0, result.output
    return target


def test_init_add_unprocessed_mark_roundtrip(tmp_path, monkeypatch):
    target = make_jotd_dir(tmp_path, monkeypatch)

    result = runner.invoke(app, ["add", "call sarah about atlas", "--dir", str(target)])
    assert result.exit_code == 0, result.output
    cap_id = result.output.strip()
    assert cap_id.startswith("cap-")

    result = runner.invoke(app, ["unprocessed", "--json", "--dir", str(target)])
    records = json.loads(result.output)
    assert [r["id"] for r in records] == [cap_id]

    result = runner.invoke(
        app, ["mark-processed", cap_id, "notes/topics/unsorted.md", "--dir", str(target)]
    )
    assert result.exit_code == 0, result.output

    result = runner.invoke(app, ["unprocessed", "--dir", str(target)])
    assert "inbox clear" in result.output


def test_capture_context_roundtrip(tmp_path, monkeypatch):
    target = make_jotd_dir(tmp_path, monkeypatch)
    result = runner.invoke(
        app,
        [
            "capture",
            "-",
            "--app",
            "Preview",
            "--title",
            "atlas-plan.pdf — Page 3",
            "--method",
            "region",
            "--dir",
            str(target),
        ],
        input="Scaling the write path is the biggest Q3 risk.\n",
    )
    assert result.exit_code == 0, result.output
    records = json.loads(runner.invoke(app, ["unprocessed", "--json", "--dir", str(target)]).output)
    (record,) = records
    assert record["source"] == "screen"
    assert record["context"] == {
        "app": "Preview",
        "title": "atlas-plan.pdf — Page 3",
        "method": "region",
    }
    assert record["text"] == "Scaling the write path is the biggest Q3 risk."


def test_capture_without_flags_has_no_context(tmp_path, monkeypatch):
    target = make_jotd_dir(tmp_path, monkeypatch)
    result = runner.invoke(app, ["capture", "hello", "--dir", str(target)])
    assert result.exit_code == 0, result.output
    (record,) = json.loads(
        runner.invoke(app, ["unprocessed", "--json", "--dir", str(target)]).output
    )
    assert record["source"] == "screen"
    assert "context" not in record


def test_add_refuses_outside_a_jotd_dir(tmp_path):
    result = runner.invoke(app, ["add", "hello", "--dir", str(tmp_path / "nowhere")])
    assert result.exit_code == 2
    assert "not a jotd directory" in result.output


def test_mark_processed_errors_are_friendly(tmp_path, monkeypatch):
    target = make_jotd_dir(tmp_path, monkeypatch)
    result = runner.invoke(
        app, ["mark-processed", "cap-20990101-000000-dead", "notes/x.md", "--dir", str(target)]
    )
    assert result.exit_code == 1
    assert "unknown capture id" in result.output
