from __future__ import annotations

from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "SourceProof"
    api_host: str = "0.0.0.0"
    api_port: int = 8080
    # Demo default: PGlite (Postgres-compatible). Override with sqlite:/// for tests.
    database_url: str = "postgresql+psycopg://postgres:postgres@pglite:5432/postgres"
    storage_dir: str = "./data/sources"
    builder_image: str = "soroban-verify-builder:local"
    builder_network_disabled: bool = True
    # Docker-out-of-docker: when the API runs in a container and shells out to the
    # host Docker daemon, bind-mount paths are resolved on the HOST, not inside this
    # container. host_data_dir is the host path that maps to container_data_root,
    # so build work dirs (under the shared data volume) can be mounted into builds.
    host_data_dir: Optional[str] = Field(default=None, validation_alias="HOST_DATA_DIR")
    container_data_root: str = Field(default="/app/data", validation_alias="CONTAINER_DATA_ROOT")
    build_timeout_seconds: int = 300
    max_tarball_bytes: int = 50 * 1024 * 1024
    # Abuse/DoS protection for write endpoints (per client IP, sliding window).
    verify_rate_limit: int = Field(default=10, validation_alias="VERIFY_RATE_LIMIT")
    verify_rate_window_seconds: int = Field(default=60, validation_alias="VERIFY_RATE_WINDOW_SECONDS")
    verifier_instance_id: str = "local-verifier-1"
    stellar_cli_version: str = "23.0.0"
    docker_image_digest: str = "local"
    # Demo only: seed one sample contract with two divergent verifier records so
    # the multi-verifier divergence panel is demonstrable without live federation.
    # Off by default; the demo compose turns it on. Never enable in production.
    seed_demo_divergence: bool = Field(default=False, validation_alias="SEED_DEMO_DIVERGENCE")

    # Testnet/futurenet: SDF public RPC. Mainnet: no SDF public RPC — use a provider URL below.
    rpc_urls: dict[str, str] = {
        "testnet": "https://soroban-testnet.stellar.org",
        "mainnet": "https://soroban-rpc.mainnet.stellar.gateway.fm",
        "futurenet": "https://rpc-futurenet.stellar.org",
    }
    rpc_url_testnet: Optional[str] = Field(default=None, validation_alias="RPC_URL_TESTNET")
    rpc_url_mainnet: Optional[str] = Field(default=None, validation_alias="RPC_URL_MAINNET")
    rpc_url_futurenet: Optional[str] = Field(default=None, validation_alias="RPC_URL_FUTURENET")

    def host_path_for(self, container_path: str) -> str:
        """Translate a container path under container_data_root to the host path
        the Docker daemon can mount. Returns the input unchanged when no mapping
        is configured (e.g. the API runs natively on the host)."""
        if not self.host_data_dir:
            return container_path
        from pathlib import Path

        root = Path(self.container_data_root).resolve()
        target = Path(container_path).resolve()
        try:
            relative = target.relative_to(root)
        except ValueError:
            return container_path
        return str(Path(self.host_data_dir) / relative)

    def rpc_url_for(self, network: str) -> str | None:
        overrides = {
            "testnet": self.rpc_url_testnet,
            "mainnet": self.rpc_url_mainnet,
            "futurenet": self.rpc_url_futurenet,
        }
        override = overrides.get(network)
        if override:
            return override
        return self.rpc_urls.get(network)

    network_passphrases: dict[str, str] = {
        "testnet": "Test SDF Network ; September 2015",
        "mainnet": "Public Global Stellar Network ; September 2015",
        "futurenet": "Test SDF Future Network ; October 2022",
    }


settings = Settings()
