"""The grader is graded: CI runs it over the committed golden run (a synthetic
/organize output with three planted defects) and asserts the exact metrics.
This is what lets the LLM eval stay human-run without the grader rotting."""

import json
import shutil
from pathlib import Path

from grade import check_thresholds, grade

GOLDEN = Path(__file__).resolve().parent.parent / "evals" / "golden"


def load_golden():
    manifest = json.loads((GOLDEN / "manifest.json").read_text())
    expected = json.loads((GOLDEN / "expected.json").read_text())
    return manifest, expected


def test_golden_metrics_exact():
    manifest, expected = load_golden()
    metrics = grade(GOLDEN / "vault", manifest)
    assert metrics == expected


def test_golden_defects_detected():
    manifest, _ = load_golden()
    metrics = grade(GOLDEN / "vault", manifest)
    # three planted defects: two misroutes, one missed loop stamp
    assert metrics["routing_hits"] == metrics["n"] - 2
    assert metrics["loops_found"] == metrics["loops_expected"] - 1
    assert metrics["loop_precision"] == 1.0
    gates = check_thresholds(metrics)
    assert gates["routing_accuracy"] is True  # 26/28 clears 0.85
    assert gates["loop_recall"] is False  # 6/7 misses 0.90 — the gate bites
    assert gates["overall"] is False


def test_inbox_mutation_detected(tmp_path):
    manifest, _ = load_golden()
    work = tmp_path / "vault"
    shutil.copytree(GOLDEN / "vault", work)
    inbox = next((work / "inbox").glob("*.jsonl"))
    inbox.write_text(inbox.read_text() + '{"id":"cap-x","text":"smuggled"}\n')
    assert grade(work, manifest)["inbox_intact"] is False


def test_missing_processed_entry_detected(tmp_path):
    manifest, _ = load_golden()
    work = tmp_path / "vault"
    shutil.copytree(GOLDEN / "vault", work)
    log = work / "state" / "processed.log"
    lines = log.read_text().splitlines()
    log.write_text("\n".join(lines[1:]) + "\n")
    metrics = grade(work, manifest)
    assert metrics["processed_complete"] is False
    assert metrics["routing_hits"] < len(manifest)


def test_glob_never_matches_unsorted(tmp_path):
    """'topics/*' must not be satisfiable by a dump into topics/unsorted."""
    manifest, _ = load_golden()
    work = tmp_path / "vault"
    shutil.copytree(GOLDEN / "vault", work)
    # find the new-topic capture (expected topics/*) and reroute it to unsorted
    entry = next(m for m in manifest if m["expect"].get("class") == "topic-new")
    cap_id = entry["record"]["id"]
    log = work / "state" / "processed.log"
    rerouted = []
    for line in log.read_text().splitlines():
        if line.startswith(cap_id):
            ts = line.rsplit(" ", 1)[1]
            line = f"{cap_id} notes/topics/unsorted.md {ts}"
        rerouted.append(line)
    log.write_text("\n".join(rerouted) + "\n")
    unsorted = work / "notes" / "topics" / "unsorted.md"
    unsorted.write_text(unsorted.read_text() + f"\n- dumped here ({cap_id})\n")
    metrics = grade(work, manifest)
    bad = next(c for c in metrics["per_capture"] if c["id"] == cap_id)
    assert bad["ok"] is False
