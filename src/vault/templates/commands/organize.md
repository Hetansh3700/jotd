---
description: Process the inbox — librarian routes captures into notes, linker cross-links them
---

Process this vault's inbox in two passes:

1. Invoke the **librarian** subagent to route all unprocessed captures. Pass along nothing —
   it starts from `vault unprocessed --json` itself. Wait for it to finish.
2. If the librarian touched any notes, invoke the **linker** subagent and give it the list of
   note files the librarian reported touching.
3. Run `vault derive` to rebuild open-loops and the entity index.

Then summarize for the user in a few lines: captures processed, notes touched, loops opened,
anything sent to unsorted, and the derive counts.
