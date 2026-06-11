#!/usr/bin/env bash
# Create .env.testnet for scenario scripts (contract ID is set by you after external deploy).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="$ROOT/.env.testnet"

if [[ -f "$ENV_FILE" ]]; then
  echo "Already exists: $ENV_FILE"
else
  cat > "$ENV_FILE" <<EOF
# Created by scripts/testnet/setup-env.sh — edit CONTRACT_ID before running scenarios.
API_URL=http://127.0.0.1:8080
NETWORK=testnet
CONTRACT_ID=
DEPLOYED_WASM_HASH=
GITHUB_URL=
GIT_REF=
TARBALL_MATCH=$ROOT/examples/hello-world-source.tar.gz
TARBALL_MISMATCH=$ROOT/examples/mismatch-sample-source.tar.gz
TARBALL_INVALID=$ROOT/examples/invalid-source.tar.gz
EOF
  echo "Created $ENV_FILE"
fi

echo ""
echo "Edit $ENV_FILE and set:"
echo "  CONTRACT_ID=C...   (testnet contract you deployed outside SourceProof)"
echo ""
echo "Optional: DEPLOYED_WASM_HASH (S10), GITHUB_URL + GIT_REF (S09)"
echo ""
echo "Then: make testnet-samples && make testnet-demo"
echo "Or verify in the UI: http://127.0.0.1:8080/demo/"
