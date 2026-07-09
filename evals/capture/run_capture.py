"""Capture-quality harness — human-run against real app scenes.

THE CAPTURE-COMMAND CONTRACT (frozen; Tier A and Tier B must both satisfy it):
the command passed via --cmd is executed once per scene and MUST print exactly
one JSON object to stdout:

    {"text": str, "app": str|null, "title": str|null, "method": str}

Non-zero exit or unparseable stdout fails the scene with reason=capture-error.
`method` is recorded from the output, not declared in the scene — the same
scenes grade Tier A ("region") today and Tier B ("ax"|"window"|"fullscreen")
later, and reports show method drift per scene over time.

Usage:
  python evals/capture/run_capture.py --cmd 'contrib/screen-capture/vault-screen-capture.sh --json'
  ... --only pdf-two-col        # single scene
  ... --no-wait                 # skip the Enter prompts (pre-staged scenes)

Per scene the harness prints the setup instructions, waits for Enter (stage the
scene, position for the grab), runs the command, grades, and writes a report to
evals/capture/results/. Gate: >= 85% of scenes pass.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from grade_capture import GATE, grade_all  # noqa: E402

HERE = Path(__file__).resolve().parent


def load_scenes(only: str | None) -> list[dict]:
    scenes = [
        json.loads(line)
        for line in (HERE / "scenes.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if only:
        scenes = [s for s in scenes if s["id"] == only]
        if not scenes:
            raise SystemExit(f"no scene with id {only!r}")
    return scenes


def run_capture(cmd: str) -> dict | None:
    proc = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=180)
    if proc.returncode != 0:
        print(f"  capture command exited {proc.returncode}: {proc.stderr[-300:]}", file=sys.stderr)
        return None
    try:
        out = json.loads(proc.stdout)
        return out if isinstance(out, dict) else None
    except json.JSONDecodeError:
        print(f"  capture output was not JSON: {proc.stdout[:200]!r}", file=sys.stderr)
        return None


def report(summary: dict, cmd: str) -> Path:
    stamp = datetime.now().strftime("%Y-%m-%d-%H%M")
    out = HERE / "results" / f"capture-{stamp}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# capture-quality eval — {stamp}",
        "",
        f"- command: `{cmd}`",
        f"- scenes: {summary['passed']}/{summary['scenes']} = {summary['score']} (gate ≥ {GATE})",
        f"- overall: {'PASS' if summary['overall'] else 'FAIL'}",
        "",
        "| scene | pass | method | missing | leaked |",
        "|---|---|---|---|---|",
    ]
    for r in summary["results"]:
        lines.append(
            f"| {r['id']} | {'✓' if r['passed'] else '✗ ' + r['reason']} | {r['method'] or '—'}"
            f" | {', '.join(r['missing']) or '—'} | {', '.join(r['leaked']) or '—'} |"
        )
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cmd", required=True, help="capture command printing the contract JSON")
    ap.add_argument("--only", help="run a single scene id")
    ap.add_argument("--no-wait", action="store_true", help="skip Enter prompts (pre-staged)")
    args = ap.parse_args()

    scenes = load_scenes(args.only)
    captures: dict[str, dict | None] = {}
    for scene in scenes:
        print(f"\n=== {scene['id']} ({scene['app']})")
        print(f"    setup: {scene['setup']}")
        if not args.no_wait:
            input("    stage the scene, then press Enter to capture... ")
        captures[scene["id"]] = run_capture(args.cmd)

    summary = grade_all(scenes, captures)
    out = report(summary, args.cmd)
    print(f"\nreport: {out}")
    verdict = "PASS" if summary["overall"] else "FAIL"
    print(f"overall: {verdict} ({summary['passed']}/{summary['scenes']})")
    return 0 if summary["overall"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
