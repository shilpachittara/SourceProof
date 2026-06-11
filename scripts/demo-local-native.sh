#!/usr/bin/env bash
# End-to-end demo WITHOUT Docker: host stellar-cli build + API with use_docker=false.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
API_URL="${API_URL:-http://127.0.0.1:8080}"
TARBALL="${TARBALL:-$ROOT/examples/hello-world-source.tar.gz}"
EXAMPLE="$ROOT/examples/hello-world"

command -v stellar >/dev/null || { echo "Install stellar-cli first (see start-demo-native.sh)"; exit 1; }

if [[ ! -f "$TARBALL" ]]; then
  echo "==> Creating example tarball"
  "$ROOT/scripts/package-example.sh"
fi

echo "==> Building example contract with host stellar-cli"
cd "$EXAMPLE"
stellar contract build --release
WASM=$(find target/wasm32v1-none/release -maxdepth 1 -name '*.wasm' | head -1)
[[ -n "$WASM" ]] || { echo "No .wasm under target/wasm32v1-none/release"; exit 1; }
WASM_HASH=$("$ROOT/scripts/hash-wasm.sh" "$WASM")
echo "Built wasm hash: $WASM_HASH"

if ! curl -sf "$API_URL/health" >/dev/null; then
  echo "Start the API first in another terminal:"
  echo "  ./scripts/start-demo-native.sh"
  exit 1
fi

echo "==> Submitting verification (use_docker=false)"
RESPONSE=$(curl -sS -X POST "$API_URL/v1/verify" \
  -F "network=testnet" \
  -F "wasm_hash=$WASM_HASH" \
  -F "source=@${TARBALL}" \
  -F "use_docker=false")

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
    echo ""
    echo "Open http://127.0.0.1:8080/demo/ to see the registry."
    exit 0
  fi
  sleep 2
done
echo "Timed out"
exit 1
