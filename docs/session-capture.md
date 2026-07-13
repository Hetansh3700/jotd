# Capturing Claude Code sessions

Two ways to turn a Claude Code session into jotd captures — one pull, one push.
Both write through the same append-only `jotd capture` path as every other client,
with `source: claude-code`.

## Install

```bash
jotd install claude-code            # global /jotd:session command only
jotd install claude-code --hook     # + auto-capture when a session ends (opt-in)
jotd install claude-code --upgrade  # refresh unmodified files after a jotd update
jotd uninstall claude-code          # remove command files + hook; hand-edited files kept
```

Files land in `~/.claude/commands/jotd/` (available in every session); jotd's
bookkeeping manifest lives at `~/.config/jotd/global-manifest.json`. `--hook` merges
one `SessionEnd` entry into `~/.claude/settings.json` — idempotent, preserving
everything else in the file; a settings file that fails to parse is never touched.

## Manual: `/jotd:session`

Run it in any Claude Code session, in any repo. The main agent distills the
conversation into 0–6 atomic fragments (decisions + why, unresolved TODOs,
learnings, durable facts) and pipes each through
`jotd capture - --source claude-code … --method session`. Fragments name the
project and people in the text itself — routing keys off text; context is only
a hint. Nothing durable → nothing captured.

## Automatic: the SessionEnd hook

When a session ends, Claude Code runs `jotd hook session-end` with a JSON payload
on stdin (`session_id`, `transcript_path`, `cwd`, `reason`). The runner:

1. **Guards** (each skip is logged): scribe/pulse subprocess (`JOTD_SESSION_HOOK`
   env), `reason: clear`, unresolvable jotd dir, session ran *in* the jotd dir
   (recursion breaker), missing transcript, session already captured manually via
   `/jotd:session` (detected on Bash tool_use blocks, not raw text), fewer than 2
   real user messages.
2. **Digests** the transcript deterministically in Python — user/assistant text
   only, tool noise dropped, first user message + tail kept under a char budget.
3. **Asks the scribe** — one headless `claude -p` turn, no tools, cwd = the jotd
   data dir (the one directory trusted for headless runs) — for
   `{"captures": [{"text": …}]}`.
4. **Enforces in code** (the model only drafts): max 6 fragments, per-fragment
   char cap, and the 4096-byte serialized line cap — oversize fragments are
   rejected and logged, never truncated.
5. **Appends** survivors in-process via the same writer as every capture, with
   `context: {app: "Claude Code", title: <repo dir name>, method: "session-end"}`.

The hook never fails loudly: any error is logged and swallowed, exit code is
always 0 — a notes tool must never break a coding session.

## Where to look when something's off

```bash
tail ~/jotd/state/logs/session-hook.log   # every run: ok / skip / reject / error, with reasons
jotd unprocessed                          # captures waiting for the librarian
```

Tradeoff to know: the hook is synchronous — when it decides to run the scribe,
session exit waits for it (up to ~120s worst case, typically well under). A
detached runner is the documented future improvement. Sessions that end via
`/clear`, trivial sessions, and repeated ends of an already-captured session all
skip the scribe entirely, so the common case adds nothing.
