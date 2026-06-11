#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
EXAMPLE="$ROOT/examples/mismatch-sample"
OUT="${1:-$ROOT/examples/mismatch-sample-source.tar.gz}"

cd "$EXAMPLE"
tar -czf "$OUT" \
  --exclude='target' \
  --exclude='.git' \
  Cargo.toml \
  contracts/

echo "Created mismatch tarball: $OUT"
tar -tzf "$OUT"
