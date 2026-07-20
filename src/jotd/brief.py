"""The deterministic team brief — `jotd hook session-start`'s read side (D12).

Pure Python over derived state and inbox records: no LLM, no tokens, ~0ms
added to session start. Claude Code injects whatever a SessionStart hook
prints to stdout into the new session's context, so this module is how every
session (any repo, any machine) starts already knowing the team's state.
Selection and the char budget are enforced here in code (D5); on any doubt
the hook prints nothing — a brief must never noise up a session start.
"""

from __future__ import annotations

import json
import os
import subprocess
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from jotd import headless, inbox
from jotd.author import slugify
from jotd.config import resolve_data_dir
from jotd.formats import parse_capture_line, parse_processed_line

BRIEF_CHAR_BUDGET = 4000
MAX_LOOPS = 8
MAX_NOTES = 10
SNIPPETS_PER_AUTHOR = 3
RECENT_DAYS = 3
SNIPPET_CHARS = 120


def _log(data_dir: Path, session_id: str, status: str, detail: str) -> None:
    """Same log file as the SessionEnd scribe; hook=start is the discriminator."""
    try:
        ts = datetime.now().astimezone().isoformat(timespec="seconds")
        detail = " ".join(detail.split())[:400]
        inbox._append_line(
            data_dir / "state" / "logs" / "session-hook.log",
            f"{ts} session={session_id or '?'} hook=start {status}: {detail}\n",
        )
    except OSError:
        pass


def _git(data_dir: Path, *args: str) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            ["git", *args], cwd=data_dir, capture_output=True, text=True, timeout=5, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


def _open_loops(data_dir: Path) -> tuple[str, list[dict[str, Any]]]:
    """(generated-date, open loops sorted stale-first then oldest-first)."""
    path = data_dir / "state" / "open-loops.json"
    if not path.is_file():
        return "", []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return "", []
    loops = [lp for lp in data.get("loops", []) if lp.get("status") == "open"]
    loops.sort(key=lambda lp: (not lp.get("stale"), -int(lp.get("age_days", 0))))
    return str(data.get("generated", "")), loops


def _recent_captures(data_dir: Path, today: date) -> list[dict[str, Any]]:
    cutoff = (today - timedelta(days=RECENT_DAYS)).isoformat()
    records: list[dict[str, Any]] = []
    for path in sorted((data_dir / "inbox").glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                rec = parse_capture_line(line)
            except (ValueError, json.JSONDecodeError):
                continue
            if str(rec.get("ts", "")) >= cutoff:
                records.append(rec)
    # filename order is author-lexicographic, never chronological — sort by record ts
    records.sort(key=lambda r: str(r.get("ts", "")))
    return records


def _recent_notes(data_dir: Path, today: date) -> list[str]:
    cutoff = (today - timedelta(days=RECENT_DAYS)).isoformat()
    log = data_dir / "state" / "processed.log"
    paths: set[str] = set()
    if log.is_file():
        for line in log.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                _id, routed, ts = parse_processed_line(line)
            except ValueError:
                continue
            if ts >= cutoff:
                paths.update(routed)
    return sorted(paths)


def _cwd_tokens(cwd: str) -> list[str]:
    """Focus candidates from the session's directory, most specific first:
    the directory basename, then the origin remote's repo name. NO LLM."""
    tokens: list[str] = []
    base = slugify(Path(cwd).name)
    if base:
        tokens.append(base)
    remote = _git(Path(cwd), "remote", "get-url", "origin")
    if remote and remote.returncode == 0 and remote.stdout.strip():
        name = remote.stdout.strip().rstrip("/").rsplit("/", 1)[-1]
        name = name.rsplit(":", 1)[-1]  # scp-style git@host:repo with no slash
        name = name.removesuffix(".git")
        slug = slugify(name)
        if slug and slug not in tokens:
            tokens.append(slug)
    return tokens


def _load_entities(data_dir: Path) -> dict[str, dict[str, Any]]:
    path = data_dir / "state" / "entities.json"
    if path.is_file():
        try:
            entities = json.loads(path.read_text(encoding="utf-8")).get("entities", {})
            if isinstance(entities, dict) and entities:
                return entities
        except (json.JSONDecodeError, OSError):
            pass
    # no derived state yet — fall back to project note filenames
    projects = data_dir / "notes" / "projects"
    if not projects.is_dir():
        return {}
    return {
        p.stem: {"type": "project", "aliases": [], "path": f"notes/projects/{p.name}"}
        for p in sorted(projects.glob("*.md"))
    }


def _match_focus(tokens: list[str], data_dir: Path) -> tuple[str, str] | None:
    """(slug, note relpath) the session's cwd points at, or None. Deterministic:
    projects beat other entity types; exact slug beats alias beats containment;
    containment needs >= 4 chars on the shorter side (kills 'api'-grade noise)."""
    entities = _load_entities(data_dir)
    if not tokens or not entities:
        return None
    projects = {s: e for s, e in entities.items() if e.get("type") == "project"}
    for pool in (projects, entities):
        for token in tokens:
            if token in pool:
                return token, str(pool[token].get("path", ""))
            for slug in sorted(pool):
                aliases = pool[slug].get("aliases") or []
                if any(slugify(str(a)) == token for a in aliases):
                    return slug, str(pool[slug].get("path", ""))
            contains = sorted(
                (
                    slug
                    for slug in pool
                    if min(len(slug), len(token)) >= 4 and (token in slug or slug in token)
                ),
                key=lambda s: (-len(s), s),
            )
            if contains:
                return contains[0], str(pool[contains[0]].get("path", ""))
    return None


def _fresh_daily_brief(data_dir: Path, now: datetime) -> Path | None:
    briefs = data_dir / "state" / "briefs"
    if not briefs.is_dir():
        return None
    candidates = sorted(briefs.glob("*.md"))
    if not candidates:
        return None
    latest = candidates[-1]
    try:
        age_s = now.timestamp() - latest.stat().st_mtime
    except OSError:
        return None
    return latest if age_s < 24 * 3600 else None


def _header_bits(data_dir: Path, generated: str) -> list[str]:
    bits: list[str] = []
    if generated:
        bits.append(f"state derived {generated}")
    last = _git(data_dir, "log", "-1", "--format=%cI")
    if last and last.returncode == 0 and last.stdout.strip():
        bits.append(f"last commit {last.stdout.strip()[:16]}")
    unsynced = _unsynced_captures(data_dir)
    if unsynced:
        bits.append(f"{unsynced} capture(s) on this machine not yet synced — run `jotd sync`")
    return bits


def _unsynced_captures(data_dir: Path) -> int:
    """Capture lines written locally but not committed — the staleness nudge."""
    count = 0
    numstat = _git(data_dir, "diff", "HEAD", "--numstat", "--", "inbox/")
    if numstat and numstat.returncode == 0:
        for line in numstat.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) == 3 and parts[0].isdigit():
                count += int(parts[0])
    porcelain = _git(data_dir, "status", "--porcelain", "--", "inbox/")
    if porcelain and porcelain.returncode == 0:
        for line in porcelain.stdout.splitlines():
            if line.startswith("??"):
                f = data_dir / line[3:].strip()
                if f.is_file():
                    count += sum(1 for ln in f.read_text(encoding="utf-8").splitlines() if ln)
    return count


def build_brief(
    data_dir: Path,
    now: datetime | None = None,
    budget: int = BRIEF_CHAR_BUDGET,
    cwd: str | None = None,
) -> str | None:
    """Render the brief, or None when there is nothing worth injecting.

    With a cwd, sections are re-ranked around the project the session is in
    (D14) — deterministically; without one (or without a match) the output is
    byte-identical to the unranked brief.
    """
    now = now or datetime.now().astimezone()
    today = now.date()
    generated, loops = _open_loops(data_dir)
    captures = _recent_captures(data_dir, today)
    notes = _recent_notes(data_dir, today)
    if not loops and not captures and not notes:
        return None
    focus = _match_focus(_cwd_tokens(cwd), data_dir) if cwd else None

    lines: list[str] = ["# jotd brief (auto-injected at session start)"]
    bits = _header_bits(data_dir, generated)
    if focus:
        bits.insert(0, f"focus: {focus[0]} ({focus[1]})")
    if bits:
        lines.append("_" + " · ".join(bits) + "_")

    if loops:
        if focus:
            # stable: focus-note loops float as a block, stale-first kept within tiers
            loops.sort(key=lambda lp: lp.get("note") != focus[1])
        shown = loops[:MAX_LOOPS]
        lines += ["", f"## Open loops ({len(loops)} open, top {len(shown)})"]
        for lp in shown:
            flag = " STALE" if lp.get("stale") else ""
            lines.append(
                f"- [{lp.get('owner', 'me')}]{flag} {lp.get('text', '')} "
                f"({lp.get('age_days', 0)}d — {lp.get('note', '')})"
            )

    if captures:
        focus_ids: set[str] = set()
        if focus:
            focus_ids = {
                cap_id
                for cap_id, routed in inbox.processed_entries(data_dir).items()
                if focus[1] in routed
            }
        by_author: dict[str, list[dict[str, Any]]] = {}
        for r in captures:
            by_author.setdefault(str(r.get("author", "unknown")), []).append(r)
        lines += ["", f"## Captured in the last {RECENT_DAYS} days"]
        for who in sorted(by_author):
            recs = by_author[who]
            chosen = recs[-SNIPPETS_PER_AUTHOR:]
            if focus_ids and any(r["id"] in focus_ids for r in recs):
                # captures routed to the focus note displace the newest-3 default
                preferred = [r for r in recs if r["id"] in focus_ids][-SNIPPETS_PER_AUTHOR:]
                rest = [r for r in recs if r["id"] not in focus_ids]
                k = SNIPPETS_PER_AUTHOR - len(preferred)
                chosen = sorted(
                    preferred + (rest[-k:] if k > 0 else []),
                    key=lambda r: str(r.get("ts", "")),
                )
            lines.append(f"- **{who}** ({len(recs)}):")
            for r in chosen:
                snippet = " ".join(str(r.get("text", "")).split())[:SNIPPET_CHARS]
                lines.append(f"  - {snippet}")

    if notes:
        if focus:
            notes.sort(key=lambda p: p != focus[1])  # stable: matched note first
        lines += ["", f"## Notes touched in the last {RECENT_DAYS} days"]
        lines += [f"- {p}" for p in notes[:MAX_NOTES]]

    daily = _fresh_daily_brief(data_dir, now)
    if daily:
        lines += ["", f"Daily brief: {daily.relative_to(data_dir)} (`jotd log --brief`)"]

    lines += [
        "",
        f"_Full state: {data_dir}/state/open-loops.md · capture into it with "
        '`jotd add "..."` from any directory_',
    ]

    # hard budget: drop whole lines from the bottom, never cut mid-line (D5)
    text = "\n".join(lines)
    while len(text) > budget and len(lines) > 2:
        lines.pop()
        text = "\n".join(lines)
    return text + "\n"


def run_session_start(payload: dict[str, Any]) -> str | None:
    """Core of `jotd hook session-start`; returns the brief to print, or None.

    Mirrors run_session_end's posture: every failure path is a (logged) skip,
    and the recursion breakers are the same two — the env guard set on every
    jotd headless child, and skipping sessions inside the data dir itself.
    """
    session_id = str(payload.get("session_id", ""))
    source = str(payload.get("source", ""))
    cwd = str(payload.get("cwd", ""))

    if os.environ.get(headless.HOOK_ENV_GUARD):
        return None  # scribe/pulse child session — no log, data dir not trusted yet

    data_dir = resolve_data_dir(None)
    if not (data_dir / "jotd.toml").is_file():
        return None
    if source in ("resume", "compact"):
        # the restored/compacted context already carries an injected brief
        _log(data_dir, session_id, "skip", f"source={source}")
        return None
    if cwd and Path(cwd).expanduser().resolve() == data_dir:
        _log(data_dir, session_id, "skip", "session in the jotd directory itself")
        return None

    brief = build_brief(data_dir, cwd=cwd or None)
    if brief is None:
        _log(data_dir, session_id, "skip", "nothing to brief")
        return None
    _log(data_dir, session_id, "ok", f"brief {len(brief)} chars")
    return brief
