#!/usr/bin/env bash
# Hash a local wasm file (same digest used for on-chain comparison).
set -euo pipefail
WASM="${1:?Usage: hash-wasm.sh path/to/contract.wasm}"
shasum -a 256 "$WASM" | awk '{print $1}'
