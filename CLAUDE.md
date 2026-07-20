# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

jotd-by-claude — a proactive notes brain for Claude Code. Python ≥ 3.11. The three-way name split is intentional (DECISIONS.md D10): PyPI dist `jotd-by-claude`, import package `jotd`, CLI `jotd`. Core loop: capture → organize → derive → pulse.

Note: `src/jotd/templates/CLAUDE.md` is a runtime template installed into a *user's data dir* by `jotd init` — it is not this repo's dev guide. `build/` and `dist/` are build artifacts; edit only under `src/`.

## Commands

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"    # setup
.venv/bin/pytest -q                                           # all unit tests (no LLM, no network)
.venv/bin/pytest tests/test_pulse.py -q                       # one file
.venv/bin/pytest tests/test_pulse.py::test_name -q            # one test
.venv/bin/ruff check . && .venv/bin/ruff format --check .     # lint + format gate (CI runs both)
python evals/run_routing.py    # LLM product gate — HUMAN-RUN ONLY: needs `claude` login, spends tokens; never wire into CI
```

CI (`.github/workflows/ci.yml`): ruff check + format-check, pytest on Python 3.11 and 3.12. CI never calls an LLM — it grades the committed golden run instead (see Evals).

## Architecture

**The load-bearing split: the LLM decides meaning and judgment; deterministic Python owns all state, aggregates, and the interruption budget.** Budgets, byte caps, and hook guards are enforced in code *after* the model answers and cannot be prompted around (D5). Preserve this split in every change.

Entry point: `jotd.cli:main` — a Typer app in `src/jotd/cli.py`. Data-dir resolution (`config.py::resolve_data_dir`): `--dir` > `$JOTD_DIR` > cwd if it contains `jotd.toml` > pointer file `~/.config/jotd/dir` > `~/jotd`. The cwd rule is load-bearing: headless agent subprocesses run with cwd = the data dir and need no other config.

Key modules under `src/jotd/`:

- `inbox.py` — the ONLY writer of `inbox/*.jsonl` and `state/processed.log`; one `O_APPEND` syscall per capture line.
- `formats.py` — capture/processed-line (de)serialization; enforces the 4096-byte line cap by raising *before* any write — oversize captures are rejected, never truncated (D1).
- `derive.py` — deterministically rebuilds `state/` from notes; stamps `- [ ]` checkboxes with stable loop ids. Loop status (done/snoozed/silenced) is always *folded* from pulse-log events at derive time, never stored.
- `pulse.py` + `budget.py` — the scheduled judgment run. The budget `min(per_run, per_day − sent_today)` is computed in code before the model is invoked; silenced/snoozed loops are pre-filtered out of the packet; the model's nudges are hard-truncated to the budget and hallucinated/duplicate loop ids rejected, with runner rejections logged as suppressions.
- `pulselog.py` — the ONLY writer of `state/pulse-log.md`; strict one-event-per-line grammar; every event is re-parsed before append and an unparseable event raises instead of corrupting the log (D6).
- `headless.py` — shared one-shot `claude -p … --output-format json` invoker (used by pulse, the session scribe, and auto-organize); disallows Bash/Edit/Write/WebSearch/WebFetch by default; `permission_mode` exists for the one caller that needs `acceptEdits` (D13).
- `autosync.py` — the `jotd sync --auto` runner (see Background propagation below).
- `init.py` / `install.py` — scaffolding with sha256 manifests (`.claude/.jotd-manifest.json`, `~/.config/jotd/global-manifest.json`) so upgrades never clobber hand-edited files; `init.sync_managed_files` is the shared core. `_template_files()` deliberately skips `templates/global/` — without that, `init --upgrade` would scaffold the global session command into every data dir (regression-tested, D11).
- `session_capture.py` — the SessionEnd scribe (see Session capture below).
- `author.py` / `sync.py` / `brief.py` — the team layer (see Team layer below).
- `templates/` — packaged assets (`[tool.setuptools.package-data]`) scaffolded into user data dirs; `templates/global/commands/jotd/session.md` is what `jotd install claude-code` copies to `~/.claude/commands/jotd/`.

**Single-writer discipline:** never add another writer to `inbox/`, `processed.log`, or `pulse-log.md`. In team mode this extends across machines: per-author inbox files are multi-machine-safe, everything else is written only on the librarian's machine (guarded in `cli.py::_librarian_gate`).

macOS-only pieces: `sched.py` (launchd, labels `com.jotd.pulse.*` + `com.jotd.sync.auto`, bootstraps into `gui/$UID` so headless runs use the login keychain — no API key on disk, D7), `notify.py`, and `contrib/screen-capture/`.

### Session capture (D11)

`jotd hook session-end` must never break a coding session: its whole body is wrapped in try/except and it always exits 0; every skip/reject/error is logged to `state/logs/session-hook.log` (silence is logged). **Two independent recursion breakers** prevent a fork bomb of headless claudes (the scribe's own `claude -p` fires SessionEnd too): the `JOTD_SESSION_HOOK=1` env guard and the cwd-is-data-dir skip — keep both if touching this code. Dedupe (detecting a session that already ran `/jotd:session`) reads tool_use blocks, not raw transcript text. The model only drafts; code enforces the fragment budget (max 6), the per-fragment char cap, and the 4096-byte line cap.

### Team layer (D12)

Per-machine author identity resolves ONLY in the CLI/hook layer (`author.py`; `--author` >
`$JOTD_AUTHOR` > `~/.config/jotd/author` > git user.name > OS user) and is passed down
explicitly — `author=None` keeps the legacy single-file inbox, which is what keeps library
callers and `evals/run_routing.py` machine-independent. Authored captures land in
`inbox/YYYY-MM.<author>.jsonl` (readers glob `*.jsonl` and must sort by record `ts`, never
filename). `sync.py` is conservative git: commit → pull --rebase → librarian-only
derive+commit → push; conflicts abort-and-tell, never auto-merge. `brief.py` is the read
side: `jotd hook session-start` prints a deterministic sub-4000-char brief to stdout for
context injection (prints on `startup`/`clear`, silent on `resume`/`compact` and on ANY
error). Both session hooks share the same two recursion breakers; the env guard constant
lives in `headless.py` and every jotd headless child must set it.

### Background propagation (D13) + repo-aware briefs (D14)

`autosync.py` composes `run_sync` — `sync.py` stays pure transport, no locks/notify/LLM
there. One tick = flock guard → sync → (librarian only, backlog ≥ `[sync]
organize_backlog`, no cooldown, no pulse in flight) headless `/organize` via
`headless.invoke_claude(..., permission_mode="acceptEdits")` → post-model code guards →
sync again. Every marker/lock lives under git-ignored `state/logs/` — `run_sync` does `git
add -A`, so anywhere else would get committed. The inbox guard is **append-aware**
(`new.startswith(old)`), never a blanket `git checkout -- inbox/` — a capture landing
mid-organize must survive; keep that if touching `_guard_inbox`. Conflicts notify once per
episode (marker file); failed organizes cool down 4h; `jotd sync --auto` always exits 0.
The headless organize child must carry BOTH recursion-breaker markers (env guard + cwd =
data dir). `brief.py`'s cwd focus (D14) is pure string matching against
`state/entities.json`; the no-match path must stay byte-identical to the unranked brief
(regression-tested).

### Evals

`evals/` lives outside `tests/` and is imported into pytest via `tests/conftest.py`. `evals/golden/` is a synthetic, deterministic `/organize` run with **three planted defects**; `tests/test_grader.py` asserts the grader still catches them — including that loop recall 8/9 = 0.889 correctly FAILS the 0.90 gate. Regenerate golden only via `evals/make_golden.py`. Tripwire (D8): add at most 2 loop-true fixtures per extension, or golden loop recall crosses the gate and the grader-honesty test stops biting.

## Conventions

- `DECISIONS.md` is the running decision log (D0–D14). Every non-obvious choice is recorded there; when you make one, append an entry. Early entries use the pre-rename `vault` names — they are records, not docs.
- User data-dir invariants (mirrored in `templates/CLAUDE.md`): the inbox is append-only; `state/` is derived/CLI-owned; notes are append/insert-only; never remove a `<!-- loop:… -->` stamp.
- Ruff: line-length 100, target py311, rules E/F/I/UP/B.
