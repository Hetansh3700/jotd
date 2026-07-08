"""Deterministic grader for the routing eval. No LLM anywhere in this file.

Grades a vault directory after an /organize run against a manifest of labeled
captures. The grader is itself under test (tests/test_grader.py grades the
committed golden run and asserts exact metrics), so CI keeps it honest even
though CI never runs the LLM.

Target patterns in fixtures are vault paths relative to notes/ without .md
("people/sarah-chen"). A pattern containing "*" is an fnmatch glob with one
carve-out: globs NEVER match topics/unsorted — "route somewhere real in this
category" and "correctly give up" must stay distinguishable classes.

A capture is routed correctly when every expected pattern is satisfied by some
path in its processed.log entry AND that file contains the capture id (the
librarian must both write the content and record where it put it). Extra routed
paths are allowed: over-linking is not an error in v0.2.
"""

from __future__ import annotations

import json
import sys
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from vault.formats import dump_capture_line, parse_loop_line, parse_processed_line  # noqa: E402

THRESHOLDS = {"routing_accuracy": 0.85, "loop_recall": 0.90}


def _norm(path: str) -> str:
    """notes/people/sarah-chen.md -> people/sarah-chen"""
    p = path.removeprefix("notes/")
    return p.removesuffix(".md")


def _pattern_hit(pattern: str, routed: list[str], vault_dir: Path, capture_id: str) -> bool:
    for path in routed:
        norm = _norm(path)
        if "*" in pattern:
            if norm == "topics/unsorted" or not fnmatch(norm, pattern):
                continue
        elif norm != pattern:
            continue
        target = vault_dir / path
        if target.is_file() and capture_id in target.read_text(encoding="utf-8"):
            return True
    return False


def _read_processed(vault_dir: Path) -> dict[str, list[str]]:
    log = vault_dir / "state" / "processed.log"
    entries: dict[str, list[str]] = {}
    if not log.is_file():
        return entries
    for line in log.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        cap_id, paths, _ts = parse_processed_line(line)
        if cap_id in entries:
            entries[cap_id] = entries[cap_id] + ["<duplicate>"]
        else:
            entries[cap_id] = paths
    return entries


def _scan_open_loops(vault_dir: Path) -> dict[str, str]:
    """All stamped OPEN loop ids across notes -> containing file."""
    loops: dict[str, str] = {}
    for md in sorted((vault_dir / "notes").rglob("*.md")):
        for line in md.read_text(encoding="utf-8").splitlines():
            parsed = parse_loop_line(line)
            if parsed and parsed["state"] == "open":
                loops[parsed["id"]] = str(md.relative_to(vault_dir))
    return loops


def _inbox_bytes(vault_dir: Path) -> bytes:
    files = sorted((vault_dir / "inbox").glob("*.jsonl"))
    return b"".join(f.read_bytes() for f in files)


def expected_inbox_bytes(manifest: list[dict[str, Any]]) -> bytes:
    return "".join(dump_capture_line(m["record"]) for m in manifest).encode("utf-8")


def grade(vault_dir: Path, manifest: list[dict[str, Any]]) -> dict[str, Any]:
    processed = _read_processed(vault_dir)
    open_loops = _scan_open_loops(vault_dir)

    per_capture = []
    routing_hits = 0
    loops_expected = 0
    loops_found = 0
    complete = True

    for entry in manifest:
        record, expect = entry["record"], entry["expect"]
        cap_id = record["id"]
        routed = processed.get(cap_id, [])
        if not routed or "<duplicate>" in routed:
            complete = False
        missing = [p for p in expect["targets"] if not _pattern_hit(p, routed, vault_dir, cap_id)]
        ok = not missing and bool(routed)
        routing_hits += ok

        loop_ok: bool | None = None
        if expect.get("loop"):
            loops_expected += 1
            loop_ok = cap_id in open_loops
            loops_found += loop_ok

        per_capture.append(
            {
                "id": cap_id,
                "class": expect.get("class", ""),
                "text": record["text"][:60],
                "ok": ok,
                "routed": routed,
                "missing": missing,
                "loop_ok": loop_ok,
            }
        )

    fixture_ids = {m["record"]["id"] for m in manifest}
    stamped = [i for i in open_loops if i in fixture_ids]
    expected_true_found = loops_found

    n = len(manifest)
    metrics = {
        "n": n,
        "routing_hits": routing_hits,
        "routing_accuracy": round(routing_hits / n, 4) if n else 0.0,
        "loops_expected": loops_expected,
        "loops_found": loops_found,
        "loop_recall": round(loops_found / loops_expected, 4) if loops_expected else 1.0,
        "loops_stamped": len(stamped),
        "loop_precision": round(expected_true_found / len(stamped), 4) if stamped else 1.0,
        "inbox_intact": _inbox_bytes(vault_dir) == expected_inbox_bytes(manifest),
        "processed_complete": complete,
        "per_capture": per_capture,
    }
    return metrics


def check_thresholds(metrics: dict[str, Any]) -> dict[str, bool]:
    results = {name: metrics[name] >= floor for name, floor in THRESHOLDS.items()}
    results["inbox_intact"] = bool(metrics["inbox_intact"])
    results["processed_complete"] = bool(metrics["processed_complete"])
    results["overall"] = all(results.values())
    return results


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: python evals/grade.py <vault_dir> <manifest.json>", file=sys.stderr)
        return 2
    vault_dir = Path(sys.argv[1])
    manifest = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
    metrics = grade(vault_dir, manifest)
    gates = check_thresholds(metrics)
    print(json.dumps({"metrics": metrics, "gates": gates}, indent=2))
    return 0 if gates["overall"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
