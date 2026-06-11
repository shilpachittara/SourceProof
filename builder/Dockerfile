# Pinned deterministic builder for Soroban contract verification.
# Rebuild this image when bumping toolchain versions; record digest in build_metadata.

FROM rust:1.89-bookworm

ARG STELLAR_CLI_VERSION=23.0.0

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    pkg-config \
    libssl-dev \
    libdbus-1-dev \
    libudev-dev \
    libusb-1.0-0-dev \
    && rm -rf /var/lib/apt/lists/*

RUN rustup target add wasm32v1-none

# Install the Stellar CLI from a prebuilt release binary (fast — avoids a ~20–30 min
# `cargo install` compile). Falls back to cargo install if the download fails.
RUN set -eux; \
    arch="$(uname -m)"; \
    case "$arch" in \
      aarch64|arm64) target="aarch64-unknown-linux-gnu" ;; \
      x86_64|amd64)  target="x86_64-unknown-linux-gnu" ;; \
      *) echo "unsupported arch: $arch" >&2; exit 1 ;; \
    esac; \
    url="https://github.com/stellar/stellar-cli/releases/download/v${STELLAR_CLI_VERSION}/stellar-cli-${STELLAR_CLI_VERSION}-${target}.tar.gz"; \
    if curl -fsSL "$url" -o /tmp/stellar-cli.tar.gz; then \
      tar -xzf /tmp/stellar-cli.tar.gz -C /usr/local/bin stellar; \
      rm -f /tmp/stellar-cli.tar.gz; \
    else \
      echo "Prebuilt download failed; compiling from source"; \
      cargo install stellar-cli --version "${STELLAR_CLI_VERSION}" --locked; \
    fi; \
    stellar --version

WORKDIR /source

COPY build.sh /usr/local/bin/soroban-build.sh
RUN chmod +x /usr/local/bin/soroban-build.sh

ENV STELLAR_CLI_VERSION=${STELLAR_CLI_VERSION}

ENTRYPOINT ["/usr/local/bin/soroban-build.sh"]
