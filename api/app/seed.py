"""Demo-only seed data.

Inserts a single sample contract with two *divergent* verifier records (one
``verified``, one ``mismatch``) so the multi-verifier divergence panel in the
demo UI is clickable without standing up real cross-operator federation (that
is the M2 milestone). Gated behind ``SEED_DEMO_DIVERGENCE`` and never enabled
in production. The contract ID is an obviously-synthetic sample, not a real
on-chain deployment.
"""

from __future__ import annotations

import hashlib
import logging
import tarfile
from io import BytesIO

from app import database
from app.config import settings
from app.storage import validate_and_store_tarball

logger = logging.getLogger(__name__)

# Synthetic, clearly-labelled sample (not a real on-chain contract). 56 chars.
DEMO_DIVERGENCE_CONTRACT_ID = "CDEMODIVERGENCE" + "A" * 41

_ONCHAIN_WASM_HASH = hashlib.sha256(b"sourceproof-demo-divergence-onchain").hexdigest()
_DIVERGENT_BUILD_HASH = hashlib.sha256(b"sourceproof-demo-divergence-mismatch").hexdigest()


def _sample_tarball() -> bytes:
    """A minimal but valid Rust source tarball (needs a Cargo.toml to validate)."""
    buf = BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, content in (
            (
                "Cargo.toml",
                '[package]\nname = "sample-token"\nversion = "0.1.0"\nedition = "2021"\n',
            ),
            (
                "src/lib.rs",
                "#![no_std]\n// SourceProof divergence demo — sample source.\n",
            ),
        ):
            data = content.encode()
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            tar.addfile(info, BytesIO(data))
    return buf.getvalue()


def seed_demo_divergence() -> bool:
    """Idempotently seed the divergence sample. Returns True if records were added."""
    session = database.SessionLocal()
    try:
        existing = (
            session.query(database.Verification)
            .filter(
                database.Verification.network == "testnet",
                database.Verification.contract_id == DEMO_DIVERGENCE_CONTRACT_ID,
            )
            .count()
        )
        if existing:
            return False

        content_hash, stored_path = validate_and_store_tarball(_sample_tarball())
        now = database.utcnow()

        verified = database.Verification(
            id=database.new_verification_id(),
            network="testnet",
            contract_id=DEMO_DIVERGENCE_CONTRACT_ID,
            wasm_hash=_ONCHAIN_WASM_HASH,
            status=database.VerificationStatus.VERIFIED.value,
            trust_level="sep58_rebuild",
            tarball_content_hash=content_hash,
            source_path=str(stored_path),
            source_origin="github",
            source_repo="https://github.com/example/sample-token",
            source_commit="a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0",
            builder_image=settings.builder_image,
            build_metadata={
                "docker_image": settings.builder_image,
                "docker_image_digest": settings.docker_image_digest,
                "stellar_cli_version": "23.0.0",
                "rustc_version": "1.89.0",
                "build_profile": "release",
            },
            verifier_instance_id="sdf-verifier",
            created_at=now,
            verified_at=now,
        )

        mismatch = database.Verification(
            id=database.new_verification_id(),
            network="testnet",
            contract_id=DEMO_DIVERGENCE_CONTRACT_ID,
            wasm_hash=_ONCHAIN_WASM_HASH,
            status=database.VerificationStatus.MISMATCH.value,
            trust_level="sep58_rebuild",
            tarball_content_hash=content_hash,
            source_path=str(stored_path),
            source_origin="github",
            source_repo="https://github.com/example/sample-token",
            source_commit="a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0",
            builder_image="stellar/stellar-cli:22.0.0",
            expected_wasm_hash=_ONCHAIN_WASM_HASH,
            built_wasm_hash=_DIVERGENT_BUILD_HASH,
            build_metadata={
                "docker_image": "stellar/stellar-cli:22.0.0",
                "docker_image_digest": "sha256:2200c0de2200c0de2200c0de2200c0de2200c0de2200c0de2200c0de2200c0de",
                "stellar_cli_version": "22.0.0",
                "rustc_version": "1.84.0",
                "build_profile": "release",
                "mismatch_reason": "toolchain delta — rebuilt with an older soroban-sdk; bytecode differs",
            },
            verifier_instance_id="community-verifier",
            created_at=now,
            verified_at=now,
        )

        session.add_all([verified, mismatch])
        session.commit()
        logger.info("Seeded demo divergence sample contract %s", DEMO_DIVERGENCE_CONTRACT_ID)
        return True
    finally:
        session.close()
