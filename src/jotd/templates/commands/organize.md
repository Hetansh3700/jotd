---
description: Process the inbox — librarian routes captures into notes, linker cross-links them
---

Process this jotd directory's inbox in two passes:

1. Invoke the **librarian** subagent to route all unprocessed captures. Pass along nothing —
   it starts from `jotd unprocessed --json` itself. Wait for it to finish.
2. If the librarian touched any notes, invoke the **linker** subagent and give it the list of
   note files the librarian reported touching.
3. Run `jotd derive` to rebuild open-loops and the entity index.

Then summarize for the user in a few lines: captures processed, notes touched, loops opened,
anything sent to unsorted, and the derive counts.

If any jotd command refuses because this machine is not the librarian (team mode), stop
immediately and tell the user — do not work around the guard or edit state files directly.
