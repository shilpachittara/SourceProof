#!/usr/bin/env bash
set -euo pipefail

# /source is mounted read-only; copy to a writable workspace so cargo can write
# Cargo.lock and target/ during the build.
BUILD_DIR="$(mktemp -d /tmp/build.XXXXXX)"
cp -a /source/. "$BUILD_DIR/"
cd "$BUILD_DIR"

#!/usr/bin/env bash
set -euo pipefail

# /source is mounted read-only; copy to a writable workspace so cargo can write
# Cargo.lock and target/ during the build.
BUILD_DIR="$(mktemp -d /tmp/build.XXXXXX)"
cp -a /source/. "$BUILD_DIR/"
cd "$BUILD_DIR"

echo "==> Building Soroban contract"
if [[ -n "${BLDARG:-}" ]]; then
  mapfile -t BLDARGS <<< "$BLDARG"
  stellar "${BLDARGS[@]}"
elif [[ -n "${BLDOPT:-}" ]]; then
  # shellcheck disable=SC2086
  stellar contract build ${BLDOPT}
else
  stellar contract build
fi

WASM=""
for candidate in target/wasm32v1-none/release/*.wasm; do
  if [[ -f "$candidate" ]]; then
    WASM="$candidate"
    break
  fi
done

if [[ -z "$WASM" ]]; then
  echo "ERROR: No .wasm artifact found under target/wasm32v1-none/release/" >&2
  exit 1
fi

mkdir -p /output
cp "$WASM" /output/contract.wasm

# Export the resolved Cargo.lock so the packaged tarball can pin the EXACT same
# dependency versions used to build the deployed Wasm.
if [[ -f Cargo.lock ]]; then
  cp Cargo.lock /output/Cargo.lock
fi

echo "==> Build complete: /output/contract.wasm"
shasum -a 256 /output/contract.wasm
