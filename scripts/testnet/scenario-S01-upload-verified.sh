#!/usr/bin/env bash
# S01: Upload tarball + contract_id → status verified
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=helpers.sh
source "$DIR/helpers.sh"
require_env

ROOT="$(cd "$DIR/../.." && pwd)"
TARBALL="${TARBALL_MATCH:-$ROOT/examples/hello-world-source.tar.gz}"
[[ -f "$TARBALL" ]] || "$ROOT/scripts/package-example.sh"

echo "S01: Upload + contract_id → expect verified"
submit_and_poll verified \
  -F "network=$NETWORK" \
  -F "contract_id=$CONTRACT_ID" \
  -F "source=@${TARBALL}" \
  -F "use_docker=true"
