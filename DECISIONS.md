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
