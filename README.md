# jotd-by-claude

**A proactive notes brain for Claude Code.** Your notes work for you between the times you
look at them.

Every notes tool stores. A few retrieve well. None act. jotd captures fragments instantly,
has an agent organize them into an entity-linked notes directory, derives what's actually open — and
then **the pulse**, a scheduled headless Claude Code run, reads that state a few times a day
and decides whether anything deserves your attention. Under a hard interruption budget.
With every decision logged, **including the decisions to stay silent**.

> Status: v0.2 under construction — M0 (routing eval) → M4 (pulse core) built in this repo;
> M5 (calendar/email behaviors) and M6 (ship) tracked in the roadmap.

## Trust rules (non-negotiable)

- **The inbox is append-only.** Capture is a single `O_APPEND` write; agents are denied write
  access to it by Claude Code permission rules; the eval byte-compares it before/after.
- **The pulse never sends anything to another human.** It has read-only tools, full stop. It
  nudges *you* (macOS notification), it prepares, it drafts — you always fire the shot.
- **Silence is logged.** `state/pulse-log.md` records "considered X, suppressed because Y" for
  every candidate the pulse chose not to surface.

## How the quality gate works

- `evals/run_routing.py` — human-run LLM eval: 28 labeled captures through a real headless
  `/organize`, graded deterministically (routing ≥ 85%, loop recall ≥ 90%, inbox integrity
  100%). Results are committed to `evals/results/`.
- CI never spends tokens: it grades the committed golden run (which contains planted defects)
  and asserts the grader catches them. See DECISIONS.md D2.

## Development

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/pytest -q            # unit tests, no LLM
.venv/bin/ruff check .
python evals/run_routing.py    # the LLM product gate (requires claude login)
```

MIT.
