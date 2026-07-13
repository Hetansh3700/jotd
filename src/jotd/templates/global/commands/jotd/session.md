---
description: Distill this session into atomic jotd captures (decisions, TODOs, learnings)
allowed-tools: Bash(jotd capture:*)
---

Review THIS conversation and distill it into **0–6 atomic capture fragments** worth keeping
in the user's notes:

- **decisions made and why** (the why is the durable part)
- **unresolved TODOs / follow-ups** — phrase as a self-contained imperative
- **learnings and gotchas** (things that cost time and would again)
- **durable facts** discovered (constraints, credentials locations, quirks)

Skip routine mechanics: file edits, test runs, transient errors, anything derivable from
the repo's git history. If nothing durable happened, say so and capture nothing.

Rules for each fragment:

- Self-contained and ≤ ~600 characters — it will be read months from now, alone.
- **Name the project and any people in the text itself** (e.g. "jotd: decided X because Y").
  Routing keys off the text; the metadata below is only a hint.
- One `jotd capture` call per fragment, text piped via quoted heredoc (never argv):

```bash
jotd capture - --source claude-code --app "Claude Code" --title "$(basename "$PWD")" --method session <<'EOF'
<fragment text>
EOF
```

If jotd reports "not a jotd directory", tell the user to run `jotd init` first and stop.

When done, confirm in one short line: how many fragments were captured and their capture
ids as printed by the CLI. Do not organize anything now — the librarian does that later.
