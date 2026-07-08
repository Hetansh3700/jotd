# DECISIONS

Running log of choices made during the build, per the v0.2 spec ("if a decision isn't
specified, pick the simplest option that satisfies the acceptance criteria and note it here").

## D0 — Step-0 verification (2026-07-08)

Verified against the installed tooling before writing code:

- **claude CLI 2.1.205, headless**: `claude -p "/pingcheck"` from a directory containing
  `.claude/commands/pingcheck.md` executes the project slash command (returned the sentinel
  exactly), so `/organize` and the pulse can be driven headless. `--output-format json` yields an
  envelope with `result`, `is_error`, `num_turns`, `modelUsage` (incl. `costUSD`).
  `--agents`, `--allowedTools`, `--append-system-prompt`, `--max-turns`, `--model`,
  `--permission-mode` all exist.
- **PyPI**: `vault` is taken → dist name is **`vault-brain`**, import package `vault`,
  CLI `vault` (same split as roster's `roster-mcp`/`roster`). `vault-brain` returned 404
  (free) on 2026-07-08.
- **Binary collision**: no `vault` on this machine's PATH today, but HashiCorp Vault is a real
  collision risk for users — `vault init` will warn when `which -a vault` finds a foreign binary
  ahead of ours.

## D1 — The inbox is JSONL, not markdown

One line = one capture makes the append-only invariant structurally safe (no in-file edit is
ever meaningful), makes "unprocessed" a set difference over ids, and makes eval fixtures
format-identical to real captures. Human readability lives in `notes/`; the inbox is a log,
not a document. Oversize captures (> 4096 bytes serialized) are rejected, never truncated —
truncation corrupts provenance (same rule as roster D2).

## D2 — The LLM eval is human-run; CI gates the grader against a committed golden run

roster's eval gate is pure-local (embeddings) so it lives in CI. vault's routing *is* LLM
behavior — auth, dollars, nondeterminism — so `evals/run_routing.py` is a human-run product
gate (like roster's `bench/`), its results committed to `evals/results/`. What CI *does* gate:
`tests/test_grader.py` grades `evals/golden/` — a synthetic, deterministic /organize run with
**three planted defects** (two misroutes, one missed loop stamp) — and asserts exact metrics,
including that the loop-recall gate correctly FAILS on it. The grader cannot rot, and a grader
that stops detecting failures breaks CI. Golden is regenerated only via `evals/make_golden.py`
(fixed timestamps; zero clock/LLM dependence).

## D3 — Glob targets never match `topics/unsorted`

Fixture expectations support globs ("people/*" = librarian should create/route to *some*
person note). Carve-out: a glob never matches `topics/unsorted.md`, otherwise "route somewhere
real in this category" and "correctly give up" would be indistinguishable classes and dumping
everything in unsorted would game the eval. Exact-target `topics/unsorted` expectations (the
ambiguous class) still work.

## D4 — Grader leniency in v0.2: extra routed paths allowed, loop owner not graded

Over-linking (routing a capture to more files than expected) is not penalized — fan-out
judgment varies legitimately and the cost of extra links is low. Loop `owner` labels are in the
fixtures (documentation + future use) but not graded: owner extraction is a text convention the
librarian applies, and grading it would be brittle before the convention has dogfood mileage.
Revisit both with eval data in v0.3.

## D5 — The interruption budget lives in code; the model only reasons inside it

The runner computes `min(per_run, per_day − already_sent_today)` from the pulse-log BEFORE
invoking the model, pre-filters silenced (two drops) and snoozed loops out of the packet
(the model structurally cannot renudge what it never sees), then hard-truncates the model's
nudges to the budget and rejects hallucinated/duplicate loop ids — runner rejections are
logged as `suppress ... reason="runner: ..."` lines, so even the enforcement layer's
decisions are auditable. The prompt restates the budget only so the model's suppression
reasoning reads coherently.

## D6 — pulse-log.md is a one-line-per-event grammar with a round-trip write guard

The spec's headline artifact ("an agent that logs why it chose silence") must be readable
raw AND machine-foldable. One event per line, strict regex grammar, `pulselog.py` is the
sole writer via O_APPEND; free text is sanitized (quotes→apostrophes, newlines flattened)
and every event is re-parsed before it is appended — an unparseable event raises instead of
corrupting the log. Loop status (done/snoozed/silenced) is always FOLDED from events at
derive time, never stored, so the log is the single source of truth.

## D7 — launchd headless auth: verified, keychain-backed, no API key on disk (2026-07-08)

`vault schedule install` bootstraps into `gui/$UID` (the login-keychain domain);
a `launchctl kickstart` of the morning slot ran the full pulse — claude auth, model call,
brief written, notification delivered — with zero extra configuration. The
`ANTHROPIC_API_KEY`-in-plist fallback stays documented but off by default. Also verified:
headless claude ignores workspace `permissions.allow` in untrusted dirs (denies still
apply), so the eval harness grants the vault CLI via `--allowedTools` flags and real users
accept the trust dialog once (docs/headless-notes.md).
