#!/usr/bin/env bash
# Shared helpers for testnet demo scenarios.

api_url() {
  echo "${API_URL:-http://127.0.0.1:8080}"
}

load_env() {
  local root
  root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
  if [[ -f "$root/.env.testnet" ]]; then
    # shellcheck source=/dev/null
    set -a
    source "$root/.env.testnet"
    set +a
  fi
}

require_env() {
  load_env
  : "${CONTRACT_ID:?Set CONTRACT_ID in .env.testnet or environment}"
  : "${NETWORK:=testnet}"
  API_URL="$(api_url)"
}

poll_verification() {
  local vid="$1"
  local url
  url="$(api_url)/v1/verifications/$vid"
  for _ in $(seq 1 60); do
    local result status
    result=$(curl -sS "$url")
    status=$(echo "$result" | python3 -c "import sys,json; print(json.load(sys.stdin)['status'])")
    echo "  status=$status"
    if [[ "$status" != "pending" ]]; then
      echo "$result" | python3 -m json.tool
      [[ "$status" == "${2:-verified}" ]]
      return
    fi
    sleep 3
  done
  echo "Timed out polling $vid"
  return 1
}

submit_and_poll() {
  local expected_status="${1:-verified}"
  shift
  local response
  response=$(curl -sS -X POST "$(api_url)/v1/verify" "$@")
  echo "$response" | python3 -m json.tool
  local vid
  vid=$(echo "$response" | python3 -c "import sys,json; print(json.load(sys.stdin)['verification_id'])")
  poll_verification "$vid" "$expected_status"
}
