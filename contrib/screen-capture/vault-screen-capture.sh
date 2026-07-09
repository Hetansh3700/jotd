#!/bin/bash
# Required parameters:
# @raycast.schemaVersion 1
# @raycast.title Vault Screen Capture
# @raycast.mode silent
#
# Optional parameters:
# @raycast.icon 🗃️
# @raycast.packageName Vault
#
# Documentation:
# @raycast.description Region-grab → on-device OCR → vault inbox (append-only)
#
# Also runnable from any terminal or hotkey tool; the @raycast headers are inert
# comments elsewhere. `--json` prints the capture-contract JSON instead of writing
# to the vault (used by evals/capture/run_capture.py).

set -u
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OCR="$DIR/bin/vault-screen-ocr"
JSON_MODE=0
[ "${1:-}" = "--json" ] && JSON_MODE=1

notify() {
    osascript -e 'on run argv' \
        -e 'display notification (item 1 of argv) with title "vault capture"' \
        -e 'end run' "$1" >/dev/null 2>&1
}

if [ ! -x "$OCR" ]; then
    notify "OCR helper missing — run contrib/screen-capture/build.sh"
    echo "helper missing: $OCR (run build.sh)" >&2
    exit 1
fi

WORK="$(mktemp -d)"
PNG="$WORK/grab.png"
trap 'rm -rf "$WORK"' EXIT

# Interactive region select. -x mutes the shutter sound. Esc leaves no file.
# The screenshot never leaves $WORK and is deleted on exit — only text persists.
ERR="$(screencapture -i -x "$PNG" 2>&1 || true)"
if [ ! -s "$PNG" ]; then
    if [ -n "$ERR" ]; then
        notify "capture failed — grant Screen Recording to your launcher, then relaunch it"
        echo "screencapture: $ERR" >&2
        exit 1
    fi
    exit 0 # user pressed Esc — silent no-op
fi

OUT="$("$OCR" "$PNG")" || {
    notify "OCR failed on the grab"
    exit 1
}

TEXT="$(printf '%s' "$OUT" | /usr/bin/python3 -c 'import json,sys; print(json.load(sys.stdin)["text"])')"
APP="$(printf '%s' "$OUT" | /usr/bin/python3 -c 'import json,sys; print(json.load(sys.stdin).get("app") or "")')"
TITLE="$(printf '%s' "$OUT" | /usr/bin/python3 -c 'import json,sys; print(json.load(sys.stdin).get("title") or "")')"

if [ -z "$TEXT" ]; then
    notify "no text found in the grab"
    exit 0
fi

if [ "$JSON_MODE" = 1 ]; then
    printf '%s' "$OUT" |
        /usr/bin/python3 -c 'import json,sys; d=json.load(sys.stdin); d["method"]="region"; print(json.dumps(d))'
    exit 0
fi

if ! ERRMSG="$(printf '%s' "$TEXT" | vault capture - --source screen \
    ${APP:+--app "$APP"} ${TITLE:+--title "$TITLE"} --method region 2>&1)"; then
    notify "vault rejected the capture: $ERRMSG"
    echo "vault capture: $ERRMSG" >&2
    exit 1
fi
# success is silent — the launcher's HUD is confirmation enough
