#!/usr/bin/env bash
# Create all sample tarballs (no deploy).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
"$ROOT/scripts/package-example.sh"
"$ROOT/scripts/package-mismatch.sh"
"$ROOT/scripts/package-invalid.sh"
echo "Samples ready under examples/*.tar.gz"
