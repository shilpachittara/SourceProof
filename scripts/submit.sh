#!/usr/bin/env bash
set -euo pipefail

API_URL="${API_URL:-http://localhost:8080}"
NETWORK="${NETWORK:-testnet}"
CONTRACT_ID="${CONTRACT_ID:?Set CONTRACT_ID}"
TARBALL="${TARBALL:?Set TARBALL path to source.tar.gz}"
USE_DOCKER="${USE_DOCKER:-true}"

echo "Submitting verification to $API_URL"
RESPONSE=$(curl -sS -X POST "$API_URL/v1/verify" \
  -F "network=$NETWORK" \
  -F "contract_id=$CONTRACT_ID" \
  -F "source=@${TARBALL}" \
  -F "use_docker=$USE_DOCKER")

echo "$RESPONSE" | python3 -m json.tool

VERIFICATION_ID=$(echo "$RESPONSE" | python3 -c "import sys, json; print(json.load(sys.stdin)['verification_id'])")
POLL_URL="$API_URL/v1/verifications/$VERIFICATION_ID"

echo "Polling $POLL_URL"
for _ in $(seq 1 60); do
  STATUS_JSON=$(curl -sS "$POLL_URL")
  STATUS=$(echo "$STATUS_JSON" | python3 -c "import sys, json; print(json.load(sys.stdin)['status'])")
  echo "status=$STATUS"
  if [[ "$STATUS" != "pending" ]]; then
    echo "$STATUS_JSON" | python3 -m json.tool
    exit 0
  fi
  sleep 5
done

echo "Timed out waiting for verification"
exit 1
