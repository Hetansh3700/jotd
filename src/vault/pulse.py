"""`vault pulse` — the scheduled run that decides what deserves attention.

Control flow is deterministic code; ONLY the judgment call ("of these eligible
loops, which would the user act on today, and why / why not?") goes to the
model. The model cannot exceed the budget, cannot resurrect silenced loops
(they never enter its packet), and cannot act — its tool allowlist is
Read/Grep/Glob and its output is parsed JSON, so the trust rule ("never sends
anything to another human") is the absence of capability, not a promise.

Every run appends a heartbeat, even when it fails or skips — silent death is
itself a failure mode the log must show.
"""

from __future__ import annotations

import fcntl
import json
import shutil
import subprocess
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from vault import budget as budget_mod
from vault import notify, pulselog
from vault.config import PulseConfig, load_config
from vault.derive import derive

SLOTS = ("morning", "midday", "evening", "manual")
CLAUDE_TIMEOUT_S = 300
RECENT_EVENTS_IN_PACKET = 20

PACKET_TASK = (
    "You are this vault's pulse. Read the packet below; you may Read/Grep notes in the "
    "current directory for extra context on any candidate loop. Then reply with ONLY a JSON "
    'object, no prose, no code fences: {"nudges": [{"loop_id": str, "text": str, '
    '"reason": str}], "suppressed": [{"loop_id": str, "reason": str}], "brief": str|null}'
    "\n\nPACKET:\n"
)


def _short(loop_id: str) -> str:
    return loop_id.rsplit("-", 1)[-1] if loop_id.startswith("cap-") else loop_id


def _agent_body(data_dir: Path) -> str:
    path = data_dir / ".claude" / "agents" / "pulse.md"
    text = path.read_text(encoding="utf-8")
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end >= 0:
            return text[end + 5 :].strip()
    return text.strip()


def _loops(data_dir: Path) -> list[dict[str, Any]]:
    path = data_dir / "state" / "open-loops.json"
    if not path.is_file():
        return []
    return json.loads(path.read_text(encoding="utf-8")).get("loops", [])


def _yesterday_summary(data_dir: Path, today: date) -> dict[str, Any]:
    yesterday = (today - timedelta(days=1)).isoformat()
    captured = 0
    for f in (data_dir / "inbox").glob("*.jsonl"):
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.strip() and json.loads(line).get("ts", "").startswith(yesterday):
                captured += 1
    organized: set[str] = set()
    log = data_dir / "state" / "processed.log"
    if log.is_file():
        for line in log.read_text(encoding="utf-8").splitlines():
            parts = line.split()
            if len(parts) == 3 and parts[2].startswith(yesterday):
                organized.update(parts[1].split(","))
    return {"captures": captured, "organized_into": sorted(organized)}


def build_packet(data_dir: Path, cfg: PulseConfig, slot: str, today: date) -> dict[str, Any]:
    events = pulselog.read_events(data_dir)
    eligible = budget_mod.eligible_loops(_loops(data_dir))
    folded = pulselog.fold(events)
    aging_suppressed = [
        {
            "loop_id": lp["id"],
            "text": lp["text"],
            "times_suppressed": folded[lp["id"]]["suppressed"],
            "age_days": lp["age_days"],
        }
        for lp in eligible
        if folded.get(lp["id"], {}).get("suppressed", 0) >= 2
    ]
    keep = (
        "id",
        "text",
        "note",
        "owner",
        "age_days",
        "stale",
        "first_seen",
        "nudges",
        "last_nudged",
    )
    return {
        "slot": slot,
        "date": today.isoformat(),
        "nudge_budget": budget_mod.remaining_budget(cfg, events, today),
        "stale_after_days": cfg.stale_after_days,
        "eligible_loops": [{k: lp[k] for k in keep} for lp in eligible],
        "recent_pulse_events": [e for e in events[-RECENT_EVENTS_IN_PACKET:]],
        "yesterday": _yesterday_summary(data_dir, today),
        "aging_suppressed": aging_suppressed,
        "calendar": "not connected in v0.2 — say so in the brief, do not invent meetings",
    }


def _extract_json(text: str) -> dict[str, Any]:
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("no JSON object in model output")
    return json.loads(text[start : end + 1])


def validate_output(obj: Any) -> list[str]:
    errors = []
    if not isinstance(obj, dict):
        return ["output is not an object"]
    for key, fields in (
        ("nudges", ("loop_id", "text", "reason")),
        ("suppressed", ("loop_id", "reason")),
    ):
        items = obj.get(key)
        if not isinstance(items, list):
            errors.append(f"{key} is not a list")
            continue
        for i, item in enumerate(items):
            if not isinstance(item, dict) or not all(
                isinstance(item.get(f), str) and item.get(f) for f in fields
            ):
                errors.append(f"{key}[{i}] missing/invalid fields {fields}")
    brief = obj.get("brief")
    if brief is not None and not isinstance(brief, str):
        errors.append("brief is neither string nor null")
    return errors


def _invoke_claude(data_dir: Path, cfg: PulseConfig, prompt: str, agent_body: str) -> str:
    claude = shutil.which("claude")
    if not claude:
        raise RuntimeError("claude CLI not on PATH")
    cmd = [
        claude,
        "-p",
        prompt,
        "--model",
        cfg.model,
        "--append-system-prompt",
        agent_body,
        "--allowedTools",
        "Read",
        "Grep",
        "Glob",
        "--disallowedTools",
        "Bash",
        "Edit",
        "Write",
        "WebSearch",
        "WebFetch",
        "--output-format",
        "json",
        "--max-turns",
        "15",
    ]
    proc = subprocess.run(
        cmd, cwd=data_dir, capture_output=True, text=True, timeout=CLAUDE_TIMEOUT_S
    )
    if proc.returncode != 0:
        raise RuntimeError(f"claude exited {proc.returncode}: {proc.stderr[-400:]}")
    envelope = json.loads(proc.stdout)
    if envelope.get("is_error"):
        raise RuntimeError(f"claude reported error: {str(envelope.get('result'))[:400]}")
    return envelope.get("result", "")


def _write_brief(data_dir: Path, today: date, brief_md: str, packet: dict[str, Any]) -> Path:
    path = data_dir / "state" / "briefs" / f"{today.isoformat()}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"# Daily brief — {today.isoformat()}\n\n{brief_md.strip()}\n", encoding="utf-8"
    )
    return path


def _fallback_brief(packet: dict[str, Any]) -> str:
    loops = sorted(packet["eligible_loops"], key=lambda lp: -lp["age_days"])[:3]
    lines = ["(model brief unavailable — deterministic fallback)", "", "## Top open loops"]
    lines += [f"- {lp['text']} ({lp['age_days']}d)" for lp in loops] or ["- none"]
    y = packet["yesterday"]
    lines += [
        "",
        f"Yesterday: {y['captures']} captures, organized into {len(y['organized_into'])} notes.",
    ]
    return "\n".join(lines)


def run_pulse(
    data_dir: Path,
    slot: str = "manual",
    *,
    dry_run: bool = False,
    today: date | None = None,
) -> dict[str, Any]:
    if slot not in SLOTS:
        raise ValueError(f"slot must be one of {SLOTS}")
    cfg = load_config(data_dir)
    today = today or date.today()
    started = time.monotonic()

    def ts() -> str:
        return datetime.now().astimezone().isoformat(timespec="seconds")

    def heartbeat(status: str, nudges: int = 0, suppressed: int = 0, err: str = "") -> None:
        if not dry_run:
            pulselog.append_event(
                data_dir,
                "heartbeat",
                ts(),
                slot=slot,
                status=status,
                nudges=nudges,
                suppressed=suppressed,
                **({"err": err} if err else {}),
            )

    lock_path = data_dir / "state" / ".pulse.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_fd = open(lock_path, "w")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        heartbeat("skipped", err="another pulse run holds the lock")
        return {"status": "skipped"}

    try:
        derive(data_dir, today=today)
        packet = build_packet(data_dir, cfg, slot, today)
        eligible_ids = {lp["id"] for lp in packet["eligible_loops"]}
        is_morning = slot == "morning"

        if not eligible_ids and not is_morning:
            heartbeat("ok")
            return {"status": "ok", "nudges": [], "suppressed": [], "skipped_llm": True}

        try:
            raw = _invoke_claude(
                data_dir,
                cfg,
                PACKET_TASK + json.dumps(packet, ensure_ascii=False, indent=1),
                _agent_body(data_dir),
            )
            output = _extract_json(raw)
            errors = validate_output(output)
            if errors:
                raise ValueError("model output failed schema: " + "; ".join(errors))
        except Exception as e:  # noqa: BLE001 — any failure means: send NOTHING, log it
            heartbeat("error", err=str(e))
            return {"status": "error", "error": str(e)}

        kept, runner_rejected = budget_mod.enforce(
            output["nudges"], eligible_ids, packet["nudge_budget"]
        )
        model_suppressed = [s for s in output["suppressed"] if s["loop_id"] in eligible_ids]

        actions: list[str] = []
        if is_morning:
            brief_md = output.get("brief") or _fallback_brief(packet)
            if dry_run:
                actions.append(f"would write brief ({len(brief_md)} chars) and notify")
            else:
                path = _write_brief(data_dir, today, brief_md, packet)
                notify.send(
                    "vault — daily brief",
                    f"Brief ready: vault log --brief ({path.name})",
                    cfg.channel,
                )
                actions.append(f"brief -> {path}")

        for n in kept:
            message = f"{n['text']} — vault done|snooze|drop {_short(n['loop_id'])}"
            if dry_run:
                actions.append(f"would nudge: {message}  [reason: {n['reason']}]")
            else:
                notify.send("vault", message, cfg.channel)
                pulselog.append_event(
                    data_dir,
                    "nudge",
                    ts(),
                    loop_id=n["loop_id"],
                    text=n["text"],
                    reason=n["reason"],
                )
        if not dry_run:
            for s in model_suppressed:
                pulselog.append_event(
                    data_dir, "suppress", ts(), loop_id=s["loop_id"], reason=s["reason"]
                )
            for r in runner_rejected:
                pulselog.append_event(
                    data_dir,
                    "suppress",
                    ts(),
                    loop_id=r.get("loop_id", "?"),
                    reason=r["reason"],
                )

        dur = int(time.monotonic() - started)
        heartbeat("ok", nudges=len(kept), suppressed=len(model_suppressed) + len(runner_rejected))
        return {
            "status": "ok",
            "nudges": kept,
            "suppressed": model_suppressed,
            "runner_rejected": runner_rejected,
            "actions": actions,
            "duration_s": dur,
        }
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()
