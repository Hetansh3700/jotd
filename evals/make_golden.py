"""Regenerate evals/golden/ — a synthetic, deterministic /organize run.

The golden vault is what a competent librarian WOULD produce over the fixture
captures, with three planted defects so tests prove the grader catches misses:

  D-a  capture idx 3  ("schen prefers async...") misrouted to topics/unsorted
       instead of people/sarah-chen           -> routing miss
  D-b  capture idx 22 (sarah + helios fanout)  routed only to projects/helios
                                               -> routing miss (partial fanout)
  D-c  capture idx 20 (marcus cost breakdown)  content logged but loop NOT
       stamped                                 -> loop recall miss

Expected metrics: routing 26/28, loop recall 6/7, precision 1.0, integrity ok.

Run from repo root: python evals/make_golden.py   (fully deterministic; no LLM,
no clock — timestamps are fixed literals so the committed output never churns.)
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from vault.formats import dump_capture_line, format_loop_line  # noqa: E402

EVALS = Path(__file__).resolve().parent
GOLDEN = EVALS / "golden"
DAY = "2026-07-07"

NEW_NOTES = {
    "people/dana-ross": ("person", "Dana Ross"),
    "topics/agent-interruption-budget": ("topic", "Agent interruption budget"),
    "topics/unsorted": ("topic", "Unsorted"),
}

# idx -> routed targets override (defects D-a, D-b); None = follow expectations
OVERRIDES: dict[int, list[str]] = {3: ["topics/unsorted"], 22: ["projects/helios"]}
SKIP_LOOP_STAMP = {20}  # defect D-c

GLOB_RESOLUTION = {4: ["people/dana-ross"], 13: ["topics/agent-interruption-budget"]}


def ensure_note(vault: Path, target: str, kind: str, title: str) -> Path:
    path = vault / "notes" / (target + ".md")
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            f"---\ntype: {kind}\ntitle: {title}\naliases: []\ncreated: {DAY}\n---\n"
            f"\n## Log\n\n## Open loops\n",
            encoding="utf-8",
        )
    return path


def append_under(path: Path, section: str, line: str) -> None:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    if section not in lines:
        lines += ["", section]
    idx = lines.index(section)
    end = idx + 1
    while end < len(lines) and not lines[end].startswith("## "):
        end += 1
    while end > idx + 1 and lines[end - 1] == "":
        end -= 1
    lines.insert(end, line)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    fixtures = [
        json.loads(line)
        for line in (EVALS / "fixtures" / "captures.jsonl").read_text().splitlines()
        if line.strip()
    ]

    if GOLDEN.exists():
        shutil.rmtree(GOLDEN)
    vault = GOLDEN / "vault"
    (vault / "inbox").mkdir(parents=True)
    (vault / "state").mkdir(parents=True)
    shutil.copytree(EVALS / "fixtures" / "seed-vault" / "notes", vault / "notes")

    manifest, inbox_lines, processed_lines = [], [], []
    for i, fx in enumerate(fixtures):
        ts = f"{DAY}T09:{i:02d}:00-07:00"
        record = {
            "id": f"cap-20260707-09{i:02d}00-{i:08x}",
            "ts": ts,
            "text": fx["text"],
            "source": "cli",
        }
        manifest.append({"record": record, "expect": fx["expect"]})
        inbox_lines.append(dump_capture_line(record))

        targets = OVERRIDES.get(i) or GLOB_RESOLUTION.get(i) or fx["expect"]["targets"]
        for target in targets:
            kind, title = NEW_NOTES.get(target, (target.split("/")[0].rstrip("s"), target))
            path = ensure_note(vault, target, kind, title)
            append_under(path, "## Log", f"- {DAY}: {fx['text']} ({record['id']})")
        if fx["expect"].get("loop") and i not in SKIP_LOOP_STAMP:
            first = vault / "notes" / (targets[0] + ".md")
            append_under(first, "## Open loops", format_loop_line(fx["text"], record["id"]))
        routed = ",".join("notes/" + t + ".md" for t in targets)
        processed_lines.append(f"{record['id']} {routed} {ts}\n")

    (vault / "inbox" / "2026-07.jsonl").write_text("".join(inbox_lines), encoding="utf-8")
    (vault / "state" / "processed.log").write_text("".join(processed_lines), encoding="utf-8")
    (GOLDEN / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")

    from grade import check_thresholds, grade  # local import: same directory

    metrics = grade(vault, manifest)
    (GOLDEN / "expected.json").write_text(json.dumps(metrics, indent=1), encoding="utf-8")
    print(
        f"golden regenerated: routing {metrics['routing_hits']}/{metrics['n']}, "
        f"loop recall {metrics['loop_recall']}, gates={check_thresholds(metrics)}"
    )


if __name__ == "__main__":
    main()
