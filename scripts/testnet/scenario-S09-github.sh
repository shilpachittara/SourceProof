#!/usr/bin/env bash
# S09: GitHub repo + ref → snapshot → verify (optional: set GITHUB_URL + GIT_REF in .env.testnet)
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=helpers.sh
source "$DIR/helpers.sh"
require_env

if [[ -z "${GITHUB_URL:-}" || -z "${GIT_REF:-}" ]]; then
  echo "SKIP: Set GITHUB_URL and GIT_REF in .env.testnet to a public repo/commit that"
  echo "      matches the deployed Wasm (same source as hello-world at deploy commit)."
  exit 2
fi

echo "S09: GitHub input → expect verified (if repo matches deployment)"
submit_and_poll verified \
  -F "network=$NETWORK" \
  -F "contract_id=$CONTRACT_ID" \
  -F "github_url=${GITHUB_URL}" \
  -F "git_ref=${GIT_REF}" \
  -F "use_docker=true"
