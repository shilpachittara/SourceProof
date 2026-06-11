#!/usr/bin/env bash
# S04: GET /v1/testnet/contracts/{id} → verified + freshness current
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=helpers.sh
source "$DIR/helpers.sh"
require_env

echo "S04: Contract lookup → expect verified + freshness current"
RESULT=$(curl -sS "$(api_url)/v1/${NETWORK}/contracts/${CONTRACT_ID}")
echo "$RESULT" | python3 -m json.tool

python3 -c "
import sys, json
d = json.load(sys.stdin)
v = d['verifications'][0]
assert v['status'] == 'verified', v['status']
assert v.get('freshness') == 'current', v.get('freshness')
print('OK: verified + current')
" <<< "$RESULT"
