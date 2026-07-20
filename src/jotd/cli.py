"""The `jotd` CLI. Deterministic entry points only — no LLM calls in this file
except `jotd pulse`, which shells out to a headless claude run (M4)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Annotated

import typer

from jotd import inbox
from jotd.author import resolve_author, resolve_author_with_rule
from jotd.config import load_team, resolve_data_dir
from jotd.init import scaffold

app = typer.Typer(no_args_is_help=True, add_completion=False, rich_markup_mode=None)

DirOpt = Annotated[Path | None, typer.Option("--dir", help="jotd data dir override")]
AuthorOpt = Annotated[
    str | None, typer.Option("--author", help="author slug override (default: this machine's)")
]


def _dir(explicit: Path | None) -> Path:
    d = resolve_data_dir(explicit)
    if not (d / "jotd.toml").is_file():
        typer.echo(f"error: {d} is not a jotd directory (run `jotd init {d}` first)", err=True)
        raise typer.Exit(2)
    return d


def _librarian_gate(d: Path, author_flag: str | None = None) -> None:
    """State-writing commands run only on the librarian's machine (D12).

    Solo mode (no [team] table) is unrestricted. This is a guard against
    accidental multi-machine state writes, not authentication.
    """
    team = load_team(d)
    if team.librarian is None:
        return
    me = resolve_author(author_flag)
    if me != team.librarian:
        typer.echo(
            f"error: this machine is '{me}' but the librarian is '{team.librarian}' "
            "(jotd.toml [team]) — state-writing commands run only on the librarian's "
            "machine; capture and `jotd sync` from here instead",
            err=True,
        )
        raise typer.Exit(2)


@app.command()
def init(
    directory: Annotated[Path | None, typer.Argument(help="target dir (default ~/jotd)")] = None,
    upgrade: Annotated[bool, typer.Option(help="re-sync unmodified managed files")] = False,
    git: Annotated[bool, typer.Option(help="git-init the data dir")] = True,
    set_default: Annotated[bool, typer.Option(help="point the default jotd dir here")] = False,
) -> None:
    """Scaffold (or upgrade) a jotd data dir with agents, commands, and conventions."""
    target = (directory or Path.home() / "jotd").expanduser()
    actions = scaffold(target, git=git, upgrade=upgrade, set_default=set_default)
    for a in actions:
        typer.echo(a)
    typer.echo(f"jotd ready: {target}")


def _append(
    text: list[str] | None,
    source: str,
    context: dict[str, str] | None,
    directory: Path | None,
    author_flag: str | None = None,
) -> None:
    joined = " ".join(text) if text else ""
    if not joined or joined == "-":
        joined = sys.stdin.read()
    try:
        record = inbox.append_capture(
            _dir(directory),
            joined,
            source=source,
            author=resolve_author(author_flag),
            context=context,
        )
    except (inbox.JotdError, ValueError) as e:
        typer.echo(f"error: {e}", err=True)
        raise typer.Exit(1) from None
    typer.echo(record["id"])


@app.command()
def add(
    text: Annotated[list[str] | None, typer.Argument()] = None,
    source: Annotated[str, typer.Option()] = "cli",
    author: AuthorOpt = None,
    directory: DirOpt = None,
) -> None:
    """Append a capture to the inbox (append-only; reads stdin when no TEXT or TEXT is '-')."""
    _append(text, source, None, directory, author)


@app.command()
def capture(
    text: Annotated[list[str] | None, typer.Argument()] = None,
    source: Annotated[str, typer.Option()] = "screen",
    app_name: Annotated[str | None, typer.Option("--app", help="frontmost app name")] = None,
    title: Annotated[str | None, typer.Option(help="window title, if known")] = None,
    method: Annotated[str | None, typer.Option(help="region|window|fullscreen|ax")] = None,
    author: AuthorOpt = None,
    directory: DirOpt = None,
) -> None:
    """Append a capture with source metadata (for capture clients like screen OCR).

    Same append path as `add` — metadata lands in the record's `context` and reaches
    the librarian as a routing HINT via `jotd unprocessed --json`. Clients should
    pipe text via stdin (TEXT of '-') to avoid argv quoting hazards.
    """
    context = {k: v for k, v in (("app", app_name), ("title", title), ("method", method)) if v}
    _append(text, source, context or None, directory, author)


@app.command()
def whoami() -> None:
    """Print this machine's author slug and which rule resolved it."""
    slug, rule = resolve_author_with_rule(None)
    typer.echo(f"{slug}  (from {rule})")


@app.command()
def sync(
    no_derive: Annotated[
        bool, typer.Option("--no-derive", help="skip the librarian's auto-derive")
    ] = False,
    auto: Annotated[
        bool,
        typer.Option(
            "--auto",
            help="scheduled mode: log to state/logs/sync-auto.log, notify once "
            "on failure, always exit 0 (launchd owns the schedule, we own retries)",
        ),
    ] = False,
    author: AuthorOpt = None,
    directory: DirOpt = None,
) -> None:
    """Sync the data dir with its git remote: commit, pull --rebase, push."""
    if auto:
        # --no-derive is ignored here: auto mode IS the librarian-derive path
        try:
            from jotd.autosync import run_auto_sync

            run_auto_sync(_dir(directory), resolve_author(author))
        except Exception:  # noqa: BLE001 — a scheduled job must never exit non-zero
            pass
        return
    from jotd.sync import run_sync

    try:
        lines = run_sync(_dir(directory), resolve_author(author), derive_after_pull=not no_derive)
    except inbox.JotdError as e:
        typer.echo(f"error: {e}", err=True)
        raise typer.Exit(2) from None
    for line in lines:
        typer.echo(line)


@app.command()
def unprocessed(
    as_json: Annotated[bool, typer.Option("--json")] = False,
    directory: DirOpt = None,
) -> None:
    """List captures the librarian has not routed yet."""
    records = inbox.unprocessed(_dir(directory))
    if as_json:
        typer.echo(json.dumps(records, ensure_ascii=False, indent=1))
    elif not records:
        typer.echo("inbox clear — nothing unprocessed")
    else:
        for r in records:
            typer.echo(f"{r['id']}  {r['text']}")


@app.command("mark-processed")
def mark_processed(
    capture_id: str,
    paths: Annotated[str, typer.Argument(help="comma-separated data-dir-relative note paths")],
    directory: DirOpt = None,
) -> None:
    """Record where a capture was routed (the ONLY way state/processed.log is written)."""
    d = _dir(directory)
    _librarian_gate(d)
    try:
        inbox.mark_processed(d, capture_id, paths.split(","))
    except inbox.JotdError as e:
        typer.echo(f"error: {e}", err=True)
        raise typer.Exit(1) from None
    typer.echo(f"processed {capture_id}")


@app.command()
def derive(directory: DirOpt = None) -> None:
    """Rebuild derived state: open-loops.md/.json and entities.json (idempotent)."""
    from jotd.derive import derive as run_derive

    d = _dir(directory)
    _librarian_gate(d)
    summary = run_derive(d)
    typer.echo(
        f"stamped {summary['stamped']} hand-written loops; "
        f"{summary['loops_open']} open ({summary['loops_stale']} stale); "
        f"{summary['entities']} entities indexed"
    )


@app.command()
def pulse(
    slot: Annotated[str, typer.Option(help="morning|midday|evening|manual")] = "manual",
    now: Annotated[
        bool, typer.Option("--now", help="manual trigger (same as --slot manual)")
    ] = False,
    dry_run: Annotated[bool, typer.Option(help="decide but do not notify or log")] = False,
    directory: DirOpt = None,
) -> None:
    """Run the pulse: derive state, let the model judge, deliver within the budget."""
    from jotd.pulse import run_pulse

    d = _dir(directory)
    _librarian_gate(d)
    result = run_pulse(d, "manual" if now else slot, dry_run=dry_run)
    if result["status"] == "error":
        typer.echo(f"pulse error (logged, nothing sent): {result['error']}", err=True)
        raise typer.Exit(1)
    if result["status"] == "skipped":
        typer.echo("skipped: another pulse run is in flight")
        return
    for a in result.get("actions", []):
        typer.echo(a)
    typer.echo(
        f"pulse ok: {len(result.get('nudges', []))} nudged, "
        f"{len(result.get('suppressed', []))} suppressed by judgment, "
        f"{len(result.get('runner_rejected', []))} rejected by the runner"
    )


def _respond(action: str, fragment: str, days: int | None, directory: Path | None) -> None:
    from jotd.feedback import respond

    try:
        typer.echo(respond(_dir(directory), fragment, action, days=days))
    except inbox.JotdError as e:
        typer.echo(f"error: {e}", err=True)
        raise typer.Exit(1) from None


@app.command()
def done(loop: str, directory: DirOpt = None) -> None:
    """Mark a nudged loop done (flips its checkbox in the note too)."""
    d = _dir(directory)
    team = load_team(d)
    if team.librarian is not None and resolve_author(None) != team.librarian:
        # Non-librarian `done` degrades to a checkbox flip (D12): notes are the
        # shared human layer, and the librarian's derive folds [x] into status.
        from jotd.feedback import flip_only

        try:
            typer.echo(flip_only(d, loop))
        except inbox.JotdError as e:
            typer.echo(f"error: {e}", err=True)
            raise typer.Exit(1) from None
        return
    _respond("done", loop, None, directory)


@app.command()
def snooze(
    loop: str,
    days: Annotated[int | None, typer.Option()] = None,
    directory: DirOpt = None,
) -> None:
    """Snooze a loop (default jotd.toml snooze_days); the pulse stays quiet until then."""
    _librarian_gate(_dir(directory))
    _respond("snooze", loop, days, directory)


@app.command()
def drop(loop: str, directory: DirOpt = None) -> None:
    """Drop a nudge; two drops on one loop silence it permanently."""
    _librarian_gate(_dir(directory))
    _respond("drop", loop, None, directory)


schedule_app = typer.Typer(no_args_is_help=True, add_completion=False)
app.add_typer(
    schedule_app, name="schedule", help="launchd scheduling for the pulse and auto-sync (macOS)"
)


@schedule_app.command("install")
def schedule_install(directory: DirOpt = None) -> None:
    """Install what fits THIS machine: pulse slots (librarian/solo only) and,
    with [sync] auto = true, the auto-sync job (any machine)."""
    from jotd import sched
    from jotd.config import load_sync, load_team

    d = _dir(directory)
    team = load_team(d)
    me = resolve_author(None)
    installed: list[str] = []
    pulse_allowed = team.librarian is None or me == team.librarian
    if pulse_allowed:
        installed += sched.install(d)  # a pulse elsewhere would fail 3x daily (D12)
    else:
        typer.echo(
            f"pulse schedule skipped: this machine is '{me}', the librarian is "
            f"'{team.librarian}' — the pulse runs only there"
        )
    sync_cfg = load_sync(d)
    if sync_cfg.auto:
        installed += sched.install_sync(d, sync_cfg.interval_minutes)
    else:
        typer.echo("auto-sync schedule skipped: set [sync] auto = true in jotd.toml to enable")
    for line in installed:
        typer.echo(line)
    if not installed and not pulse_allowed:
        raise typer.Exit(2)  # nothing installable here — keep the old guard's teeth


@schedule_app.command("uninstall")
def schedule_uninstall() -> None:
    """Boot out and remove all jotd plists (pulse slots and auto-sync)."""
    from jotd import sched

    for line in sched.uninstall():
        typer.echo(line)


@schedule_app.command("status")
def schedule_status() -> None:
    from jotd import sched

    for line in sched.status():
        typer.echo(line)


@app.command("install")
def install_cmd(
    target: Annotated[str, typer.Argument(help="integration to install (claude-code)")],
    hook: Annotated[
        bool,
        typer.Option(
            "--hook",
            help="auto-capture sessions (SessionEnd) and inject the brief (SessionStart)",
        ),
    ] = False,
    upgrade: Annotated[bool, typer.Option(help="re-sync unmodified managed files")] = False,
) -> None:
    """Install the global /jotd:session command (and optional session hooks)."""
    if target != "claude-code":
        typer.echo(f"error: unknown install target {target!r} (try: claude-code)", err=True)
        raise typer.Exit(2)
    from jotd.install import install_claude_code

    for line in install_claude_code(hook=hook, upgrade=upgrade):
        typer.echo(line)


@app.command("uninstall")
def uninstall_cmd(
    target: Annotated[str, typer.Argument(help="integration to remove (claude-code)")],
) -> None:
    """Remove the global command files and both session hooks."""
    if target != "claude-code":
        typer.echo(f"error: unknown install target {target!r} (try: claude-code)", err=True)
        raise typer.Exit(2)
    from jotd.install import uninstall_claude_code

    for line in uninstall_claude_code():
        typer.echo(line)


hook_app = typer.Typer(no_args_is_help=True, add_completion=False)
app.add_typer(hook_app, name="hook", help="Claude Code hook entry points (machine-invoked)")


@hook_app.command("session-end")
def hook_session_end() -> None:
    """SessionEnd hook: distill the ended session into captures. Never fails loudly."""
    try:
        from jotd.session_capture import run_session_end

        payload = json.loads(sys.stdin.read())
        if isinstance(payload, dict):
            run_session_end(payload)
    except Exception:  # noqa: BLE001 — a hook must never break the user's session end
        pass


@hook_app.command("session-start")
def hook_session_start() -> None:
    """SessionStart hook: print the brief for context injection. Silent on any failure."""
    try:
        from jotd.brief import run_session_start

        payload = json.loads(sys.stdin.read())
        if isinstance(payload, dict):
            brief = run_session_start(payload)
            if brief:
                sys.stdout.write(brief)
    except Exception:  # noqa: BLE001 — a hook must never break the user's session start
        pass


@app.command()
def status(directory: DirOpt = None) -> None:
    """Health check: inbox backlog, open loops, last pulse heartbeat, schedule."""
    from datetime import datetime, timedelta

    from jotd import pulselog, sched
    from jotd.config import load_sync, load_team

    d = _dir(directory)
    backlog = len(inbox.unprocessed(d))
    events = pulselog.read_events(d)
    beats = [e for e in events if e["kind"] == "heartbeat"]
    typer.echo(f"jotd directory: {d}")
    sync_cfg = load_sync(d)
    backlog_line = f"inbox backlog: {backlog} unprocessed"
    if (
        sync_cfg.auto
        and sync_cfg.organize_backlog > 0
        and load_team(d).librarian == resolve_author(None)
    ):
        backlog_line += f" (auto-organize at >={sync_cfg.organize_backlog})"
    typer.echo(backlog_line)
    loops_md = d / "state" / "open-loops.md"
    if loops_md.is_file():
        typer.echo(loops_md.read_text().splitlines()[3].strip("_ "))
    if beats:
        last = beats[-1]
        typer.echo(f"last pulse: {last['ts']} slot={last['slot']} status={last['status']}")
        last_ok = next((b for b in reversed(beats) if b["status"] == "ok"), None)
        stale_after = datetime.now().astimezone() - timedelta(hours=36)
        if not last_ok or datetime.fromisoformat(last_ok["ts"]) < stale_after:
            typer.echo("WARNING: no successful pulse heartbeat in 36h — check jotd schedule status")
    else:
        typer.echo("last pulse: never")
    auto_log = d / "state" / "logs" / "sync-auto.log"
    if auto_log.is_file():
        tail = [ln for ln in auto_log.read_text(encoding="utf-8").splitlines() if ln.strip()]
        if tail:
            typer.echo(f"last auto-sync: {tail[-1]}")
    elif sync_cfg.auto:
        typer.echo("last auto-sync: never")
    conflict = d / "state" / "logs" / "sync-auto.conflict"
    if conflict.is_file():
        since = conflict.read_text(encoding="utf-8").split(" ", 1)[0]
        typer.echo(f"WARNING: auto-sync failing since {since} — run `jotd sync` by hand")
    for line in sched.status():
        typer.echo(f"schedule: {line}")


@app.command()
def log(
    brief: Annotated[bool, typer.Option("--brief", help="print today's daily brief")] = False,
    lines: Annotated[int, typer.Option("-n")] = 20,
    directory: DirOpt = None,
) -> None:
    """Tail the pulse log, or print today's brief with --brief."""
    from datetime import date

    d = _dir(directory)
    if brief:
        path = d / "state" / "briefs" / f"{date.today().isoformat()}.md"
        if path.is_file():
            typer.echo(path.read_text())
        else:
            typer.echo(f"no brief for {date.today().isoformat()} yet")
        return
    from jotd.pulselog import log_path

    path = log_path(d)
    if not path.is_file():
        typer.echo("pulse log is empty — the pulse has never run")
        return
    for line in path.read_text().splitlines()[-lines:]:
        typer.echo(line)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
