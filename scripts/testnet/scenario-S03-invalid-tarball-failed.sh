#!/usr/bin/env bash
# S03: Invalid tarball (no Cargo.toml) → status failed
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=helpers.sh
source "$DIR/helpers.sh"
require_env

ROOT="$(cd "$DIR/../.." && pwd)"
TARBALL="${TARBALL_INVALID:-$ROOT/examples/invalid-source.tar.gz}"
[[ -f "$TARBALL" ]] || "$ROOT/scripts/package-invalid.sh"

echo "S03: Invalid tarball → expect failed (HTTP 202 then status failed)"
RESPONSE=$(curl -sS -X POST "$(api_url)/v1/verify" \
  -F "network=$NETWORK" \
  -F "contract_id=$CONTRACT_ID" \
  -F "source=@${TARBALL}" \
  -F "use_docker=true")
echo "$RESPONSE" | python3 -m json.tool
VID=$(echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin)['verification_id'])")
poll_verification "$VID" failed
