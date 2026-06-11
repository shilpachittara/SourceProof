#!/usr/bin/env bash
# Deploy a Soroban contract for the SourceProof demo, and produce the matching
# source tarball — so uploading that tarball verifies as VERIFIED.
#
# Flow:
#   1. Build the Wasm INSIDE the pinned builder image (the verifier's toolchain).
#   2. Capture the resolved Cargo.lock so the tarball pins identical deps.
#   3. Package the source tarball (Cargo.toml + Cargo.lock + contracts/).
#   4. Deploy those exact Wasm bytes to the network.
#   5. Print CONTRACT_ID + tarball path to upload in the demo UI.
#
# Usage:
#   ./scripts/deploy-contract.sh                  # examples/demo-contract
#   CONTRACT_DIR=examples/hello-world ./scripts/deploy-contract.sh
#
# Requirements: Docker + builder image (make builder), Stellar CLI + funded key.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

CONTRACT_DIR="${CONTRACT_DIR:-examples/demo-contract}"
IDENTITY="${STELLAR_IDENTITY:-deployer}"
NETWORK="${NETWORK:-testnet}"
BUILDER_IMAGE="${BUILDER_IMAGE:-soroban-verify-builder:local}"

SRC="$ROOT/$CONTRACT_DIR"
NAME="$(basename "$CONTRACT_DIR")"
TARBALL="$ROOT/examples/${NAME}-source.tar.gz"
WORK="$ROOT/tmp/deploy-${NAME}"

[[ -f "$SRC/Cargo.toml" ]] || { echo "No Cargo.toml in $SRC"; exit 1; }
command -v docker  >/dev/null || { echo "Docker required"; exit 1; }
command -v stellar >/dev/null || { echo "Stellar CLI required (brew install stellar-cli)"; exit 1; }

if ! docker image inspect "$BUILDER_IMAGE" >/dev/null 2>&1; then
  echo "==> Building builder image (once, ~1-2 min)…"
  docker compose --profile builder build builder
fi

echo "==> [1/4] Building Wasm in builder image from $CONTRACT_DIR"
rm -rf "$WORK"
mkdir -p "$WORK/out"
docker run --rm \
  -v "$SRC:/source:ro" \
  -v "$WORK/out:/output" \
  "$BUILDER_IMAGE"
WASM="$WORK/out/contract.wasm"
[[ -f "$WASM" ]] || { echo "Build produced no Wasm"; exit 1; }

# Persist the resolved lockfile into the source so the tarball matches the build.
if [[ -f "$WORK/out/Cargo.lock" ]]; then
  cp "$WORK/out/Cargo.lock" "$SRC/Cargo.lock"
  echo "    Saved resolved Cargo.lock into $CONTRACT_DIR"
fi
WASM_HASH=$(shasum -a 256 "$WASM" | awk '{print $1}')
echo "    Wasm hash: $WASM_HASH"

echo "==> [2/4] Packaging source tarball"
( cd "$SRC"
  LOCK=(); [[ -f Cargo.lock ]] && LOCK=(Cargo.lock)
  # COPYFILE_DISABLE stops macOS tar from emitting AppleDouble (._*) files.
  COPYFILE_DISABLE=1 tar --no-xattrs -czf "$TARBALL" \
    --exclude='target' --exclude='.git' --exclude='._*' --exclude='.DS_Store' \
    Cargo.toml "${LOCK[@]}" contracts/
)
echo "    Tarball: $TARBALL"

echo "==> [3/4] Ensuring funded identity: $IDENTITY"
stellar keys address "$IDENTITY" >/dev/null 2>&1 || stellar keys generate "$IDENTITY" --network "$NETWORK"
stellar keys fund "$IDENTITY" --network "$NETWORK" 2>/dev/null || true

echo "==> [4/4] Deploying to $NETWORK"
DEPLOY_OUT=$(stellar contract deploy --wasm "$WASM" --source "$IDENTITY" --network "$NETWORK" 2>&1)
echo "$DEPLOY_OUT"
CONTRACT_ID=$(echo "$DEPLOY_OUT" | grep -oE 'C[A-Z0-9]{55}' | tail -1)

# Machine-readable summary for other scripts (e.g. github-demo.sh).
cat > "$WORK/summary.env" <<EOF
CONTRACT_ID=$CONTRACT_ID
WASM_HASH=$WASM_HASH
TARBALL=$TARBALL
CONTRACT_DIR=$SRC
NETWORK=$NETWORK
EOF

echo ""
echo "=================================================================="
echo " Deployed — ready to verify as VERIFIED"
echo "   CONTRACT_ID : $CONTRACT_ID"
echo "   WASM_HASH   : $WASM_HASH"
echo "   TARBALL     : $TARBALL"
echo "=================================================================="
echo ""
echo "Now verify in the UI (http://localhost:8080/demo/):"
echo "  Upload tab → network=$NETWORK"
echo "             → contract_id=$CONTRACT_ID"
echo "             → file=$TARBALL"
echo ""
echo "Or via API:"
echo "  curl -X POST http://localhost:8080/v1/verify \\"
echo "    -F network=$NETWORK -F contract_id=$CONTRACT_ID -F source=@$TARBALL"
