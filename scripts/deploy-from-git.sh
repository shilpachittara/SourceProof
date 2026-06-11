#!/usr/bin/env bash
# Deploy a Soroban contract straight FROM a git repo.
#
# Flow:
#   1. Clone the repo (at an optional ref).
#   2. Build the Wasm INSIDE the pinned builder image (the verifier's toolchain).
#   3. Deploy those exact Wasm bytes to the network.
#   4. Print CONTRACT_ID + COMMIT + the GitHub-flow verification command.
#
# Because the repo commits Cargo.lock and we build in the pinned image, the
# deployed bytecode is byte-identical to what SourceProof rebuilds from the same
# commit -> the GitHub verification returns `verified`.
#
# Usage:
#   ./scripts/deploy-from-git.sh https://github.com/shilpachittara/stellar-test.git [git-ref]
#
# Requirements: Docker + builder image (make builder), Stellar CLI + funded key.
set -euo pipefail

REPO_URL="${1:?Usage: deploy-from-git.sh <repo-url> [git-ref]}"
REF="${2:-}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

BUILDER_IMAGE="${BUILDER_IMAGE:-soroban-verify-builder:local}"
IDENTITY="${STELLAR_IDENTITY:-deployer}"
NETWORK="${NETWORK:-testnet}"
API_URL="${API_URL:-http://127.0.0.1:8080}"

command -v docker  >/dev/null || { echo "Docker required"; exit 1; }
command -v stellar >/dev/null || { echo "Stellar CLI required (brew install stellar-cli)"; exit 1; }
command -v git     >/dev/null || { echo "git required"; exit 1; }

if ! docker image inspect "$BUILDER_IMAGE" >/dev/null 2>&1; then
  echo "==> Building builder image (once, ~1-2 min)…"
  ( cd "$ROOT" && docker compose --profile builder build builder )
fi

# Work under the repo (shared with the Docker VM on macOS/Colima); /tmp and
# /var/folders are NOT shared, so a bind-mount from there would be empty.
WORK="$ROOT/tmp/deploy-from-git"
rm -rf "$WORK"
mkdir -p "$WORK"
trap 'rm -rf "$WORK"' EXIT

echo "==> [1/3] Cloning $REPO_URL"
git clone --quiet "$REPO_URL" "$WORK/repo"
cd "$WORK/repo"
if [[ -n "$REF" ]]; then
  git checkout --quiet "$REF"
fi
COMMIT="$(git rev-parse HEAD)"
echo "    commit: $COMMIT"
[[ -f Cargo.toml ]] || { echo "Repo has no Cargo.toml at root"; exit 1; }
[[ -f Cargo.lock ]] || echo "    WARNING: repo has no Cargo.lock — build may not be reproducible"

echo "==> [2/3] Building Wasm in builder image"
mkdir -p "$WORK/out"
docker run --rm -v "$WORK/repo:/source:ro" -v "$WORK/out:/output" "$BUILDER_IMAGE"
WASM="$WORK/out/contract.wasm"
[[ -f "$WASM" ]] || { echo "Build produced no Wasm"; exit 1; }
WASM_HASH="$(shasum -a 256 "$WASM" | awk '{print $1}')"
echo "    Wasm hash: $WASM_HASH"

echo "==> [3/3] Deploying to $NETWORK as identity '$IDENTITY'"
stellar keys address "$IDENTITY" >/dev/null 2>&1 || stellar keys generate "$IDENTITY" --network "$NETWORK"
stellar keys fund "$IDENTITY" --network "$NETWORK" 2>/dev/null || true
DEPLOY_OUT="$(stellar contract deploy --wasm "$WASM" --source "$IDENTITY" --network "$NETWORK" 2>&1)"
echo "$DEPLOY_OUT"
CONTRACT_ID="$(echo "$DEPLOY_OUT" | grep -oE 'C[A-Z0-9]{55}' | tail -1)"

WEB_URL="${REPO_URL%.git}"
echo ""
echo "=================================================================="
echo " Deployed from git — ready to verify (GitHub flow)"
echo "   CONTRACT_ID : $CONTRACT_ID"
echo "   WASM_HASH   : $WASM_HASH"
echo "   REPO        : $WEB_URL"
echo "   COMMIT      : $COMMIT"
echo "=================================================================="
echo ""
echo "Verify via API:"
echo "  curl -X POST $API_URL/v1/verify \\"
echo "    -F network=$NETWORK -F contract_id=$CONTRACT_ID \\"
echo "    -F github_url=$WEB_URL -F git_ref=$COMMIT"
echo ""
echo "Or in the UI ($API_URL/demo/) → GitHub tab with the values above."
