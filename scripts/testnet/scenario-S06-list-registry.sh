#!/usr/bin/env bash
# S06: GET /v1/verifications?network=testnet
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=helpers.sh
source "$DIR/helpers.sh"
load_env
NETWORK="${NETWORK:-testnet}"

echo "S06: List verifications registry"
RESULT=$(curl -sS "$(api_url)/v1/verifications?network=${NETWORK}&limit=20")
echo "$RESULT" | python3 -m json.tool
python3 -c "
import sys, json
d = json.load(sys.stdin)
assert d['total'] >= 1, 'expected at least one verification'
print('OK: total=', d['total'])
" <<< "$RESULT"
