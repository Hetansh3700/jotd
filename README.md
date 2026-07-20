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

## How it works

The loop is **capture → organize → derive → pulse**:

1. **Capture** — `jotd add "…"` appends one line to the inbox. A single `O_APPEND` write, so
   it's instant and never summarized on the way in.
2. **Organize** — `/organize` in a Claude Code session routes each capture into the right note
   (the *librarian* agent), cross-links entity mentions as `[[wiki-links]]` (the *linker*), then
   rebuilds derived state.
3. **Derive** — `jotd derive` deterministically rebuilds `state/` from your notes: stamps every
   `- [ ]` checkbox with a stable **loop** id and computes what's open, stale, snoozed, or done.
4. **Pulse** — on a schedule, a headless `claude` run reads the current state and decides what,
   if anything, is worth surfacing right now — then delivers it as a macOS notification.

The load-bearing split: **the LLM decides meaning and judgment; deterministic Python owns all
state, aggregates, and the interruption budget.** The budget can't be prompted around — code
enforces it after the model answers.

Everything lives in plain files under a jotd directory (default `~/jotd`):

```
~/jotd/
  jotd.toml                    # config: budgets, model, slot times
  inbox/YYYY-MM[.<author>].jsonl   # append-only raw captures, one JSON line each
  notes/{people,projects,topics,meetings,journal}/<slug>.md   # your notes
  state/                       # DERIVED from notes + logs (open-loops, entities, pulse-log, briefs)
  .claude/{agents,commands,settings.json}   # the Claude Code agents + permission rules
  CLAUDE.md                    # conventions the agents depend on
```

## Requirements

- **Python ≥ 3.11**
- **The `claude` CLI**, installed, on your PATH, and logged in — required for `/organize`,
  `/recall`, and the pulse (they shell out to a headless `claude` run; no API key needed).
- **macOS** for the proactive pieces: launchd scheduling, notifications, and the optional
  screen-capture OCR client. The core (capture, organize, derive) is cross-platform.

## Install

From source (PyPI release coming):

```bash
git clone https://github.com/Hetansh3700/jotd.git
cd jotd
pipx install .            # or: pip install -e .
```

Once published, `pipx install jotd-by-claude` — coming soon.

## Setup (first run)

```bash
jotd init ~/jotd                 # scaffold the folder, agents, and config
cd ~/jotd && claude              # accept the workspace trust dialog once (headless runs need it)
osascript -e 'display notification "test" with title "jotd"'   # approve the macOS notif prompt
jotd schedule install            # install the 3×/day pulse (launchd)
jotd install claude-code         # optional: /jotd:session in every Claude Code session
                                 #   add --hook to auto-capture sessions when they end
                                 #   and inject a team brief when they start
```

Two manual gates matter — each silently breaks the pulse if skipped:

- **Workspace trust:** run `claude` interactively once inside the jotd directory and accept the
  trust dialog. Scheduled pulses inherit it.
- **Notification permission:** send one test notification so macOS's first-notification prompt
  is approved, or later nudges are dropped without warning.

## Usage

**Capture** — instant, from anywhere (bind it to a hotkey):

```bash
jotd add "email Sarah the Q3 numbers"
pbpaste | jotd add -             # pipe from clipboard / stdin
```

**Organize** — run inside your jotd directory in a Claude Code session:

```
/organize                        # librarian routes → linker links → jotd derive
```

**Capture a Claude Code session** — after `jotd install claude-code`, in ANY repo's session:

```
/jotd:session                    # distill this session into atomic captures
```

With `--hook`, sessions are also auto-distilled when they end (skipping trivial ones,
`/clear`, and sessions you already captured manually). Every decision is logged to
`state/logs/session-hook.log`. See [docs/session-capture.md](docs/session-capture.md).

**Respond to nudges** — the loop id is in the notification text:

```bash
jotd done <id>                   # mark done (also flips [ ] → [x] in the note)
jotd snooze <id> --days 5        # stay quiet until then (default: jotd.toml snooze_days)
jotd drop <id>                   # two drops silence the loop permanently
```

**Check in / trigger manually:**

```bash
jotd status                      # inbox backlog, open loops, last heartbeat, schedule health
jotd log                         # tail the pulse log (nudges + suppressions); -n N for more
jotd log --brief                 # today's daily brief
jotd pulse --now                 # run a pulse right now (budget still applies)
jotd pulse --now --dry-run       # decide, print what it would do, send/log nothing
```

**Slash commands** (available in a Claude Code session inside the jotd directory):

| Command | Does |
|---|---|
| `/capture <text>` | Append a raw capture to the inbox |
| `/organize` | Route the inbox into notes, cross-link, and re-derive |
| `/pulse` | Run a pulse now and show its reasoning (including suppressions) |
| `/daily` | Print today's brief (or a morning dry-run preview) |
| `/recall <question>` | Answer from your notes, with citations |
| `/jotd:session` | Distill the current session into captures (global — works in any repo) |

## Team mode

Point two (or a few) machines at one shared jotd directory backed by a private git repo and
it becomes a shared brain: every capture carries an author, machines sync over plain git, one
machine organizes, and every new Claude Code session on every machine starts with an injected
brief of what the team knows. No server, no accounts.

- **Inbox: multi-writer.** Each machine appends to its own `inbox/YYYY-MM.<author>.jsonl`, so
  concurrent captures never conflict under git. Author identity resolves per machine:
  `--author` > `$JOTD_AUTHOR` > `~/.config/jotd/author` > git `user.name` > OS user.
- **Everything else: single-writer.** One machine — the **librarian** (set `[team] librarian`
  in `jotd.toml`) — runs `/organize`, `jotd derive`, and the pulse. State-writing commands
  refuse to run elsewhere. `jotd done <id>` still works anywhere: on a non-librarian machine it
  flips the note checkbox, which syncs and folds into state at the librarian's next derive.
- **Read: everywhere.** The SessionStart hook injects a deterministic brief (open loops with
  owners, who captured what recently, notes touched) into every new session, on any machine.

```bash
jotd whoami                      # print this machine's author slug and how it resolved
jotd sync                        # commit → pull --rebase → (librarian: derive) → push
jotd sync --no-derive            # skip the librarian's auto-derive on this sync
```

`jotd sync` never auto-merges your notes: on a rebase conflict it aborts and leaves your
commits safe locally for you to resolve by hand. See [docs/team.md](docs/team.md) for the
full two-machine setup.

## Concepts

- **capture / inbox** — a raw fragment appended to an append-only JSONL inbox; never edited.
- **loop** — an actionable open item, a `- [ ]` checkbox in a note stamped with a stable id.
- **pulse** — the scheduled, read-only Claude run that judges what deserves your attention now.
- **interruption budget** — a hard cap on nudges (default 3/run, 6/day), enforced in code.
- **suppression** — a candidate the pulse chose *not* to surface, logged with its reason.
- **daily brief** — the morning-slot summary of "worth knowing" items (`jotd log --brief`).
- **author** — the per-machine slug stamped on each capture; scopes the inbox file so machines
  never collide (team mode).
- **librarian** — the single machine authorized to organize, derive, and pulse for a shared dir.

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

## License

MIT — see [LICENSE](LICENSE). © 2026 Hetansh Patel.
