#!/usr/bin/env bash
# Produce a guaranteed-verifiable demo contract on testnet.
#
# Why this exists: a contract verifies as `verified` ONLY when the on-chain Wasm
# was built by the SAME pinned builder image the verifier uses. This script:
#   1. packages the source tarball (incl. Cargo.lock) — the file you upload
#   2. builds the Wasm inside the builder image (the verifier's toolchain)
#   3. deploys those exact bytes to testnet
#   4. prints the contract ID + tarball path to use in the demo
#
# Requirements: Docker + builder image (make builder), Stellar CLI + a funded
# testnet identity (default: "deployer").
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

IDENTITY="${STELLAR_IDENTITY:-deployer}"
NETWORK="${NETWORK:-testnet}"
EXAMPLE_DIR="${EXAMPLE_DIR:-$ROOT/examples/hello-world}"
TARBALL="${TARBALL:-$ROOT/examples/hello-world-source.tar.gz}"
BUILDER_IMAGE="${BUILDER_IMAGE:-soroban-verify-builder:local}"
WORK="$ROOT/tmp/build-deploy"

command -v docker >/dev/null || { echo "Docker required"; exit 1; }
command -v stellar >/dev/null || { echo "Stellar CLI required (brew install stellar-cli)"; exit 1; }

# 0) Builder image present?
if ! docker image inspect "$BUILDER_IMAGE" >/dev/null 2>&1; then
  echo "==> Building builder image (once, ~1-2 min)…"
  docker compose --profile builder build builder
fi

# 1) Package the source tarball (this is what you upload to verify).
echo "==> Packaging source tarball"
"$ROOT/scripts/package-example.sh" "$TARBALL"

# 2) Build the Wasm inside the builder image (verifier's exact toolchain).
echo "==> Building Wasm in builder image"
rm -rf "$WORK"
mkdir -p "$WORK/src" "$WORK/out"
tar -xzf "$TARBALL" -C "$WORK/src"
docker run --rm \
  -v "$WORK/src:/source:ro" \
  -v "$WORK/out:/output" \
  "$BUILDER_IMAGE"
WASM="$WORK/out/contract.wasm"
[[ -f "$WASM" ]] || { echo "Build produced no Wasm"; exit 1; }
WASM_HASH=$(shasum -a 256 "$WASM" | awk '{print $1}')
echo "    Built Wasm hash: $WASM_HASH"

# 3) Ensure a funded identity, then deploy the exact bytes.
echo "==> Ensuring funded testnet identity: $IDENTITY"
stellar keys address "$IDENTITY" >/dev/null 2>&1 || stellar keys generate "$IDENTITY" --network "$NETWORK"
stellar keys fund "$IDENTITY" --network "$NETWORK" 2>/dev/null || true

echo "==> Deploying to $NETWORK"
DEPLOY_OUT=$(stellar contract deploy --wasm "$WASM" --source "$IDENTITY" --network "$NETWORK" 2>&1)
echo "$DEPLOY_OUT"
CONTRACT_ID=$(echo "$DEPLOY_OUT" | grep -oE 'C[A-Z0-9]{55}' | tail -1)

echo ""
echo "=================================================================="
echo " Demo contract ready (will verify as VERIFIED)"
echo "   CONTRACT_ID : $CONTRACT_ID"
echo "   WASM_HASH   : $WASM_HASH"
echo "   TARBALL     : $TARBALL"
echo "=================================================================="
echo ""
echo "Verify in the UI (http://localhost:8080/demo/):"
echo "  Upload tab → network=$NETWORK, contract_id=$CONTRACT_ID, file=$TARBALL"
echo ""
echo "Or via API:"
echo "  curl -X POST http://localhost:8080/v1/verify \\"
echo "    -F network=$NETWORK -F contract_id=$CONTRACT_ID \\"
echo "    -F source=@$TARBALL"
echo ""
echo "Then lookup:"
echo "  curl http://localhost:8080/v1/$NETWORK/contracts/$CONTRACT_ID"
