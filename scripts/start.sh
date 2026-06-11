#!/usr/bin/env bash
# SourceProof — start API + demo UI (Docker).
# Skips image rebuild when images already exist (use SOURCEPROOF_FORCE_BUILD=1 to rebuild).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

APP_NAME="SourceProof"
DEMO_URL="http://localhost:8080/demo/"
API_URL="http://localhost:8080"
COMPOSE_FILE="${SOURCEPROOF_COMPOSE_FILE:-docker-compose.yml}"
MAX_HEALTH_ATTEMPTS=45

compose() {
  docker compose -f "$COMPOSE_FILE" "$@"
}

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is required. Install it, then run: make start"
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  echo "Docker daemon is not running. Start Colima or Docker Desktop, then retry."
  exit 1
fi

# The API container builds contracts by calling `docker run` over the mounted
# Docker socket. The socket path differs by setup (Colima vs Docker Desktop vs
# Linux). Auto-detect it so the same compose file works everywhere; production
# Linux/CI falls back to the standard /var/run/docker.sock.
detect_docker_sock() {
  # 1) Honor an explicit override.
  if [[ -n "${DOCKER_SOCK:-}" ]]; then
    echo "$DOCKER_SOCK"; return
  fi
  # 2) Ask the active docker context for its endpoint.
  local host
  host="$(docker context inspect --format '{{.Endpoints.docker.Host}}' 2>/dev/null || true)"
  # Colima (and Docker Desktop) run the daemon in a VM. Bind-mount paths are
  # resolved by the daemon INSIDE the VM, where the socket lives at the standard
  # /var/run/docker.sock — the Mac-side socket path cannot be bind-mounted.
  if [[ "$host" == *colima* ]] || [[ "$host" == *docker.raw.sock* ]]; then
    echo "/var/run/docker.sock"; return
  fi
  if [[ "$host" == unix://* ]]; then
    echo "${host#unix://}"; return
  fi
  # 3) Standard path (Linux, Docker Desktop, CI).
  echo "/var/run/docker.sock"
}

DOCKER_SOCK="$(detect_docker_sock)"
export DOCKER_SOCK

# Host path that maps to the API container's /app/data. Needed so contract builds
# (docker-out-of-docker) can bind-mount work dirs through the host Docker daemon.
export HOST_DATA_DIR="${HOST_DATA_DIR:-$ROOT/data}"
echo "==> Host data dir: $HOST_DATA_DIR"
if [[ ! -S "$DOCKER_SOCK" ]]; then
  echo "Warning: Docker socket not found at '$DOCKER_SOCK'."
  echo "Set DOCKER_SOCK=/path/to/docker.sock and retry (verifications need it)."
else
  echo "==> Using Docker socket: $DOCKER_SOCK"
fi

mkdir -p "$ROOT/data/sources" "$ROOT/data/pglite"

# Already up?
if curl -sf "${API_URL}/health" >/dev/null 2>&1; then
  echo "✓ ${APP_NAME} is already running at ${DEMO_URL}"
  command -v open >/dev/null 2>&1 && open "${DEMO_URL}" 2>/dev/null || true
  exit 0
fi

echo ""
echo "  ╭─────────────────────────────────────────╮"
echo "  │  ◈  ${APP_NAME}                         │"
echo "  ╰─────────────────────────────────────────╯"
echo ""

API_IMAGE="soroban-verify-api:local"
PG_IMAGE="soroban-verify-pglite:local"
FORCE="${SOURCEPROOF_FORCE_BUILD:-0}"
USE_FAST="${SOURCEPROOF_FAST:-0}"

if [[ "$USE_FAST" == "1" ]] || [[ "$COMPOSE_FILE" == *fast* ]]; then
  echo "==> Fast mode (SQLite, single container)…"
  if [[ "$FORCE" == "1" ]] || ! docker image inspect "$API_IMAGE" >/dev/null 2>&1; then
    compose build api
  else
    echo "    Using cached API image (set SOURCEPROOF_FORCE_BUILD=1 to rebuild)"
  fi
  compose up -d api
else
  if [[ "$FORCE" == "1" ]] \
    || ! docker image inspect "$API_IMAGE" >/dev/null 2>&1 \
    || ! docker image inspect "$PG_IMAGE" >/dev/null 2>&1; then
    echo "==> Building images (first run ~1–3 min; cached runs skip this)…"
    compose build pglite api
  else
    echo "==> Using cached images (SOURCEPROOF_FORCE_BUILD=1 to rebuild)…"
  fi
  echo "==> Starting database + API + UI…"
  compose up -d pglite api
fi

echo "==> Waiting for API…"
for i in $(seq 1 "$MAX_HEALTH_ATTEMPTS"); do
  if curl -sf "${API_URL}/health" >/dev/null 2>&1; then
    break
  fi
  if [[ "$i" -eq "$MAX_HEALTH_ATTEMPTS" ]]; then
    echo "API did not become healthy. Logs: docker compose -f $COMPOSE_FILE logs -f api"
    exit 1
  fi
  sleep 1
done

if ! docker image inspect soroban-verify-builder:local >/dev/null 2>&1; then
  echo ""
  echo "Note: Verifications need the builder image: make builder (~1–2 min once)"
fi

HEALTH=$(curl -sS "${API_URL}/health")
echo ""
echo "✓ ${APP_NAME} is running"
echo "  Demo UI   ${DEMO_URL}"
echo "  API docs  ${API_URL}/docs"
echo ""
echo "$HEALTH" | python3 -m json.tool 2>/dev/null || echo "$HEALTH"
echo ""
echo "Faster next time: make start-fast   |   Rebuild images: SOURCEPROOF_FORCE_BUILD=1 make start"
echo "Stop: make down"
echo ""

command -v open >/dev/null 2>&1 && open "${DEMO_URL}" 2>/dev/null || true
