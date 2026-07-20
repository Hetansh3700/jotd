# Team mode — shared memory for two (or a few) people and their agents

jotd's team layer turns one data dir into a shared brain: every capture carries an author,
machines sync over plain git, one machine organizes, and every new Claude Code session on
every machine starts with an injected brief of what the team knows. No server, no accounts —
a private git repo is the entire backend.

## The model

- **Inbox: multi-writer.** Each machine appends to its own `inbox/YYYY-MM.<author>.jsonl`,
  so concurrent captures never conflict under git.
- **Everything else: single-writer.** One designated machine — the **librarian** — runs
  `/organize`, `jotd derive`, and the pulse. The CLI refuses state-writing commands on other
  machines (exit 2, friendly message). `jotd done` still works anywhere: on a non-librarian
  machine it flips the note checkbox, which syncs and folds into state at the librarian's
  next derive.
- **Read: everywhere.** The SessionStart hook prints a deterministic brief (open loops with
  owners, who captured what recently, notes touched) that Claude Code injects into every new
  session's context, in any repo, on any machine. When the session's directory (its name or
  its git remote) matches a project note, the brief re-ranks around that project — a
  `focus:` header, that project's loops and routed captures first (D14; pure string
  matching, no LLM, unchanged output when nothing matches).

Deliberately deferred at this scale: permissions, privacy filtering, contested truth.
Conventions, not infrastructure.

## Day-1 setup (both founders)

On **each** machine:

```bash
pipx install jotd-by-claude          # or pip install
mkdir -p ~/.config/jotd
echo "<your-slug>" > ~/.config/jotd/author   # e.g. "het" / "dev" — MUST differ per person
jotd whoami                          # confirm the slug and where it came from
jotd install claude-code --hook      # /jotd:session + SessionEnd capture + SessionStart brief
```

On **one** machine (say the librarian's), create and share the data dir:

```bash
jotd init ~/jotd --set-default
# add the [team] table to ~/jotd/jotd.toml:
#   [team]
#   librarian = "<librarian-slug>"
# create a PRIVATE repo (GitHub/GitLab), then:
git -C ~/jotd remote add origin git@github.com:you/jotd-data.git
jotd sync
```

On the **other** machine:

```bash
git clone git@github.com:you/jotd-data.git ~/jotd
jotd init ~/jotd --set-default       # no-op scaffold + pointer file; existing files kept
jotd sync
```

## Zero-touch loop (recommended)

Turn the daily rhythm below into background infrastructure (D13). Once, in the shared
`jotd.toml` (it syncs, so this enables every machine):

```toml
[sync]
auto = true            # jotd schedule install adds the auto-sync job
interval_minutes = 15
organize_backlog = 5   # librarian: headless /organize when unprocessed >= 5
```

Then on **each** machine: `jotd schedule install`. Every machine gets a launchd job running
`jotd sync --auto` on the interval; the librarian's machine also gets the pulse slots, and
its auto-syncs run a headless `/organize` whenever the backlog crosses the threshold — then
sync again. capture → auto-sync → auto-organize → auto-sync, zero touch.

What the automation promises:

- **Conflicts notify once, then wait for you.** The first failing tick sends one macOS
  notification and later ticks stay quiet; resolve by hand and the next tick logs
  `recovered`. Never an auto-merge.
- **A broken organize can't burn tokens.** Any failed attempt sets a 4h cooldown
  (`state/logs/organize.cooldown`); plain syncing continues every tick throughout.
- **The inbox stays inviolate.** Inbox files are byte-snapshotted around the organize; any
  non-append change is restored from git and flagged. A capture landing mid-organize
  survives.
- Everything it does is one line per tick in `state/logs/sync-auto.log`; `jotd status`
  shows the last tick and warns on a standing conflict.

One prerequisite on the librarian machine: the data dir must be trusted for headless runs
(run `claude` inside it once — the same day-0 step the pulse needs, D7).

## Daily rhythm (manual mode)

- Capture from anywhere: `jotd add "..."`, `/jotd:session`, or let the SessionEnd hook do it.
- `jotd sync` whenever you want to publish/receive (the brief nags you when captures are
  sitting unsynced). On the librarian's machine, sync auto-runs `derive` after pulling, so
  pushed state is always fresh; `--no-derive` skips that.
- The librarian runs `/organize` when the backlog warrants it, then `jotd sync`.
- Everyone's next session starts with the brief. That's the whole loop.

## Sync semantics (what `jotd sync` actually does)

commit (if dirty) → `pull --rebase` → librarian-only `derive` + commit → push (one retry on
a push race). On a rebase conflict it aborts, leaves your commits safe locally, and tells you
to resolve by hand — it never auto-merges your notes. If it warns that the remote also
writes *your* author's inbox file, two machines share one slug: fix
`~/.config/jotd/author` on one of them.
