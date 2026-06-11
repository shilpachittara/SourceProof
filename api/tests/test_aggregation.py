from __future__ import annotations

from app import database
from app.database import VerificationStatus, aggregate_verifiers

ONCHAIN = "a" * 64


def _record(verifier_id: str, status: str, **kwargs) -> database.Verification:
    return database.Verification(
        id=database.new_verification_id(),
        network="testnet",
        contract_id="CDIVERGE1",
        wasm_hash=ONCHAIN,
        status=status,
        trust_level="sep58_rebuild",
        verifier_instance_id=verifier_id,
        created_at=database.utcnow(),
        verified_at=database.utcnow(),
        **kwargs,
    )


def test_divergent_consensus_exposes_per_verifier_detail(isolated_env) -> None:
    verified = _record(
        "sdf-verifier",
        VerificationStatus.VERIFIED.value,
        tarball_content_hash="t" * 64,
        build_metadata={
            "docker_image": database.settings.builder_image,
            "stellar_cli_version": "23.0.0",
            "rustc_version": "1.89.0",
        },
    )
    mismatch = _record(
        "expert-verifier",
        VerificationStatus.MISMATCH.value,
        built_wasm_hash="b" * 64,
        expected_wasm_hash=ONCHAIN,
        build_metadata={"docker_image": "evil/image:latest", "mismatch_reason": "toolchain delta"},
    )

    out = aggregate_verifiers([verified, mismatch], current_wasm_hash=ONCHAIN)

    assert out["consensus"] == "divergent"
    assert out["verifier_count"] == 2

    by_id = {v["verifier_instance_id"]: v for v in out["verifiers"]}

    sdf = by_id["sdf-verifier"]
    assert sdf["freshness"] == "current"
    assert sdf["build_metadata"]["stellar_cli_version"] == "23.0.0"
    assert sdf["tarball_content_hash"] == "t" * 64
    assert sdf["build_image"]["allowlisted"] is True

    expert = by_id["expert-verifier"]
    assert expert["mismatch_reason"] == "toolchain delta"
    assert expert["expected_wasm_hash"] == ONCHAIN
    assert expert["built_wasm_hash"] == "b" * 64
    assert expert["build_image"]["allowlisted"] is False


def test_seed_demo_divergence_creates_divergent_sample(isolated_env) -> None:
    from app.seed import DEMO_DIVERGENCE_CONTRACT_ID, seed_demo_divergence

    assert len(DEMO_DIVERGENCE_CONTRACT_ID) == 56
    assert seed_demo_divergence() is True
    # idempotent: a second call does not duplicate
    assert seed_demo_divergence() is False

    session = database.SessionLocal()
    try:
        records = (
            session.query(database.Verification)
            .filter(database.Verification.contract_id == DEMO_DIVERGENCE_CONTRACT_ID)
            .all()
        )
    finally:
        session.close()

    assert len(records) == 2
    out = aggregate_verifiers(records, current_wasm_hash=None)
    assert out["consensus"] == "divergent"
    assert {v["status"] for v in out["verifiers"]} == {"verified", "mismatch"}
