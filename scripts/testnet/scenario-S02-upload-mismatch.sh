#!/usr/bin/env bash
# S02: Wrong source tarball + same contract_id → status mismatch
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=helpers.sh
source "$DIR/helpers.sh"
require_env

ROOT="$(cd "$DIR/../.." && pwd)"
TARBALL="${TARBALL_MISMATCH:-$ROOT/examples/mismatch-sample-source.tar.gz}"
[[ -f "$TARBALL" ]] || "$ROOT/scripts/package-mismatch.sh"

echo "S02: Mismatch tarball + contract_id → expect mismatch"
submit_and_poll mismatch \
  -F "network=$NETWORK" \
  -F "contract_id=$CONTRACT_ID" \
  -F "source=@${TARBALL}" \
  -F "use_docker=true"
