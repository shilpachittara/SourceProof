#!/usr/bin/env bash
# S05: Lookup unknown contract → 404
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=helpers.sh
source "$DIR/helpers.sh"
load_env
NETWORK="${NETWORK:-testnet}"

FAKE_ID="C0000000000000000000000000000000000000000000000000000000000001"
echo "S05: Lookup fake contract → expect HTTP 404"
HTTP=$(curl -sS -o /tmp/s05.json -w "%{http_code}" "$(api_url)/v1/${NETWORK}/contracts/${FAKE_ID}")
cat /tmp/s05.json | python3 -m json.tool
[[ "$HTTP" == "404" ]]
