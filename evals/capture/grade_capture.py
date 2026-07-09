"""Deterministic grader for capture quality. No LLM, no screen access.

A scene passes iff every `must` phrase survives into the captured text and no
`forbid` phrase does. Phrases are compared after normalization (NFKC →
lowercase → every non-alphanumeric run collapsed to one space) so line breaks,
punctuation, and OCR hyphen-joins don't cause false failures, while real
character misreads still do — those are quality failures we want counted.

Special case: a `forbid` phrase that normalizes to nothing (pure symbols, e.g.
"••••" — the redaction check) is matched against the RAW text instead.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

_NON_ALNUM = re.compile(r"[^a-z0-9]+")

# scenes passed / scenes must reach this for the capture client to gate through
GATE = 0.85


def normalize(s: str) -> str:
    s = unicodedata.normalize("NFKC", s).lower()
    return _NON_ALNUM.sub(" ", s).strip()


def grade_scene(scene: dict[str, Any], captured: dict[str, Any] | None) -> dict[str, Any]:
    """captured is the client's JSON output ({text, app, title, method}) or None on error."""
    result: dict[str, Any] = {
        "id": scene["id"],
        "method": (captured or {}).get("method"),
        "app": (captured or {}).get("app"),
        "missing": [],
        "leaked": [],
    }
    if captured is None or not isinstance(captured.get("text"), str):
        result.update(passed=False, reason="capture-error")
        return result

    raw = captured["text"]
    norm = normalize(raw)
    for phrase in scene.get("must", []):
        if normalize(phrase) not in norm:
            result["missing"].append(phrase)
    for phrase in scene.get("forbid", []):
        norm_phrase = normalize(phrase)
        hit = norm_phrase in norm if norm_phrase else phrase in raw
        if hit:
            result["leaked"].append(phrase)

    result["passed"] = not result["missing"] and not result["leaked"]
    result["reason"] = "ok" if result["passed"] else "content"
    return result


def grade_all(
    scenes: list[dict[str, Any]], captures: dict[str, dict[str, Any] | None]
) -> dict[str, Any]:
    results = [grade_scene(s, captures.get(s["id"])) for s in scenes]
    passed = sum(r["passed"] for r in results)
    return {
        "scenes": len(results),
        "passed": passed,
        "score": round(passed / len(results), 4) if results else 0.0,
        "gate": GATE,
        "overall": bool(results) and passed / len(results) >= GATE,
        "results": results,
    }
