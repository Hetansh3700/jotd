"""One-shot headless `claude -p` invocations, shared by the pulse and the
session-end scribe.

Callers own everything around the call: prompt assembly, output validation,
and any budget enforcement (D5 — code is the law, the model only drafts).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

DEFAULT_DISALLOWED_TOOLS = ("Bash", "Edit", "Write", "WebSearch", "WebFetch")


def invoke_claude(
    prompt: str,
    *,
    cwd: Path,
    model: str,
    system_prompt: str | None = None,
    allowed_tools: tuple[str, ...] = (),
    disallowed_tools: tuple[str, ...] = DEFAULT_DISALLOWED_TOOLS,
    max_turns: int = 1,
    timeout_s: int = 120,
    extra_env: dict[str, str] | None = None,
) -> str:
    claude = shutil.which("claude")
    if not claude:
        raise RuntimeError("claude CLI not on PATH")
    cmd = [claude, "-p", prompt, "--model", model]
    if system_prompt:
        cmd += ["--append-system-prompt", system_prompt]
    if allowed_tools:
        cmd += ["--allowedTools", *allowed_tools]
    if disallowed_tools:
        cmd += ["--disallowedTools", *disallowed_tools]
    cmd += ["--output-format", "json", "--max-turns", str(max_turns)]
    env = None
    if extra_env:
        env = {**os.environ, **extra_env}
    proc = subprocess.run(
        cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout_s, env=env
    )
    if proc.returncode != 0:
        raise RuntimeError(f"claude exited {proc.returncode}: {proc.stderr[-400:]}")
    envelope = json.loads(proc.stdout)
    if envelope.get("is_error"):
        raise RuntimeError(f"claude reported error: {str(envelope.get('result'))[:400]}")
    return envelope.get("result", "")


def extract_json(text: str) -> dict[str, Any]:
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("no JSON object in model output")
    return json.loads(text[start : end + 1])
