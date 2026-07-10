# The 7-day dogfood protocol (M4 exit gate)

The pulse ships when it survives a week of real use without getting muted. That is the
whole test — the spec's "muting test". Run it on your real jotd directory, not a fixture.

## Setup (day 0)

```bash
pipx install jotd-by-claude          # or: pip install -e . from the repo
jotd init ~/jotd
cd ~/jotd && claude              # accept the workspace trust dialog once (headless runs need it)
jotd schedule install
```

Wire a capture hotkey (docs/hotkeys.md). Capture relentlessly; run `/organize` in a Claude
Code session in the jotd directory once a day or whenever the backlog itches.

## Daily (2 minutes)

1. Respond to every nudge honestly: `jotd done|snooze|drop <id>` — the id is in the
   notification text. Don't perform for the agent; drop what you'd really ignore.
2. Skim the brief when it arrives. Note whether you'd have missed anything without it.
3. In the evening, grade each nudge you received in a row of the table below.

| date | nudge | justified? (would a sane assistant have interrupted you for this?) |
|------|-------|--------------------------------------------------------------------|

## Exit criteria (after day 7)

- **≤ 1 unjustified nudge per day** by your own table.
- **≥ 1 correct suppression** in `state/pulse-log.md` — a "considered X, suppressed
  because Y" line where Y was right and a nudge would have annoyed you.
- **Zero inbox mutations**: `git -C ~/jotd log --follow inbox/` shows only appends
  (or byte-compare a day-0 copy).
- **Zero missed heartbeats**: `grep heartbeat state/pulse-log.md` shows 3 lines per day
  (ok, error, or skipped — silence is the only failure).
- The 14-day extension: you still haven't run `jotd schedule uninstall`, and your nudge
  act-rate (`done` + genuinely-acted / total) is above 50%.

If a criterion fails, tune `jotd.toml` (or the pulse agent prompt) and note WHY in
DECISIONS.md before restarting the clock.
