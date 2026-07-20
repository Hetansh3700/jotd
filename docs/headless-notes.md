# Headless & notification quirks (macOS)

Field notes from building and verifying the pulse on macOS. All verified on
claude CLI 2.1.205, macOS 15/26-era `launchd`.

## Workspace trust

Headless `claude -p` **ignores `permissions.allow` entries** from a workspace's
`.claude/settings.json` until you've accepted the trust dialog for that directory
(deny entries still apply — they are safe to honor). Two consequences:

- **Your jotd directory**: run `claude` interactively in the jotd directory once and accept the
  dialog. After that, scheduled pulse runs inherit the trust.
- **Throwaway dirs** (the eval harness): pass grants on the CLI instead —
  `--allowedTools "Bash(jotd unprocessed:*)" ...` — caller flags are honored regardless
  of workspace trust.

## launchd and keychain auth

`jotd schedule install` bootstraps plists into `gui/$UID`, the domain that owns your
login keychain — verified working: a `launchctl kickstart` pulse run authenticated and
completed headless with no extra setup. If your machine ever fails here (some MDM setups),
the fallback is an `ANTHROPIC_API_KEY` entry in the plist's `EnvironmentVariables` —
deliberately not the default (keychain auth means no key sitting in a plist on disk).

launchd does not run missed `StartCalendarInterval` jobs when the lid was closed; the next
slot catches up. The pulse is stateless per run, so this degrades gracefully. The auto-sync
job uses `StartInterval` instead: missed ticks are likewise skipped, the next fires after
wake, and one fires ~interval after bootstrap — a free sync-on-login.

## Auto-organize trust prerequisite

The backlog-triggered headless `/organize` (`jotd sync --auto` on the librarian machine,
D13) needs BOTH grant paths: the three `Bash(jotd …)` commands ride `--allowedTools` flags
(honored regardless of trust), but the librarian subagent's Edit/Write on notes flows
through `--permission-mode acceptEdits`, which needs the data dir **trusted interactively
once** — the same day-0 step the pulse already requires. A sync-only setup that skipped
that step will see every auto-organize fail (and cool down); run `claude` in the data dir
once and accept the dialog.

## Notifications

- `osascript display notification` (the zero-dep default) cannot render action buttons —
  that's why the nudge text itself carries the response verbs and loop id:
  `"send Sarah the Q3 numbers — jotd done|snooze|drop 3f2a99c1"`.
- Install `terminal-notifier` (`brew install terminal-notifier`) and jotd uses it
  automatically (better identity, groups replace stale nudges).
- The FIRST notification from a new sender triggers a macOS permission prompt (for
  osascript it's "Script Editor"). Approve it or every later notification is dropped
  silently — send yourself a test with
  `osascript -e 'display notification "test" with title "jotd"'` on day 0.
- Focus modes swallow notifications by design. The pulse-log is the source of truth for
  what was actually sent; the brief is the catch-up surface.

## Debugging a silent pulse

1. `jotd status` — shows the last heartbeat and warns past 36h.
2. `state/logs/pulse-<slot>.log` — launchd stdout/stderr of the runner itself.
3. `state/pulse-log.md` — heartbeats with `status=error err="..."` carry the exception.
4. `jotd pulse --now --dry-run` — full decision cycle, nothing sent, printed to stdout.

## Debugging a silent auto-sync

1. `jotd status` — `last auto-sync:` line plus a WARNING while a conflict marker exists.
2. `state/logs/sync-auto.log` — one structured line per tick (`ok`, `skip`, `conflict`,
   `organize-ok`, `organize-error`, `organize-skip`, `guard`, `recovered`) AND the plist's
   stdout/stderr redirect, so interpreter tracebacks interleave in the same file.
3. `launchctl print gui/$UID/com.jotd.sync.auto` — is the job loaded at all?
4. A failed organize writes `state/logs/organize.cooldown` (4h); delete it to retry now.
