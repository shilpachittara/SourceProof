.PHONY: start start-fast demo demo-native down logs package-example test install-docker-cli testnet-samples testnet-env testnet-demo verified-demo deploy-contract demo-local-native dev-api builder build run ec2

# --- Portable build/run (works on macOS + Linux/EC2) ---------------------------
# Build all images needed for a working demo (API + UI image, and the pinned
# builder image used to rebuild contracts during verification).
build:
	docker compose -f docker-compose.fast.yml build api
	docker compose --profile builder build builder

# Start the stack (API + UI on :8080). Auto-detects the Docker socket and the
# host data dir, so docker-out-of-docker contract builds work everywhere.
run:
	./scripts/start-fast.sh

# One command for a fresh machine (e.g. AWS EC2): build images, then run.
ec2: build run

# Default: API + UI + PGlite (skips rebuild if images cached)
start:
	./scripts/start.sh

# Fastest: single API container + SQLite (~seconds after first image build)
start-fast:
	./scripts/start-fast.sh

demo: start
demo-fast: start-fast

test:
	cd api && python3 -m venv .venv 2>/dev/null || true; \
	. .venv/bin/activate && pip install -q -r requirements.txt && pytest -v

builder:
	@echo "Building pinned builder image (downloads prebuilt stellar-cli; ~1–2 min)…"
	docker compose --profile builder build builder

api:
	docker compose build api

up: start

demo-native:
	./scripts/start-demo-native.sh

demo-local-native:
	./scripts/demo-local-native.sh

install-docker-cli:
	./scripts/install-docker-cli-macos.sh

testnet-samples:
	./scripts/testnet/00-package-samples.sh

testnet-env:
	./scripts/testnet/setup-env.sh

testnet-demo:
	./scripts/testnet/run-demo.sh

# Build Wasm in the builder image, deploy to testnet, package the matching
# tarball — produces a contract that verifies as VERIFIED. Needs Stellar CLI.
verified-demo:
	./scripts/testnet/build-deploy-verify.sh

# Deploy a contract (default examples/demo-contract) and produce its matching
# tarball, so uploading that tarball in the UI verifies as VERIFIED.
#   make deploy-contract
#   CONTRACT_DIR=examples/hello-world make deploy-contract
deploy-contract:
	./scripts/deploy-contract.sh

down:
	docker compose -f docker-compose.yml -f docker-compose.fast.yml down --remove-orphans 2>/dev/null || docker compose down

logs:
	docker compose logs -f api

package-example:
	./scripts/package-example.sh

dev-api:
	cd api && python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt && uvicorn app.main:app --reload --port 8080
