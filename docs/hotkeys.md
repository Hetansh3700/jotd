# Instant capture from anywhere on macOS

The design goal: capture must cost under two seconds and zero context switches.
`vault add` is a single append — wire it to whatever launcher you already use.
No daemon, no app, no clipboard watcher.

## Raycast (recommended)

Create a Script Command (`Raycast → Create Script Command`):

```bash
#!/bin/bash
# @raycast.schemaVersion 1
# @raycast.title Vault Capture
# @raycast.mode silent
# @raycast.argument1 { "type": "text", "placeholder": "capture..." }
export PATH="$HOME/.local/bin:/opt/homebrew/bin:$PATH"
vault add "$1"
```

Bind it to a hotkey in Raycast settings. `mode silent` closes the window on Enter.

## Apple Shortcuts

Shortcuts → New → add **Ask for Input** (Text) → add **Run Shell Script**:

```bash
export PATH="$HOME/.local/bin:/opt/homebrew/bin:$PATH"
vault add "$(cat)"
```

with "Pass Input: to stdin". Then Settings → assign a keyboard shortcut, or add it
to the menu bar.

## Terminal

`vault add "the thing"` — or pipe: `pbpaste | vault add -`. Add an alias if you
like (`alias v="vault add"`).

## Inside Claude Code

`/capture the thing` in any session running in your vault directory.
