# This directory is a jotd directory — a proactive notes brain

You are working inside a personal notes directory managed by `jotd` (jotd-by-claude).
These conventions are load-bearing; agents and deterministic tooling both depend on them.

## The invariants

1. **`inbox/` is append-only.** Never edit, rewrite, or delete inbox files. New captures go
   through `jotd add "text"` (or the `/capture` command) — nothing else. Permission rules
   deny writes there; do not work around them.
2. **`state/` is derived or CLI-owned.** Never write anything in `state/` directly.
   `processed.log` is written only by `jotd mark-processed`; `open-loops.md`, `entities.json`
   are rebuilt by `jotd derive`; `pulse-log.md` is written only by the pulse runner and the
   feedback CLI (`jotd done|snooze|drop`).
3. **Notes are append/insert only.** Enrich, link, and add — never delete or rewrite a
   human's existing words. Fixing an obvious typo in something an agent wrote earlier is fine.

## Note format

Notes live in `notes/{people,projects,topics,meetings,journal}/<slug>.md` with YAML
frontmatter: `type`, `title`, `aliases` (list), `created`. Slugs are kebab-case
(`sarah-chen`). Two standing sections: `## Log` (dated one-liners, newest last, each citing
its capture id like `(cap-20260708-143205-3f2a)`) and `## Open loops`.

Open loops are checkbox lines stamped with an id comment:

    - [ ] send Sarah the Q3 numbers <!-- loop:cap-20260708-143205-3f2a -->

The stamp is how the pulse tracks a loop across days — never remove or reword the comment.
Mark a loop finished by flipping `[ ]` to `[x]` (or `jotd done <id>`), not by deleting it.
For a loop someone else owes, put `owner: <first-name>` at the end of the text, before the
stamp.

## Routing rules of thumb

- Prefer appending to an existing entity note (check `state/entities.json` and aliases)
  over creating a new one; create a new note when a person/project/topic clearly has none.
- A capture may fan out to several notes; record ALL of them in one
  `jotd mark-processed <id> <path,path>` call.
- `notes/topics/unsorted.md` is a legitimate destination for genuinely ambiguous fragments —
  routing there is correct behavior, not failure.
- Cross-link entities inline with `[[slug]]` wiki-links.
