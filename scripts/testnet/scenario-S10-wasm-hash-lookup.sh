#!/usr/bin/env bash
# S10: Lookup by wasm hash (optional / non-RFP explorer path)
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=helpers.sh
source "$DIR/helpers.sh"
require_env

if [[ -z "${DEPLOYED_WASM_HASH:-}" ]]; then
  echo "SKIP: set DEPLOYED_WASM_HASH in .env.testnet (optional; from explorer or prior verification)"
  exit 2
fi

echo "S10: GET /v1/wasm/{hash}"
RESULT=$(curl -sS "$(api_url)/v1/wasm/${DEPLOYED_WASM_HASH}")
echo "$RESULT" | python3 -m json.tool
python3 -c "
import sys, json
d = json.load(sys.stdin)
assert len(d['verifications']) >= 1
print('OK')
" <<< "$RESULT"
