#!/usr/bin/env bash
# End-to-end local demo without testnet: build wasm in builder, verify via API using wasm_hash.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

API_URL="${API_URL:-http://localhost:8080}"
TARBALL="${TARBALL:-$ROOT/examples/hello-world-source.tar.gz}"
EXAMPLE_SRC="$ROOT/examples/hello-world"
OUT_DIR="$ROOT/tmp/demo-out"

echo "==> Building builder image (first run may take 15-30 min)"
docker compose build builder

echo "==> Building example contract inside builder"
rm -rf "$OUT_DIR"
mkdir -p "$OUT_DIR"
docker run --rm \
  -v "$EXAMPLE_SRC:/source:ro" \
  -v "$OUT_DIR:/output" \
  --network none \
  soroban-verify-builder:local

WASM_HASH=$(./scripts/hash-wasm.sh "$OUT_DIR/contract.wasm")
echo "Built wasm hash: $WASM_HASH"

if ! curl -sf "$API_URL/health" >/dev/null; then
  echo "==> Starting API"
  docker compose up -d api
  sleep 3
fi

echo "==> Submitting verification"
RESPONSE=$(curl -sS -X POST "$API_URL/v1/verify" \
  -F "network=testnet" \
  -F "wasm_hash=$WASM_HASH" \
  -F "source=@${TARBALL}" \
  -F "use_docker=true")

echo "$RESPONSE" | python3 -m json.tool
VERIFICATION_ID=$(echo "$RESPONSE" | python3 -c "import sys, json; print(json.load(sys.stdin)['verification_id'])")

echo "==> Polling result"
for _ in $(seq 1 60); do
  RESULT=$(curl -sS "$API_URL/v1/verifications/$VERIFICATION_ID")
  STATUS=$(echo "$RESULT" | python3 -c "import sys, json; print(json.load(sys.stdin)['status'])")
  echo "status=$STATUS"
  if [[ "$STATUS" != "pending" ]]; then
    echo "$RESULT" | python3 -m json.tool
    [[ "$STATUS" == "verified" ]]
    exit 0
  fi
  sleep 5
done

echo "Timed out"
exit 1
