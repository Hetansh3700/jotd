"""Routing eval harness — HUMAN-RUN, never CI (it spends real LLM tokens).

Builds a throwaway vault from the seed fixture, appends the 28 labeled captures,
runs a headless `claude -p "/organize"` against it, and grades the result with
the deterministic grader. CI instead grades the committed golden run
(tests/test_grader.py), so the grader itself can't rot between human runs.

Usage:
  python evals/run_routing.py                 # full run (requires claude login)
  python evals/run_routing.py --keep          # keep the temp vault for autopsy
  python evals/run_routing.py --grade-only evals/golden/vault  # no LLM, re-grade
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from grade import THRESHOLDS, check_thresholds, grade  # noqa: E402

EVALS = Path(__file__).resolve().parent
CLAUDE_ARGS = [
    "--permission-mode",
    "acceptEdits",
    "--output-format",
    "json",
    "--max-turns",
    "250",
]


def build_eval_vault(tmp: Path) -> list[dict]:
    from vault.init import scaffold

    from vault import inbox

    scaffold(tmp, git=False)
    shutil.copytree(EVALS / "fixtures" / "seed-vault" / "notes", tmp / "notes", dirs_exist_ok=True)

    fixtures = [
        json.loads(line)
        for line in (EVALS / "fixtures" / "captures.jsonl").read_text().splitlines()
        if line.strip()
    ]
    manifest = []
    for fx in fixtures:
        record = inbox.append_capture(tmp, fx["text"], source="eval")
        manifest.append({"record": record, "expect": fx["expect"]})
    (tmp / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    return manifest


def run_organize(tmp: Path, model: str) -> dict:
    env = dict(os.environ)
    # the librarian shells out to `vault unprocessed` / `vault mark-processed`;
    # make sure the venv's console script wins on PATH
    env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")
    env["VAULT_DIR"] = str(tmp)
    cmd = ["claude", "-p", "/organize", "--model", model, *CLAUDE_ARGS]
    print(f"$ {' '.join(cmd)}  (cwd={tmp})")
    proc = subprocess.run(cmd, cwd=tmp, env=env, capture_output=True, text=True, timeout=2400)
    if proc.returncode != 0:
        print(proc.stdout[-2000:], file=sys.stderr)
        print(proc.stderr[-2000:], file=sys.stderr)
        raise RuntimeError(f"claude exited {proc.returncode}")
    return json.loads(proc.stdout)


def report(metrics: dict, gates: dict, out_dir: Path, model: str, session: dict | None) -> Path:
    stamp = datetime.now().strftime("%Y-%m-%d-%H%M")
    out = out_dir / f"routing-{stamp}.md"
    misses = [c for c in metrics["per_capture"] if not c["ok"] or c["loop_ok"] is False]
    lines = [
        f"# routing eval — {stamp}",
        "",
        f"- model: {model}",
        f"- routing: {metrics['routing_hits']}/{metrics['n']} = {metrics['routing_accuracy']}"
        f" (gate ≥ {THRESHOLDS['routing_accuracy']})",
        f"- loop recall: {metrics['loops_found']}/{metrics['loops_expected']}"
        f" = {metrics['loop_recall']} (gate ≥ {THRESHOLDS['loop_recall']})",
        f"- loop precision: {metrics['loop_precision']}",
        f"- inbox intact: {metrics['inbox_intact']}  processed complete:"
        f" {metrics['processed_complete']}",
        f"- overall: {'PASS' if gates['overall'] else 'FAIL'}",
    ]
    if session:
        usage = session.get("modelUsage", {})
        cost = sum(m.get("costUSD", 0) for m in usage.values())
        lines.append(f"- turns: {session.get('num_turns')}  cost: ${cost:.2f}")
    if misses:
        lines += ["", "## misses"]
        for c in misses:
            what = "misroute" if not c["ok"] else "missed loop"
            lines.append(f"- {c['id']} [{c['class']}] {what}: “{c['text']}” routed={c['routed']}")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    out.with_suffix(".json").write_text(json.dumps(metrics, indent=1), encoding="utf-8")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="sonnet")
    ap.add_argument("--keep", action="store_true", help="keep the temp vault for autopsy")
    ap.add_argument("--grade-only", metavar="VAULT_DIR", help="grade an existing vault, no LLM")
    args = ap.parse_args()

    if args.grade_only:
        vault_dir = Path(args.grade_only)
        manifest_path = vault_dir / "manifest.json"
        if not manifest_path.exists():
            manifest_path = vault_dir.parent / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        metrics = grade(vault_dir, manifest)
        gates = check_thresholds(metrics)
        print(json.dumps({k: v for k, v in metrics.items() if k != "per_capture"}, indent=2))
        print(f"gates: {gates}")
        return 0 if gates["overall"] else 1

    tmp = Path(tempfile.mkdtemp(prefix="vault-eval-"))
    try:
        manifest = build_eval_vault(tmp)
        session = run_organize(tmp, args.model)
        metrics = grade(tmp, manifest)
        gates = check_thresholds(metrics)
        out = report(metrics, gates, EVALS / "results", args.model, session)
        print(f"\nreport: {out}")
        print(f"overall: {'PASS' if gates['overall'] else 'FAIL'}  {gates}")
        return 0 if gates["overall"] else 1
    finally:
        if args.keep:
            print(f"temp vault kept: {tmp}")
        else:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
