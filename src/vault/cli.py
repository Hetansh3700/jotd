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


def main() -> None:
    app()


if __name__ == "__main__":
    main()
