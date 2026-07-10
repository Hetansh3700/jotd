"""`jotd derive` — rebuild everything in state/ that is derivable, idempotently.

The load-bearing split of the whole product: the librarian (LLM) decides what a
capture means and where it goes; THIS module (pure code) owns every aggregate —
open loops, ages, staleness, snooze/drop folding, the entity index. Because
loops live in notes as stamped checkbox lines, all of state/ can be rebuilt
from the notes tree + processed.log + pulse-log.md at any time.

The ONLY mutation derive makes outside state/ is stamping hand-written checkbox
lines (`- [ ] thing`) with a loop id comment so the pulse can track them; a
second run is a byte-for-byte no-op.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

from jotd import pulselog
from jotd.config import load_config
from jotd.formats import UNSTAMPED_LOOP_RE, parse_loop_line, parse_processed_line

OWNER_RE = re.compile(r"\bowner:\s*(?P<owner>[\w-]+)\s*$")

MD_HEADER = (
    "# Open loops — derived by `jotd derive`; do not hand-edit.\n"
    "# Respond with `jotd done|snooze|drop <id>` (any unique id fragment works).\n"
)


def _notes(data_dir: Path) -> list[Path]:
    return sorted((data_dir / "notes").rglob("*.md"))


def _loop_id_for(rel: str, text: str, taken: set[str]) -> str:
    digest = hashlib.sha1(f"{rel}:{text}".encode()).hexdigest()
    for width in (6, 8, 10, 40):
        candidate = f"l-{digest[:width]}"
        if candidate not in taken:
            return candidate
    raise RuntimeError("loop id space exhausted")  # pragma: no cover


def stamp_hand_loops(data_dir: Path) -> int:
    """Stamp `- [ ]` lines that lack a loop comment. Returns lines stamped."""
    taken: set[str] = set()
    for md in _notes(data_dir):
        for line in md.read_text(encoding="utf-8").splitlines():
            parsed = parse_loop_line(line)
            if parsed:
                taken.add(parsed["id"])

    stamped = 0
    for md in _notes(data_dir):
        rel = str(md.relative_to(data_dir))
        lines = md.read_text(encoding="utf-8").splitlines()
        changed = False
        for i, line in enumerate(lines):
            if parse_loop_line(line):
                continue
            m = UNSTAMPED_LOOP_RE.match(line)
            if not m:
                continue
            loop_id = _loop_id_for(rel, m.group("text"), taken)
            taken.add(loop_id)
            lines[i] = f"{line.rstrip()} <!-- loop:{loop_id} -->"
            changed = True
            stamped += 1
        if changed:
            md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return stamped


def _first_seen(loop_id: str, previous: dict[str, str], today: date) -> str:
    if loop_id.startswith("cap-"):
        return datetime.strptime(loop_id.split("-")[1], "%Y%m%d").date().isoformat()
    return previous.get(loop_id) or today.isoformat()


def _note_activity(data_dir: Path) -> dict[str, list[tuple[str, str]]]:
    """note path -> [(capture_id, date)] from processed.log."""
    log = data_dir / "state" / "processed.log"
    activity: dict[str, list[tuple[str, str]]] = {}
    if log.is_file():
        for line in log.read_text(encoding="utf-8").splitlines():
            if line.strip():
                cap_id, paths, ts = parse_processed_line(line)
                for p in paths:
                    activity.setdefault(p, []).append((cap_id, ts[:10]))
    return activity


def collect_loops(data_dir: Path, today: date) -> list[dict[str, Any]]:
    prev_path = data_dir / "state" / "open-loops.json"
    previous: dict[str, str] = {}
    if prev_path.is_file():
        for loop in json.loads(prev_path.read_text(encoding="utf-8")).get("loops", []):
            previous[loop["id"]] = loop.get("first_seen", "")

    cfg = load_config(data_dir)
    folded = pulselog.fold(pulselog.read_events(data_dir))
    activity = _note_activity(data_dir)

    loops = []
    for md in _notes(data_dir):
        rel = str(md.relative_to(data_dir))
        for lineno, line in enumerate(md.read_text(encoding="utf-8").splitlines(), 1):
            parsed = parse_loop_line(line)
            if not parsed:
                continue
            text = parsed["text"]
            owner_m = OWNER_RE.search(text)
            first_seen = _first_seen(parsed["id"], previous, today)
            age = (today - date.fromisoformat(first_seen)).days
            state = folded.get(parsed["id"], {})

            if parsed["state"] == "done" or state.get("done"):
                status = "done"
            elif state.get("silenced"):
                status = "silenced"
            elif state.get("snoozed_until") and pulselog.is_snoozed(state, today):
                status = "snoozed"
            else:
                status = "open"

            later_activity = any(
                d > first_seen and cap != parsed["id"] for cap, d in activity.get(rel, [])
            )
            loops.append(
                {
                    "id": parsed["id"],
                    "text": text,
                    "note": rel,
                    "src": f"{rel}:{lineno}",
                    "owner": owner_m.group("owner") if owner_m else "me",
                    "status": status,
                    "first_seen": first_seen,
                    "age_days": age,
                    "stale": status == "open"
                    and age >= cfg.stale_after_days
                    and not later_activity,
                    "snoozed_until": state.get("snoozed_until"),
                    "drops": state.get("drops", 0),
                    "nudges": state.get("nudges", 0),
                    "last_nudged": state.get("last_nudged"),
                }
            )
    return loops


def _frontmatter(text: str) -> dict[str, Any]:
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---", 4)
    if end < 0:
        return {}
    out: dict[str, Any] = {}
    for line in text[4:end].splitlines():
        key, sep, val = line.partition(":")
        if not sep:
            continue
        val = val.strip()
        if val.startswith("[") and val.endswith("]"):
            out[key.strip()] = [v.strip().strip("'\"") for v in val[1:-1].split(",") if v.strip()]
        else:
            out[key.strip()] = val
    return out


def build_entities(data_dir: Path) -> dict[str, Any]:
    activity = _note_activity(data_dir)
    bodies: dict[str, str] = {
        str(md.relative_to(data_dir)): md.read_text(encoding="utf-8") for md in _notes(data_dir)
    }
    entities: dict[str, Any] = {}
    for rel, text in bodies.items():
        fm = _frontmatter(text)
        if not fm.get("title"):
            continue
        slug = Path(rel).stem
        mentions = sum(body.count(f"[[{slug}]]") for other, body in bodies.items() if other != rel)
        dates = [d for _cap, d in activity.get(rel, [])]
        entities[slug] = {
            "type": fm.get("type", ""),
            "title": fm.get("title", ""),
            "aliases": fm.get("aliases", []),
            "path": rel,
            "mentions": mentions,
            "last_seen": max(dates) if dates else fm.get("created", ""),
        }
    return entities


def _render_md(loops: list[dict[str, Any]], today: date) -> str:
    def line(lp: dict[str, Any]) -> str:
        flags = f"{lp['age_days']}d" + (", stale" if lp["stale"] else "")
        owner = "" if lp["owner"] == "me" else f" owner:{lp['owner']}"
        return f"- [{flags}] {lp['text']} ({lp['note']}, id {lp['id']}{owner})"

    active = sorted(
        (lp for lp in loops if lp["status"] == "open"),
        key=lambda lp: (not lp["stale"], -lp["age_days"]),
    )
    snoozed = [lp for lp in loops if lp["status"] == "snoozed"]
    silenced = [lp for lp in loops if lp["status"] == "silenced"]

    parts = [MD_HEADER, f"\n_{today.isoformat()} — {len(active)} active_\n", "\n## Active\n"]
    parts += [line(lp) + "\n" for lp in active] or []
    if snoozed:
        parts.append("\n## Snoozed\n")
        parts += [
            f"- {lp['text']} (until {lp['snoozed_until']}, id {lp['id']})\n" for lp in snoozed
        ]
    if silenced:
        parts.append("\n## Silenced (dropped twice — the pulse will never mention these again)\n")
        parts += [f"- {lp['text']} (id {lp['id']})\n" for lp in silenced]
    return "".join(parts)


def derive(data_dir: Path, today: date | None = None) -> dict[str, Any]:
    today = today or date.today()
    stamped = stamp_hand_loops(data_dir)
    loops = collect_loops(data_dir, today)
    entities = build_entities(data_dir)

    state = data_dir / "state"
    state.mkdir(parents=True, exist_ok=True)
    (state / "open-loops.json").write_text(
        json.dumps({"generated": today.isoformat(), "loops": loops}, indent=1, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )
    (state / "open-loops.md").write_text(_render_md(loops, today), encoding="utf-8")
    (state / "entities.json").write_text(
        json.dumps({"generated": today.isoformat(), "entities": entities}, indent=1, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    open_loops = [lp for lp in loops if lp["status"] == "open"]
    return {
        "stamped": stamped,
        "loops_total": len(loops),
        "loops_open": len(open_loops),
        "loops_stale": sum(lp["stale"] for lp in open_loops),
        "entities": len(entities),
    }
