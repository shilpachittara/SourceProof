#!/usr/bin/env bash
# Run on the EC2 host after `git pull` (invoked by GitHub Actions or manually).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

export HOST_DATA_DIR="${HOST_DATA_DIR:-$ROOT/data}"
export DOCKER_SOCK="${DOCKER_SOCK:-/var/run/docker.sock}"
export SOURCEPROOF_COMPOSE_FILE="${SOURCEPROOF_COMPOSE_FILE:-docker-compose.fast.yml}"
export SOURCEPROOF_FORCE_BUILD="${SOURCEPROOF_FORCE_BUILD:-1}"

echo "==> Deploying SourceProof from $ROOT"
echo "==> Host data dir: $HOST_DATA_DIR"
echo "==> Compose file: $SOURCEPROOF_COMPOSE_FILE"

mkdir -p "$ROOT/data/sources" "$ROOT/data/pglite"

if ! docker info >/dev/null 2>&1; then
  echo "ERROR: Docker daemon is not running."
  exit 1
fi

echo "==> Building API image…"
docker compose -f "$SOURCEPROOF_COMPOSE_FILE" build api

echo "==> Building pinned builder image (required for verifications)…"
docker compose -f docker-compose.yml --profile builder build builder

echo "==> Restarting API container…"
docker compose -f "$SOURCEPROOF_COMPOSE_FILE" up -d --force-recreate api

echo "==> Waiting for health…"
for attempt in $(seq 1 45); do
  if curl -sf "http://127.0.0.1:8080/health" >/dev/null 2>&1; then
    echo "✓ SourceProof is healthy (attempt $attempt)"
    docker compose -f "$SOURCEPROOF_COMPOSE_FILE" ps
    exit 0
  fi
  sleep 2
done

echo "ERROR: Health check failed after 90s"
docker compose -f "$SOURCEPROOF_COMPOSE_FILE" logs --tail=80 api
exit 1
