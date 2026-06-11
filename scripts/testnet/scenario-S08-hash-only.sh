#!/usr/bin/env bash
# S08: Two-step content-addressed — upload first, then tarball_sha256 only
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=helpers.sh
source "$DIR/helpers.sh"
require_env

ROOT="$(cd "$DIR/../.." && pwd)"
TARBALL="${TARBALL_MATCH:-$ROOT/examples/hello-world-source.tar.gz}"

echo "S08a: Seed content store (upload)"
RESPONSE=$(curl -sS -X POST "$(api_url)/v1/verify" \
  -F "network=$NETWORK" \
  -F "contract_id=$CONTRACT_ID" \
  -F "source=@${TARBALL}" \
  -F "use_docker=true")
HASH=$(echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('verification_id',''))" 2>/dev/null || true)
# Get tarball hash from poll
VID=$(echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin)['verification_id'])")
poll_verification "$VID" verified >/dev/null
DETAIL=$(curl -sS "$(api_url)/v1/verifications/$VID")
CONTENT_HASH=$(echo "$DETAIL" | python3 -c "import sys,json; print(json.load(sys.stdin)['tarball_content_hash'])")

echo "S08b: Hash-only submit (content-addressed)"
submit_and_poll verified \
  -F "network=$NETWORK" \
  -F "contract_id=$CONTRACT_ID" \
  -F "tarball_sha256=${CONTENT_HASH}" \
  -F "use_docker=true"

echo "$DETAIL" | python3 -c "import sys,json; d=json.load(sys.stdin); assert d['source']['origin'] in ('upload','content-addressed','github','url','ipfs')"
