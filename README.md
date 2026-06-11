# SourceProof

<p align="center">
  <img src="demo/ui/logo-mark.svg" alt="SourceProof" width="72" height="72" />
</p>

<p align="center">
  <strong>Prove deployed Soroban Wasm was built from the source you publish.</strong><br />
  Verify once — explorers and wallets lookup the proof via API.
</p>

**SourceProof** is an open-source contract source verification service for **Soroban** smart contracts on **Stellar**. Submit Rust source (tarball upload, GitHub snapshot, hosted URL, IPFS gateway, or content-addressed hash), rebuild in a **pinned Docker builder**, and compare the result to bytecode already on chain. On success, store a **`verified`** record with downloadable source and build metadata.

> **Status:** v0.2.0 — demo / prototype for testnet and RFP review. Not production mainnet infrastructure.

> **Live demo:** [https://sourceproof.upthrust.club/demo/](https://sourceproof.upthrust.club/demo/) — submit (upload / folder / GitHub / URL+IPFS / hash-only), look up a contract, and browse the verification registry against testnet/mainnet.

---

## Why this exists

Blockchains store compiled **Wasm**, not human-readable **source**. Users, auditors, and explorers need a standard way to trust that on-chain code matches a published Rust project.

| Step | Who | What happens |
|------|-----|----------------|
| 1. Deploy | Developer (**outside SourceProof**) | Contract Wasm on testnet/mainnet (`contract_id`) |
| 2. Verify | SourceProof UI or API | Submit source → service rebuilds → hash matches chain |
| 3. Lookup | Explorer / wallet | `GET /v1/{network}/contracts/{id}` — **no rebuild**, read proof |

**SourceProof does not deploy contracts.** You deploy with Stellar CLI / Lab / your CI, then paste `contract_id` into the demo UI.

---

## How it works

```
  Rust source (.tar.gz)
        │
        ├─► Pinned builder (Docker) ──► rebuilt Wasm ──► SHA-256
        │
        └─► Testnet RPC ──► on-chain Wasm for contract_id ──► SHA-256

        hashes equal  →  verified
        hashes differ →  mismatch
```

| Component | Role |
|-----------|------|
| **Demo UI** | Submit, lookup, registry |
| **API** | Store tarball, fetch chain Wasm, orchestrate jobs, serve lookup |
| **Builder image** | Reproducible compile (same toolchain every time) |

**Why Docker?** The API and UI do not compile contracts. Docker provides a **fixed build environment** so “same source” always means “same Wasm bytes” — otherwise different Rust/CLI versions on different machines cause false mismatches. See [Why the builder is separate from the API](#why-the-builder-is-separate-from-the-api).

---

## Architecture

```
Developer → POST /v1/verify (source + contract_id + network)
         → Worker rebuilds in pinned Docker image
         → Compare Wasm hash to on-chain bytecode
         → GET /v1/{network}/contracts/{id}  (explorers — no rebuild)
```

---

## Quick start

### Prerequisites

**Option A — Docker (recommended for verifications)**

- Docker CLI + Compose (`docker compose version` must work)
- macOS: [Install via CLI](#install-docker-via-cli-macos) (Colima + Homebrew — no Docker Desktop website)
- 8GB+ RAM for first **builder** image build (~10–30 min once)

**Option B — Native (no Docker)**

- Python 3.10+
- [Rust](https://rustup.rs) + `rustup target add wasm32v1-none`
- [Stellar CLI](https://developers.stellar.org/docs/tools/developer-tools/cli/install-cli)

### Start the stack

```bash
cd soroban-verify
chmod +x scripts/*.sh scripts/testnet/*.sh

make start-fast    # fastest: API + UI, SQLite (~5–15 s after first build)
# or
make start         # API + UI + PGlite
```

| Command | What starts |
|---------|-------------|
| `make start-fast` | Single container, SQLite |
| `make start` | API + UI + PGlite (`./data/pglite`) |
| `make builder` | Pinned compile image only (run before first verification) |
| `make down` | Stop containers |
| `make logs` | Follow API logs |

`make demo` is an alias for `make start`.

Force image rebuild: `SOURCEPROOF_FORCE_BUILD=1 make start`

| URL | Purpose |
|-----|---------|
| http://127.0.0.1:8080/demo/ | **SourceProof UI** — submit, lookup, registry |
| http://127.0.0.1:8080/docs | OpenAPI |
| http://127.0.0.1:8080/health | Health check |

---

## Deploy on a server (AWS EC2 / any Linux)

The stack is portable — the same images and scripts run on Linux. On a fresh EC2:

```bash
# 1. Install Docker + Compose plugin + git, add your user to the docker group
sudo apt-get update && sudo apt-get install -y docker.io docker-compose-plugin git curl
sudo usermod -aG docker "$USER" && newgrp docker

# 2. Clone and enter the repo
git clone <your-repo-url> && cd soroban-verify

# 3. Build images, then run
make build      # builds API image + pinned builder image (~2-4 min)
make run        # starts API + UI on :8080
```

Open `http://<EC2_PUBLIC_IP>:8080/demo/` (open port 8080 in the security group).

**Custom domain + free HTTPS (nginx + Let's Encrypt):** see [deploy/nginx/README.md](deploy/nginx/README.md) (e.g. `sourceproof.upthrust.club`).

**CI/CD (auto-deploy on push to `main`):** see [deploy/ec2/README.md](deploy/ec2/README.md) — GitHub Actions → AWS EC2 over SSH.

**How it stays identical to local:** `make run` auto-detects the Docker socket and
sets `HOST_DATA_DIR` so contract builds (which shell out to the host Docker daemon)
bind-mount correctly. On native Linux Docker this resolves directly; no Colima/VM
quirks. To run with raw `docker compose`, run it from the repo root so `${PWD}/data`
resolves:

```bash
docker compose -f docker-compose.fast.yml up -d --build
```

Single command for a new box: `make ec2` (= `make build` + `make run`).

---

## Demo: deploy a contract, then verify it (two steps)

A clean, self-contained demo contract lives at `examples/demo-contract/` (a Soroban
counter). One command deploys it **and** produces the matching tarball:

```bash
make builder            # once (~1-2 min)
make run                # API + UI up

# Step 1 — deploy + package matching tarball (prints CONTRACT_ID + tarball path)
make deploy-contract
```

```bash
# Step 2 — verify (UI: http://localhost:8080/demo/ → Upload tab)
#   network=testnet, contract_id=<printed>, file=examples/demo-contract-source.tar.gz
# → status: verified
```

`deploy-contract` builds the Wasm **inside the pinned builder image**, captures the
resolved `Cargo.lock`, packages `examples/demo-contract-source.tar.gz`, then deploys
those exact bytes — so the upload always matches. Use your own contract with
`CONTRACT_DIR=examples/hello-world make deploy-contract`.

---

## Build the correct `.tar.gz` (so it verifies)

A contract verifies as `verified` **only** when the on-chain Wasm was built by the
**same pinned builder image** the verifier uses. The tarball must contain the Rust
project rooted at `Cargo.toml`, **including `Cargo.lock`** (so dependency versions
match exactly), and exclude `target/`.

**One command does build + deploy + package + (ready to) verify:**

```bash
make builder            # once
make run                # API + UI up
make verified-demo      # builds Wasm in builder image, deploys to testnet,
                        # packages examples/hello-world-source.tar.gz,
                        # prints a CONTRACT_ID that verifies as VERIFIED
```

**Manual recipe (any contract):**

```bash
# 1. Build Wasm with the pinned builder (NOT your local toolchain)
rm -rf tmp/b && mkdir -p tmp/b/src tmp/b/out
tar -xzf examples/hello-world-source.tar.gz -C tmp/b/src   # or your own source
docker run --rm -v "$PWD/tmp/b/src:/source:ro" \
  -v "$PWD/tmp/b/out:/output" soroban-verify-builder:local

# 2. Deploy THOSE EXACT bytes (deploy uploads the file as-is)
stellar contract deploy --wasm tmp/b/out/contract.wasm --source deployer --network testnet

# 3. Package the matching source (includes Cargo.lock automatically)
make package-example     # → examples/hello-world-source.tar.gz

# 4. Verify in UI/API with that tarball + the contract ID → verified
```

**Tarball rules:**

- Root the archive at the workspace `Cargo.toml` (so `stellar contract build` works).
- Always include `Cargo.lock` (pins deps — `package-example.sh` does this).
- Exclude `target/` and `.git`.
- The deployed Wasm must come from the **builder image**, or it will `mismatch`.

---

## Testnet demo (UI — verify & lookup)

**1. Deploy on testnet yourself** (Stellar CLI, Lab, etc.). Copy the contract ID (`C…`).

**2. Terminal 1** — start SourceProof:

```bash
make start-fast    # or make start
make builder       # first time only — for verification rebuilds (not deploy)
```

**3. Browser** — http://127.0.0.1:8080/demo/

| Step | UI tab | Action |
|------|--------|--------|
| Verify | **Upload** | Network `testnet`, your `CONTRACT_ID`, `hello-world-source.tar.gz` (if it matches deployed Wasm) → **verified** |
| Lookup | **Lookup** | Same contract ID → `freshness: current` |
| Proof | **Registry** | Download source tarball |

Package sample source:

```bash
make package-example    # → examples/hello-world-source.tar.gz
```

**4. Explorer GET** (after verify):

```bash
curl -s "http://127.0.0.1:8080/v1/testnet/contracts/C..." | python3 -m json.tool
```

**Optional — automated scenario scripts:**

```bash
make testnet-env        # creates .env.testnet — set CONTRACT_ID=
make testnet-samples
make testnet-demo       # S01–S10 (needs CONTRACT_ID in .env.testnet)
```

### Sample source (not deployed by this repo)

| Asset | Purpose |
|-------|---------|
| `examples/hello-world/` | Example Rust project (reference / build locally yourself) |
| `examples/hello-world-source.tar.gz` | Tarball to upload if it matches your on-chain Wasm |
| `examples/mismatch-sample-source.tar.gz` | Demo **mismatch** |
| `examples/invalid-source.tar.gz` | Demo **failed** |

---

## Run without Docker (native)

If Docker is unavailable:

**Terminal 1:**

```bash
./scripts/start-demo-native.sh
```

**Terminal 2:**

```bash
./scripts/demo-local-native.sh
```

Submissions use `use_docker=false` (local `stellar` CLI). Prefer Docker builder for testnet **verified** demos when on-chain Wasm was built with the same toolchain.

---

## Install Docker via CLI (macOS)

```bash
./scripts/install-docker-cli-macos.sh
```

Installs Homebrew (if needed), Colima, Docker CLI, and Compose. The script configures `~/.docker/config.json` so `docker compose` finds Homebrew’s compose plugin.

If `docker compose` still fails after `brew install docker-compose`, add to `~/.docker/config.json`:

```json
{
  "cliPluginsExtraDirs": ["/opt/homebrew/lib/docker/cli-plugins"]
}
```

Then:

```bash
eval "$(/opt/homebrew/bin/brew shellenv)"
colima start
make start
make builder
```

---

## Why the builder is separate from the API

| Piece | Runs in | Job |
|-------|---------|-----|
| API + UI | `make start` / native | HTTP, DB, RPC, job queue |
| Builder | `make builder` + verify worker | `stellar contract build` in pinned image |

Startup **does not** build the builder by default (keeps `make start` fast). Run `make builder` once before your first verification (`POST /v1/verify` or UI submit with Docker builds).

---

## Verify manually (curl)

Package source:

```bash
make package-example
# → examples/hello-world-source.tar.gz
```

Submit (contract already on testnet):

```bash
curl -X POST http://127.0.0.1:8080/v1/verify \
  -F network=testnet \
  -F contract_id=C... \
  -F source=@examples/hello-world-source.tar.gz \
  -F use_docker=true
```

Poll and lookup:

```bash
curl http://127.0.0.1:8080/v1/verifications/<verification_id>
curl http://127.0.0.1:8080/v1/testnet/contracts/C...
curl -O http://127.0.0.1:8080/v1/source/<tarball_content_hash>
```

Or use `./scripts/submit.sh` with `CONTRACT_ID` and `TARBALL` set.

---

## API endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/v1/verify` | Submit source (upload, GitHub, hosted/IPFS URL, hash-only) + `contract_id` or `wasm_hash` |
| `GET` | `/v1/verifications` | List verifications (registry) |
| `GET` | `/v1/verifications/{id}` | Poll job status |
| `GET` | `/v1/{network}/contracts/{id}` | Explorer lookup (verified; freshness vs live Wasm) |
| `GET` | `/v1/wasm/{hash}` | Lookup by Wasm hash |
| `GET` | `/v1/source/{content_hash}` | Download stored tarball |
| `GET` | `/health` | Health check |

**Input modes (SEP-58-style):** upload, GitHub (`github_url` + `git_ref`), hosted HTTPS URL, IPFS gateway URL, content-addressed `tarball_sha256` only.

**Trust level:** `sep58_rebuild` — rebuilt tarball equals on-chain Wasm. SEP-55 attestation (`sep55_attestation`) is a separate trust level for downstream UIs.

---

## Project layout

```
soroban-verify/
├── builder/                 # Pinned Docker image (stellar-cli + Rust)
├── api/                     # FastAPI verification service
├── demo/
│   ├── pglite/              # Local Postgres (optional stack)
│   └── ui/                  # Demo web UI
├── examples/
│   ├── hello-world/         # Sample Soroban contract
│   └── *-source.tar.gz      # Generated sample tarballs
├── scripts/
│   ├── testnet/             # Scenario scripts (S01–S10), setup-env
│   └── …                    # start, submit, package helpers
├── data/                    # DB + stored tarballs (gitignored)
└── docker-compose.yml
```

---

## Local development

```bash
make test                    # pytest (API)
make dev-api                 # uvicorn with reload (SQLite)
make builder                 # builder image for Docker verifications
```

API-only setup:

```bash
cd api
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
mkdir -p ../data/sources
export DATABASE_URL=sqlite:///../data/verify.db
export STORAGE_DIR=../data/sources
export BUILDER_IMAGE=soroban-verify-builder:local
uvicorn app.main:app --reload --port 8080
```

Build the builder image:

```bash
docker build -t soroban-verify-builder:local ./builder
# or: make builder
```

---

## Demo checklist

- [ ] `make builder` completes; same tarball rebuilds to identical Wasm twice
- [ ] Testnet contract deployed externally; `CONTRACT_ID` verified in UI
- [ ] POST `/v1/verify` → `verified` when source matches
- [ ] Wrong tarball → `mismatch`
- [ ] GET `/v1/testnet/contracts/{id}` → metadata + `freshness: current` + source URL
- [ ] Explorer path needs GET only (no rebuild)

---

## Makefile reference

| Target | Description |
|--------|-------------|
| `start` / `demo` | API + UI + PGlite |
| `start-fast` / `demo-fast` | API + UI only (SQLite) |
| `builder` | Build pinned compile image |
| `down` | Stop stack |
| `test` | Run API tests |
| `testnet-samples` | Package demo tarballs |
| `testnet-env` | Create `.env.testnet` (set `CONTRACT_ID` manually) |
| `testnet-demo` | Run scenario scripts S01–S10 |
| `install-docker-cli` | macOS Colima + Docker setup |
| `demo-native` | API + UI without Docker |
| `package-example` | `hello-world-source.tar.gz` |

---

## License

Apache-2.0 (recommended for Stellar ecosystem alignment)
