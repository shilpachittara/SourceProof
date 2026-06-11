#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
EXAMPLE="$ROOT/examples/hello-world"
OUT="${1:-$ROOT/examples/hello-world-source.tar.gz}"

cd "$EXAMPLE"
# Include Cargo.lock so the verifier rebuild resolves the EXACT same dependency
# versions used at deploy time (otherwise cargo picks newer crates → mismatch).
LOCK=()
[[ -f Cargo.lock ]] && LOCK=(Cargo.lock)
tar -czf "$OUT" \
  --exclude='target' \
  --exclude='.git' \
  Cargo.toml \
  "${LOCK[@]}" \
  contracts/

echo "Created tarball: $OUT"
tar -tzf "$OUT"
