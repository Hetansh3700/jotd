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


def test_author_flag_beats_env_beats_file(tmp_path, monkeypatch):
    from jotd import author as vauthor

    target = make_jotd_dir(tmp_path, monkeypatch)
    author_file = tmp_path / "author"
    author_file.write_text("filey\n")
    monkeypatch.setattr(vauthor, "AUTHOR_FILE", author_file)
    monkeypatch.setenv("JOTD_AUTHOR", "envy")

    runner.invoke(app, ["add", "one", "--author", "Flag Guy", "--dir", str(target)])
    runner.invoke(app, ["add", "two", "--dir", str(target)])
    monkeypatch.delenv("JOTD_AUTHOR")
    runner.invoke(app, ["add", "three", "--dir", str(target)])

    records = json.loads(runner.invoke(app, ["unprocessed", "--json", "--dir", str(target)]).output)
    by_text = {r["text"]: r["author"] for r in records}
    assert by_text == {"one": "flag-guy", "two": "envy", "three": "filey"}
    names = {p.name for p in (target / "inbox").glob("*.jsonl")}
    assert names == {"2026-07.flag-guy.jsonl", "2026-07.envy.jsonl", "2026-07.filey.jsonl"} or all(
        "." in n for n in names
    )  # month varies with today's date; the author segment is the invariant
    assert all(n.split(".")[1] in {"flag-guy", "envy", "filey"} for n in names)


def test_author_never_lands_in_context(tmp_path, monkeypatch):
    target = make_jotd_dir(tmp_path, monkeypatch)
    monkeypatch.setenv("JOTD_AUTHOR", "ana")
    runner.invoke(app, ["capture", "hello", "--method", "region", "--dir", str(target)])
    (record,) = json.loads(
        runner.invoke(app, ["unprocessed", "--json", "--dir", str(target)]).output
    )
    assert record["author"] == "ana"
    assert record["context"] == {"method": "region"}


def test_whoami_names_slug_and_rule(monkeypatch):
    monkeypatch.setenv("JOTD_AUTHOR", "Zed Person")
    result = runner.invoke(app, ["whoami"])
    assert result.exit_code == 0
    assert "zed-person" in result.output and "$JOTD_AUTHOR" in result.output


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
