#!/bin/bash
# Build the OCR helper (requires Xcode Command Line Tools: xcode-select --install).
# Native-arch by design: contrib builds from source on your machine.
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p bin
xcrun swiftc -O ocr.swift -o bin/vault-screen-ocr
echo "built bin/vault-screen-ocr ($(uname -m))"
