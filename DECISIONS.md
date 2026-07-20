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

## D8 — Screen-capture metadata entered the eval before the client existed (2026-07-08)

Fixtures may now carry `source` and `context` ({app, title, method}); the harness passes
both through `append_capture` verbatim and the golden generator mirrors them in
`new_capture` key order (golden inbox integrity is a byte comparison). The grader never
reads `context` — metadata rides only the integrity check; routing is graded on where
text landed. **Tripwire: at most 2 loop-true fixtures may be added per extension** —
golden loop recall must stay under the 0.90 gate for the grader-honesty test to keep
biting (8/9 = 0.889 fails ✓; a 9/10 extension flips CI). The librarian prompt was NOT
changed: on the first 37-fixture run both probes passed — the hint-follow fixture routed
a generic capacity plan to atlas via its title, and the title-mislead fixture followed
the text to atlas over a #helios-launch window title. 36/37 routing, 9/9 loop recall.
Fixture texts are synthetic but noise-modeled (UI chrome, OCR hyphenation, dot-leaders);
capture-quality ground truth belongs to evals/capture/, not this set.

## D9 — Tier A screen capture: the TCC-minimal pipeline, and two OCR field findings (2026-07-08)

The client is `screencapture -i` → one-shot Swift Vision helper → `vault capture` — the
helper never requests any permission. The only TCC prompt in the pipeline belongs to
Apple's own screencapture binary, attributed to the launcher (Raycast/Terminal); the
helper inherits that grant for window-title reads (CGWindowList silently omits names
when ungranted — it never prompts), Vision-on-a-file and NSWorkspace need nothing. So
none of the noteit traps apply: no embedded Info.plist, no NSApplication bootstrap, no
CGPreflight tri-state. Verified live: window capture by id → 1,464 chars OCR'd with
correct app/title attribution; pulse run + 20 parallel `vault capture` subprocesses →
append-only inbox, 20 unique ids, zero torn lines.

Field findings baked into the code:
1. **Vision reads on-screen password bullets (••••) as PERIODS.** A bullet-character
   regex alone never fires on real OCR output, and bare dot-runs can't be dropped
   (terminal dot-leaders are content) — redaction drops lines with literal bullet runs
   OR "password" followed by any masked run ([•●.*]{4,}).
2. **Text on a transparent background OCRs as blank** (composited on black). The helper
   flattens alpha onto white before recognition; the committed two-col.pdf asset draws
   an explicit white page fill for the same reason.

## D10 — Renamed: vault → jotd-by-claude / jotd (2026-07-09)

Full rename, no compatibility shims (pre-release, single dogfooder): dist `vault-brain` →
**`jotd-by-claude`**, import package and CLI `vault` → **`jotd`**, and every derived
identifier — `JOTD_DIR`, `jotd.toml`, `~/.config/jotd/dir`, default data dir `~/jotd`,
launchd labels `com.jotd.pulse.*`, manifest `.claude/.jotd-manifest.json`, notification
title/group `jotd`, `jotd-screen-capture.sh` / `jotd-screen-ocr`. Prose swept too: the data
dir is a "jotd directory", not a "vault". Earlier entries in this log keep the old names —
they are records, not docs. The D0 HashiCorp binary collision is moot with a CLI named
`jotd`; the init-time PATH shadow check stays, generalized to warn about any foreign `jotd`
binary (stale installs). two-col.pdf was regenerated (byte-deterministic generator) because
its sample text named the old product. Verify `jotd-by-claude` is free on PyPI before the
first publish.

## D11 — Session capture: global /jotd:session command + opt-in SessionEnd hook (2026-07-13)

Claude Code sessions become a capture source, both pull and (opt-in) push. `jotd install
claude-code` installs `templates/global/commands/jotd/session.md` into
`~/.claude/commands/jotd/` — available in every CC session — reusing init's sha256-manifest
loop (extracted as `init.sync_managed_files`). The manifest lives at
`~/.config/jotd/global-manifest.json`: jotd bookkeeping stays out of `~/.claude`. The
walker in `_template_files()` skips `templates/global/` — without that exclusion the rglob
would scaffold `session.md` into every data dir on `init --upgrade` (regression-tested).

Decisions that matter:

1. **The manual path is a command file, not an agent.** A subagent never sees the parent
   conversation; only the main agent can distill its own session. It pipes each fragment
   via quoted heredoc into `jotd capture - --source claude-code` — argv quoting is a trap,
   stdin is the contract (same as the screen client). Zero CLI changes: `source` is
   free-form and `{app,title,method}` fit (`app: Claude Code`, `title: <repo dir>`,
   `method: session` manual / `session-end` hook).
2. **The hook never fails and never truncates.** `jotd hook session-end` wraps its whole
   body in try/except and exits 0 unconditionally — a notes tool must never break a coding
   session. Model output is drafted only: code enforces the fragment budget (max 6), the
   per-fragment char cap, and the 4096-byte line cap (reject, log, continue — D1). Every
   skip/reject/error is logged to `state/logs/session-hook.log` (silence is logged — same
   posture as the pulse).
3. **Two independent recursion breakers.** The scribe's own `claude -p` (and the pulse's)
   fire SessionEnd too: the scribe subprocess carries `JOTD_SESSION_HOOK=1` in its env,
   and any session whose cwd is the data dir is skipped. Either alone would suffice;
   both are cheap and the failure mode (fork bomb of headless claudes) is expensive.
4. **The scribe gets a digest, not tool access.** Python compacts the transcript JSONL
   (user/assistant text only, tool noise dropped, first-user-message + tail under a char
   budget) and the scribe runs with no tools, one turn, cwd = the data dir — the only
   directory known to be trusted for headless runs (D7).
5. **Dedupe reads tool_use blocks, not raw text.** A session that already ran
   `/jotd:session` (a Bash tool_use whose command contains `--source claude-code`) is
   skipped; matching raw transcript text would false-positive on any session that merely
   read or edited files mentioning the command (e.g. working on jotd itself).
6. **settings.json is merged, never clobbered.** `--hook` parses `~/.claude/settings.json`,
   appends one SessionEnd entry (idempotent by marker substring, `timeout: 120` — the
   scribe needs ~60s and CC's default would kill it), and preserves every unknown key.
   Unparseable settings abort the merge untouched. Uninstall removes only entries matching
   the marker and only files whose hash still matches the manifest.

## D12 — Team layer: authorship, git sync, single librarian, SessionStart brief (2026-07-19)

The team layer makes one data dir shared memory for n≈2 people and their agents: captures
carry authors, machines sync over plain git, one machine organizes, and a SessionStart hook
injects a deterministic brief into every new CC session (the read-side twin of D11's
SessionEnd scribe). Permissions, privacy filtering, contested truth, CRDTs/servers are
deliberately deferred — conventions instead of code at this scale.

Decisions that matter:

1. **Author identity is per-machine and never lives in jotd.toml.** jotd.toml is committed
   and synced, so "who am I" cannot live there. Resolution: `--author` flag > `$JOTD_AUTHOR`
   > `~/.config/jotd/author` (the canonical setup) > slugified `git config user.name` > OS
   username > `"user"`; any layer that slugs to empty falls through. Resolution happens ONLY
   in the CLI/hook layer and is passed down explicitly — `author=None` keeps the legacy
   single-file inbox, so library callers and the eval harness are untouched. `jotd whoami`
   prints the slug AND the rule that resolved it, because slug collisions (two machines,
   one identity) reintroduce exactly the file conflicts per-author files eliminate; `jotd
   sync` additionally warns when a pull changes your own author's inbox file.
2. **Record carries `author` (provenance); filename carries it too (conflict isolation).**
   `inbox/YYYY-MM.<author>.jsonl` keeps concurrent machines out of each other's way under
   git; readers group/sort by record fields, never filename (filename order is
   author-lexicographic, not chronological). Slug contract in formats.py: `[a-z0-9-]`, ≤32.
3. **Single-librarian is a guard, not auth.** With `[team] librarian` set, mark-processed,
   derive, pulse, snooze, drop, and `schedule install` exit 2 on non-librarian machines
   (schedule especially — an installed launchd pulse would otherwise fail 3× daily forever).
   `done` instead degrades to a checkbox flip: notes are the shared human layer, and derive
   already folds `[x]` into status=done, so loop state still crosses machines with zero new
   writers of pulse-log.md (D6 intact). Solo mode (no `[team]`) is byte-for-byte unchanged.
4. **`jotd sync` is conservative git, nothing more.** commit → pull --rebase → librarian-only
   derive+commit → push (`-u` on first, exactly one retry on a push race). Empty remote is
   fine; a rebase conflict aborts and tells the user their commits are safe locally — never
   auto-merge notes. Identity fallback (`-c user.email=<author>@jotd.invalid`) so a machine
   without git identity can still commit. On the librarian machine sync auto-derives after
   pull (--no-derive to skip) so pushed state is as fresh as the last sync.
5. **The brief is deterministic Python, and the start hook prints or shuts up.** Composed
   from open-loops.json (stale-first), last-3-days captures grouped by record author,
   processed.log activity, and a fresh daily brief pointer; hard 4000-char budget enforced
   by dropping whole lines (D5). `jotd hook session-start` prints on `startup` and `clear`,
   skips `resume`/`compact` (context already has a brief), and on ANY error or skip prints
   nothing and exits 0 — same posture as D11, except the success path must write stdout
   (that is how SessionStart context injection works). Same two recursion breakers as D11;
   the pulse's headless child now also carries JOTD_SESSION_HOOK=1 (it previously relied on
   the cwd skip alone), with the guard constant moved to headless.py.
6. **`--hook` installs both halves of the loop.** SessionEnd (timeout 120) and SessionStart
   (timeout 10) as separate marker-matched entries; rerunning on an old SessionEnd-only
   install adds the start hook idempotently; uninstall removes both and nothing else.

## D13 — Background propagation: auto-sync + backlog-triggered auto-organize (2026-07-20)

D12 made shared memory possible; every hop was still human-triggered (`jotd sync` per
machine, `/organize` on the librarian's). D13 makes propagation automatic: a
`com.jotd.sync.auto` launchd job (StartInterval, default 15 min) runs `jotd sync --auto` on
every machine; on the librarian's machine an auto-sync additionally runs a headless
`/organize` when the unprocessed backlog reaches `[sync] organize_backlog`, then syncs
again. capture → auto-sync → auto-organize → auto-sync, zero touch. The D5 split holds:
the model only routes notes; code owns the schedule, thresholds, locks, guards, recovery.

Decisions that matter:

1. **`sync.py` stays pure transport; the runner is `autosync.py`.** Flock overlap guard,
   logging, notification, the LLM call, and all recovery live in the new module —
   composing `run_sync`, never modifying it. `jotd sync --auto` prints nothing and always
   exits 0 (launchd throttles failing jobs; retry semantics are ours).
2. **Every new on-disk artifact lives under git-ignored `state/logs/`** — `run_sync` does
   `git add -A`, so a lock or marker anywhere else would get committed and synced. Files:
   `sync-auto.log` (structured log AND the plist's Std{Out,Err}Path — the module prints
   nothing, so launchd's redirect only ever captures tracebacks, one file to debug),
   `.sync-auto.lock`, `sync-auto.conflict`, `organize.cooldown`.
3. **Conflicts notify once per episode.** First failing tick sends one notification and
   writes the conflict marker; later ticks log only ("still failing"); the next clean sync
   clears the marker and logs `recovered`. `run_sync` already refuses to run mid-rebase, so
   ticks are inert until the human resolves. Unknown exceptions never notify (no notify
   loops) — they log, and the launchd redirect has the traceback.
4. **The headless organize is the eval harness's proven recipe via the shared invoker.**
   `headless.invoke_claude` gained `permission_mode` (the one missing flag);
   `/organize` runs with `acceptEdits`, `--allowedTools` for the three jotd Bash commands,
   `disallowed_tools=()`, max-turns 250, and both recursion-breaker envs. Trust
   prerequisite (D7) unchanged: the librarian's data dir is trusted interactively once.
5. **Post-organize guards are append-aware, not blunt.** Inbox files are snapshotted
   before the run; afterwards `new.startswith(old)` passes (a legit capture landing
   mid-organize survives), anything else is restored from git (lossless — sync #1 committed
   moments ago) with a log + notification; new inbox files survive only if every line
   parses as a capture (month rollover). Rejected: blanket `git checkout -- inbox/`, which
   would destroy concurrent captures.
6. **Failure is cheap and bounded.** Organize failure (or a run where the backlog didn't
   decrease — mark-processed never ran) writes a 4h cooldown marker so a broken organize
   can't burn a 40-minute timeout every 15 minutes; partial progress still ships (append-only
   artifacts are valid at any prefix, sync #2 re-derives IN CODE and pushes). A pulse
   in flight skips organize (flock on `.pulse.lock`), never waits.
7. **`schedule install` is now per-machine-aware.** Pulse jobs install only where they can
   run (solo or librarian — D12.3's rationale intact); the sync job installs anywhere
   `[sync] auto = true`, and is skipped with a message when the dir has no git repo or no
   origin. Nothing installable on a non-librarian machine still exits 2. `[sync]` lives in
   the committed jotd.toml, so enabling auto once propagates to every machine by itself.

## D14 — Repo-aware briefs: deterministic cwd focus (2026-07-20)

The SessionStart brief was global — the same 4000 chars whether you opened the repo the
team is heads-down on or an unrelated scratch dir. D14 ranks it around the project the
session is in, still with zero LLM at session start (D5): `build_brief` takes the hook's
`cwd` and re-orders — never adds — content when a deterministic match is found.

Decisions that matter:

1. **Focus tokens come from two places only:** the slugified cwd basename, then the origin
   remote's repo name (same 5s-timeout, None-on-failure `_git` posture as the header bits).
   Both reuse `author.slugify` — one slug alphabet everywhere.
2. **Matching is string comparison over sorted inputs, in a fixed priority.** Candidates
   come from `state/entities.json` (fallback: `notes/projects/*.md` stems when derive has
   never run); `type == "project"` entities beat all others; per pool: exact slug > exact
   slugified alias > containment either direction with the shorter side >= 4 chars (kills
   `api`-grade noise); containment ties break longest-slug-then-lexicographic.
3. **"Boost" is a stable re-sort, never new content.** Loops on the focus note float as a
   block (stale-first preserved within tiers), the focus note leads "notes touched", and
   captures ROUTED to the focus note (per processed.log) displace the newest-3 default
   within their author group. Rejected: matching capture TEXT — deterministic but hopelessly
   noisy (the project name appears in most captures), and unprocessed captures have no
   routing to match anyway. All caps and the char budget unchanged.
4. **No match ⇒ byte-identical output.** cwd absent, tokens empty, or nothing matched means
   every focus-gated branch is skipped and the brief is literally `==` the unranked one —
   regression-tested, so the ranking can never drift the default.
