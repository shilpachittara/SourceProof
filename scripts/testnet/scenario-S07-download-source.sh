#!/usr/bin/env bash
# S07: Download verified source tarball by content hash
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=helpers.sh
source "$DIR/helpers.sh"
require_env

echo "S07: Download source tarball"
LOOKUP=$(curl -sS "$(api_url)/v1/${NETWORK}/contracts/${CONTRACT_ID}")
HASH=$(echo "$LOOKUP" | python3 -c "import sys,json; print(json.load(sys.stdin)['verifications'][0]['tarball_content_hash'])")
OUT="/tmp/s07-${HASH:0:16}.tar.gz"
HTTP=$(curl -sS -o "$OUT" -w "%{http_code}" "$(api_url)/v1/source/${HASH}")
echo "HTTP $HTTP → $OUT ($(wc -c < "$OUT") bytes)"
[[ "$HTTP" == "200" ]]
file "$OUT" | grep -q gzip
