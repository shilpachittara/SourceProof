#!/usr/bin/env bash
# Run all testnet demo scenarios (API must be running).
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=helpers.sh
source "$DIR/helpers.sh"

load_env
API_URL="$(api_url)"
NETWORK="${NETWORK:-testnet}"

echo "=============================================="
echo " SourceProof — testnet demo scenario runner"
echo " API: $API_URL  network: $NETWORK"
echo "=============================================="

curl -sf "$API_URL/health" >/dev/null || {
  echo "API not running. Start first:"
  echo "  make demo   OR   ./scripts/start-demo-native.sh"
  exit 1
}

if [[ ! -f "$(cd "$DIR/../.." && pwd)/.env.testnet" ]]; then
  echo "Missing .env.testnet — run: make testnet-env"
  echo "Then set CONTRACT_ID to your testnet contract (deployed outside this repo)."
  exit 1
fi

SCENARIOS=(
  S01-upload-verified
  S02-upload-mismatch
  S03-invalid-tarball-failed
  S04-lookup-verified
  S05-lookup-unverified-404
  S06-list-registry
  S07-download-source
  S08-hash-only
  S09-github
  S10-wasm-hash-lookup
)

PASS=0
FAIL=0
SKIP=0

for s in "${SCENARIOS[@]}"; do
  script="$DIR/scenario-${s}.sh"
  echo ""
  echo "---------- $s ----------"
  if [[ ! -f "$script" ]]; then
    echo "SKIP (script missing: $script)"
    SKIP=$((SKIP + 1))
    continue
  fi
  if bash "$script"; then
    echo "PASS $s"
    PASS=$((PASS + 1))
  else
    rc=$?
    if [[ $rc -eq 2 ]]; then
      echo "SKIP $s (optional / not configured)"
      SKIP=$((SKIP + 1))
    else
      echo "FAIL $s"
      FAIL=$((FAIL + 1))
    fi
  fi
done

echo ""
echo "=============================================="
echo " Done: PASS=$PASS FAIL=$FAIL SKIP=$SKIP"
echo " Demo UI: $API_URL/demo/"
echo "=============================================="
[[ $FAIL -eq 0 ]]
