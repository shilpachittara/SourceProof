#!/usr/bin/env bash
# End-to-end GitHub-flow demo for SourceProof.
#
# What it does:
#   1. Builds the demo contract in the pinned builder image and DEPLOYS those
#      exact Wasm bytes to testnet (reproducible toolchain => verifiable).
#   2. Publishes the matching source (Cargo.toml + Cargo.lock + contracts/) to
#      your GitHub repo on a fresh commit.
#   3. Prints the exact GitHub-tab verification you can run in the UI/API, which
#      will resolve the repo @ commit, rebuild, and report VERIFIED.
#
# This is the SEP-55 style flow: the deployer publishes source at a commit and
# the verifier proves the on-chain bytecode was built from it.
#
# Usage:
#   ./scripts/testnet/github-demo.sh https://github.com/shilpachittara/stellar-test.git
#
# Requirements:
#   - Docker + builder image (make builder)
#   - Stellar CLI + a funded testnet identity
#   - git push access to the target repo (gh auth / SSH key / PAT)
set -euo pipefail

REPO_URL="${1:?Usage: github-demo.sh <git-remote-url>  e.g. https://github.com/owner/repo.git}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

CONTRACT_DIR="${CONTRACT_DIR:-examples/demo-contract}"
NAME="$(basename "$CONTRACT_DIR")"
API_URL="${API_URL:-http://127.0.0.1:8080}"

echo "==> [1/3] Build + deploy via the pinned builder image"
CONTRACT_DIR="$CONTRACT_DIR" ./scripts/deploy-contract.sh

SUMMARY="$ROOT/tmp/deploy-${NAME}/summary.env"
[[ -f "$SUMMARY" ]] || { echo "Missing $SUMMARY (deploy failed?)"; exit 1; }
# shellcheck disable=SC1090
source "$SUMMARY"

echo ""
echo "==> [2/3] Publishing source to $REPO_URL"
PUB="$ROOT/tmp/github-publish-${NAME}"
rm -rf "$PUB"
mkdir -p "$PUB"
cp "$CONTRACT_DIR/Cargo.toml" "$PUB/"
[[ -f "$CONTRACT_DIR/Cargo.lock" ]] && cp "$CONTRACT_DIR/Cargo.lock" "$PUB/"
cp -R "$CONTRACT_DIR/contracts" "$PUB/"
cat > "$PUB/README.md" <<EOF
# Soroban demo contract

Deployed to Stellar **$NETWORK** as \`$CONTRACT_ID\`.
Verify reproducibly with SourceProof (GitHub flow).
EOF

(
  cd "$PUB"
  git init -q
  git add .
  git -c user.name="SourceProof Demo" -c user.email="demo@sourceproof.local" \
    commit -q -m "Soroban demo contract ($CONTRACT_ID)"
  git branch -M main
  git remote add origin "$REPO_URL"
  echo "    Pushing to origin/main…"
  git push -u origin main
)
COMMIT="$(cd "$PUB" && git rev-parse HEAD)"

# Normalize the repo URL for the UI (strip .git suffix)
WEB_URL="${REPO_URL%.git}"

echo ""
echo "=================================================================="
echo " GitHub flow ready"
echo "   CONTRACT_ID : $CONTRACT_ID"
echo "   REPO        : $WEB_URL"
echo "   COMMIT      : $COMMIT"
echo "=================================================================="
echo ""
echo "Verify in the UI (GitHub tab @ $API_URL/demo/):"
echo "   network      = $NETWORK"
echo "   contract_id  = $CONTRACT_ID"
echo "   github_url   = $WEB_URL"
echo "   git_ref      = $COMMIT"
echo ""
echo "Or via API:"
echo "  curl -X POST $API_URL/v1/verify \\"
echo "    -F network=$NETWORK -F contract_id=$CONTRACT_ID \\"
echo "    -F github_url=$WEB_URL -F git_ref=$COMMIT"
