"""The `vault` CLI. Deterministic entry points only — no LLM calls in this file
except `vault pulse`, which shells out to a headless claude run (M4)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Annotated

import typer

from vault import inbox
from vault.config import resolve_data_dir
from vault.init import scaffold

app = typer.Typer(no_args_is_help=True, add_completion=False, rich_markup_mode=None)

DirOpt = Annotated[Path | None, typer.Option("--dir", help="vault data dir override")]


def _dir(explicit: Path | None) -> Path:
    d = resolve_data_dir(explicit)
    if not (d / "vault.toml").is_file():
        typer.echo(f"error: {d} is not a vault (run `vault init {d}` first)", err=True)
        raise typer.Exit(2)
    return d


@app.command()
def init(
    directory: Annotated[Path | None, typer.Argument(help="target dir (default ~/vault)")] = None,
    upgrade: Annotated[bool, typer.Option(help="re-sync unmodified managed files")] = False,
    git: Annotated[bool, typer.Option(help="git-init the data dir")] = True,
    set_default: Annotated[bool, typer.Option(help="point the default vault here")] = False,
) -> None:
    """Scaffold (or upgrade) a vault data dir with agents, commands, and conventions."""
    target = (directory or Path.home() / "vault").expanduser()
    actions = scaffold(target, git=git, upgrade=upgrade, set_default=set_default)
    for a in actions:
        typer.echo(a)
    typer.echo(f"vault ready: {target}")


@app.command()
def add(
    text: Annotated[list[str] | None, typer.Argument()] = None,
    source: Annotated[str, typer.Option()] = "cli",
    directory: DirOpt = None,
) -> None:
    """Append a capture to the inbox (append-only; reads stdin when no TEXT or TEXT is '-')."""
    joined = " ".join(text) if text else ""
    if not joined or joined == "-":
        joined = sys.stdin.read()
    try:
        record = inbox.append_capture(_dir(directory), joined, source=source)
    except (inbox.VaultError, ValueError) as e:
        typer.echo(f"error: {e}", err=True)
        raise typer.Exit(1) from None
    typer.echo(record["id"])


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
    paths: Annotated[str, typer.Argument(help="comma-separated vault-relative note paths")],
    directory: DirOpt = None,
) -> None:
    """Record where a capture was routed (the ONLY way state/processed.log is written)."""
    try:
        inbox.mark_processed(_dir(directory), capture_id, paths.split(","))
    except inbox.VaultError as e:
        typer.echo(f"error: {e}", err=True)
        raise typer.Exit(1) from None
    typer.echo(f"processed {capture_id}")


@app.command()
def derive(directory: DirOpt = None) -> None:
    """Rebuild derived state: open-loops.md/.json and entities.json (idempotent)."""
    from vault.derive import derive as run_derive

    summary = run_derive(_dir(directory))
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
    from vault.pulse import run_pulse

    result = run_pulse(_dir(directory), "manual" if now else slot, dry_run=dry_run)
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
    from vault.feedback import respond

    try:
        typer.echo(respond(_dir(directory), fragment, action, days=days))
    except inbox.VaultError as e:
        typer.echo(f"error: {e}", err=True)
        raise typer.Exit(1) from None


@app.command()
def done(loop: str, directory: DirOpt = None) -> None:
    """Mark a nudged loop done (flips its checkbox in the note too)."""
    _respond("done", loop, None, directory)


@app.command()
def snooze(
    loop: str,
    days: Annotated[int | None, typer.Option()] = None,
    directory: DirOpt = None,
) -> None:
    """Snooze a loop (default vault.toml snooze_days); the pulse stays quiet until then."""
    _respond("snooze", loop, days, directory)


@app.command()
def drop(loop: str, directory: DirOpt = None) -> None:
    """Drop a nudge; two drops on one loop silence it permanently."""
    _respond("drop", loop, None, directory)


schedule_app = typer.Typer(no_args_is_help=True, add_completion=False)
app.add_typer(schedule_app, name="schedule", help="launchd scheduling for the pulse (macOS)")


@schedule_app.command("install")
def schedule_install(directory: DirOpt = None) -> None:
    """Write per-slot launchd plists and bootstrap them into the gui domain."""
    from vault import sched

    for line in sched.install(_dir(directory)):
        typer.echo(line)


@schedule_app.command("uninstall")
def schedule_uninstall() -> None:
    """Boot out and remove all vault pulse plists."""
    from vault import sched

    for line in sched.uninstall():
        typer.echo(line)


@schedule_app.command("status")
def schedule_status() -> None:
    from vault import sched

    for line in sched.status():
        typer.echo(line)


@app.command()
def status(directory: DirOpt = None) -> None:
    """Vault health: inbox backlog, open loops, last pulse heartbeat, schedule."""
    from datetime import datetime, timedelta

    from vault import pulselog, sched

    d = _dir(directory)
    backlog = len(inbox.unprocessed(d))
    events = pulselog.read_events(d)
    beats = [e for e in events if e["kind"] == "heartbeat"]
    typer.echo(f"vault: {d}")
    typer.echo(f"inbox backlog: {backlog} unprocessed")
    loops_md = d / "state" / "open-loops.md"
    if loops_md.is_file():
        typer.echo(loops_md.read_text().splitlines()[3].strip("_ "))
    if beats:
        last = beats[-1]
        typer.echo(f"last pulse: {last['ts']} slot={last['slot']} status={last['status']}")
        last_ok = next((b for b in reversed(beats) if b["status"] == "ok"), None)
        stale_after = datetime.now().astimezone() - timedelta(hours=36)
        if not last_ok or datetime.fromisoformat(last_ok["ts"]) < stale_after:
            typer.echo(
                "WARNING: no successful pulse heartbeat in 36h — check vault schedule status"
            )
    else:
        typer.echo("last pulse: never")
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
    from vault.pulselog import log_path

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
