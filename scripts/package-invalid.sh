#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${1:-$ROOT/examples/invalid-source.tar.gz}"

TMP=$(mktemp -d)
echo "This tarball intentionally has no Cargo.toml" > "$TMP/README.md"
tar -czf "$OUT" -C "$TMP" README.md
rm -rf "$TMP"

echo "Created invalid tarball: $OUT"
