#!/usr/bin/env bash
# Prove the pinned builder image produces byte-identical Wasm across two rebuilds.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SOURCE="${SOURCE_DIR:-$ROOT/examples/demo-contract}"
BUILDER_IMAGE="${BUILDER_IMAGE:-soroban-verify-builder:local}"
WORKDIR="$(mktemp -d)"
trap 'rm -rf "$WORKDIR"' EXIT

if ! command -v docker >/dev/null 2>&1; then
  echo "docker is required for builder reproducibility check" >&2
  exit 1
fi

if ! docker image inspect "$BUILDER_IMAGE" >/dev/null 2>&1; then
  echo "==> Builder image missing; building $BUILDER_IMAGE"
  docker compose -f "$ROOT/docker-compose.yml" --profile builder build builder
fi

build_once() {
  local out="$1"
  mkdir -p "$out"
  docker run --rm \
    -v "$SOURCE:/source:ro" \
    -v "$out:/output" \
    "$BUILDER_IMAGE" >/dev/null
  shasum -a 256 "$out/contract.wasm" | awk '{print $1}'
}

echo "==> Rebuilding $SOURCE twice in $BUILDER_IMAGE"
HASH_A="$(build_once "$WORKDIR/run-a")"
HASH_B="$(build_once "$WORKDIR/run-b")"

if [[ "$HASH_A" != "$HASH_B" ]]; then
  echo "FAIL: builder produced different wasm hashes" >&2
  echo "  run-a: $HASH_A" >&2
  echo "  run-b: $HASH_B" >&2
  exit 1
fi

echo "OK: reproducible wasm hash $HASH_A"
