# jotd screen capture (Tier A)

Hotkey → drag a region → on-device OCR → your jotd inbox. The screenshot is
deleted the moment text is extracted; only text ever persists, and it goes
through `jotd capture` — the same tested append-only writer as every other
capture. This client never touches inbox files.

## Setup

```bash
cd contrib/screen-capture
./build.sh                        # needs Xcode CLT (xcode-select --install)
./jotd-screen-capture.sh         # first run: macOS prompts for Screen Recording
```

**Permissions (one-time):** `screencapture` needs Screen Recording granted to
whatever launches the script — Raycast, your terminal, or Shortcuts. macOS
prompts on first use. **Relaunch the launcher after granting** — a running
process does not pick up the new grant. That single grant also lets the OCR
helper read the frontmost window title; nothing else in the pipeline touches
permissions.

**Raycast:** add `contrib/screen-capture` as a Script Directory (the script
carries `@raycast` headers), then bind "Jotd Screen Capture" to a hotkey.
Works equally from Apple Shortcuts or a plain shell alias.

## What lands in the inbox

```json
{"id":"cap-…","ts":"…","text":"<ocr text>","source":"screen",
 "context":{"app":"Preview","title":"SSO-RFP.pdf","method":"region"}}
```

`context` reaches the librarian as a routing *hint* — the text is ground truth
(the routing eval's title-mislead fixture keeps that honest).

## Limits & troubleshooting

- **Captures are capped at 4 KB serialized.** jotd rejects (never truncates)
  oversized grabs and you get a notification — re-grab a smaller region.
- **Two-column PDFs:** the region selection is the column selector; grab one
  column at a time.
- **Password fields:** the OCR helper drops any line containing a bullet run or
  "password" followed by a masked run — note that Vision reads on-screen `••••`
  bullets as periods, which is why the password-context rule exists.
- **Window title may be missing** (some Electron apps report none) — the
  capture still lands, just without `title`.
- **Esc during region-select** is a silent no-op.
- **Capture shows only your wallpaper?** The launcher lacks Screen Recording:
  System Settings → Privacy & Security → Screen & System Audio Recording,
  enable it, then quit and relaunch the launcher. macOS may re-confirm this
  grant periodically.
- `./jotd-screen-capture.sh --json` prints the capture instead of saving it —
  used by `evals/capture/run_capture.py` to grade capture quality.
