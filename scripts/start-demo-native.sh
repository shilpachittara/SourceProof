#!/usr/bin/env bash
# Run API + demo UI locally WITHOUT Docker (SQLite + host stellar-cli for builds).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
API="$ROOT/api"
VENV="$API/.venv"

echo ""
echo "  ◈ SourceProof (native mode — no Docker)"
echo ""
echo "==> Checking tools (no Docker required for this path)"
command -v python3 >/dev/null || { echo "Install Python 3.10+"; exit 1; }
command -v stellar >/dev/null || {
  echo "Missing stellar CLI. Install one of:"
  echo "  cargo install stellar-cli --locked"
  echo "  # or after Homebrew: brew install stellar"
  exit 1
}
command -v rustc >/dev/null || { echo "Install Rust: https://rustup.rs"; exit 1; }
rustup target add wasm32v1-none 2>/dev/null || true

mkdir -p "$ROOT/data/sources" "$ROOT/data"

if [[ ! -d "$VENV" ]]; then
  echo "==> Creating Python venv"
  python3 -m venv "$VENV"
fi
# shellcheck source=/dev/null
source "$VENV/bin/activate"
pip install -q -r "$API/requirements.txt"

export DATABASE_URL="sqlite:///${ROOT}/data/verify.db"
export STORAGE_DIR="${ROOT}/data/sources"
export BUILDER_IMAGE="host-stellar-cli"
export VERIFIER_INSTANCE_ID="local-verifier-native"

echo ""
echo "Starting SourceProof API (native, use_docker=false for verification builds)"
echo "  UI:       http://127.0.0.1:8080/demo/"
echo "  API docs: http://127.0.0.1:8080/docs"
echo "  Health:   http://127.0.0.1:8080/health"
echo ""
echo "In another terminal run: ./scripts/demo-local-native.sh"
echo "Press Ctrl+C to stop."
echo ""

cd "$API"
exec uvicorn app.main:app --host 127.0.0.1 --port 8080 --reload
