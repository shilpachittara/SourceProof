"""Service discovery payloads for health probes and API clients."""

from __future__ import annotations

from typing import Any

from app import allowlist
from app.config import settings


API_VERSION = "0.2.0"

FEATURES = [
    "sep58_rebuild",
    "idempotent_submit",
    "structured_errors",
    "contract_badge",
    "wasm_reverse_index",
    "multi_verifier_aggregation",
    "freshness_recheck",
]


def health_payload() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": settings.app_name,
        "api_version": API_VERSION,
        "verifier_instance_id": settings.verifier_instance_id,
        "builder_image": settings.builder_image,
        "networks": sorted(settings.rpc_urls.keys()),
        "database": "pglite" if "pglite" in settings.database_url else "other",
    }


def capabilities_payload() -> dict[str, Any]:
    images = allowlist.active_images()
    return {
        "service": settings.app_name,
        "api_version": API_VERSION,
        "verifier_instance_id": settings.verifier_instance_id,
        "networks": sorted(settings.rpc_urls.keys()),
        "features": FEATURES,
        "builder": {
            "default_image": settings.builder_image,
            "network_disabled": settings.builder_network_disabled,
            "allowlisted_images": [
                {
                    "name": img.name,
                    "digest": img.digest,
                    "stellar_cli_version": img.stellar_cli_version,
                    "sdf_trusted": img.sdf_trusted,
                    "deprecated_after": (
                        img.deprecated_after.isoformat() if img.deprecated_after else None
                    ),
                }
                for img in images
            ],
        },
        "limits": {
            "max_tarball_bytes": settings.max_tarball_bytes,
            "verify_rate_limit": settings.verify_rate_limit,
            "verify_rate_window_seconds": settings.verify_rate_window_seconds,
        },
    }
