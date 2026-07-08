---
description: Show today's daily brief (or preview one if the morning pulse hasn't run)
---

Show the user today's brief:

!vault log --brief

If that says no brief exists yet, preview one without sending anything:

!vault pulse --slot morning --dry-run

Relay the brief (or the dry-run preview) as-is — do not re-summarize it.
