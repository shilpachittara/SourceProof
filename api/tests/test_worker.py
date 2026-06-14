from __future__ import annotations

from pathlib import Path

import pytest

from app import database
from app.builder import BuildResult
from app.storage import validate_and_store_tarball
from app.worker import process_verification
from tests.helpers import WASM_HASH_A, WASM_HASH_B, make_source_tarball


def _create_pending_record(expected_hash: str) -> str:
    data = make_source_tarball()
    content_hash, stored_path = validate_and_store_tarball(data)
    verification_id = database.new_verification_id()

    db = database.SessionLocal()
    assert db is not None
    db.add(
        database.Verification(
            id=verification_id,
            network="testnet",
            contract_id="CTEST123",
            wasm_hash=expected_hash,
            status=database.VerificationStatus.PENDING.value,
            trust_level="sep58_rebuild",
            tarball_content_hash=content_hash,
            source_path=str(stored_path),
            verifier_instance_id="test-verifier",
            created_at=database.utcnow(),
        )
    )
    db.commit()
    db.close()
    return verification_id


def test_process_verification_verified(isolated_env, monkeypatch: pytest.MonkeyPatch) -> None:
    verification_id = _create_pending_record(WASM_HASH_A)

    def fake_build(
        source_dir: Path,
        output_dir: Path,
        image: str | None = None,
        bldopt: str | None = None,
    ) -> BuildResult:
        return BuildResult(
            wasm_bytes=b"\x00asm",
            wasm_hash=WASM_HASH_A,
            build_metadata={"docker_image": "test"},
        )

    monkeypatch.setattr("app.worker.build_contract", fake_build)

    process_verification(verification_id, use_docker=True)

    db = database.SessionLocal()
    record = db.get(database.Verification, verification_id)
    assert record is not None
    assert record.status == database.VerificationStatus.VERIFIED.value
    assert record.built_wasm_hash == WASM_HASH_A
    db.close()


def test_worker_forwards_bldopt_to_builder(isolated_env, monkeypatch: pytest.MonkeyPatch) -> None:
    verification_id = _create_pending_record(WASM_HASH_A)
    captured: dict[str, str | None] = {}

    def fake_build(
        source_dir: Path,
        output_dir: Path,
        image: str | None = None,
        bldopt: str | None = None,
    ) -> BuildResult:
        captured["bldopt"] = bldopt
        return BuildResult(
            wasm_bytes=b"\x00asm",
            wasm_hash=WASM_HASH_A,
            build_metadata={"docker_image": "test", "applied_bldopt": bldopt or ""},
        )

    monkeypatch.setattr("app.worker.build_contract", fake_build)

    db = database.SessionLocal()
    record = db.get(database.Verification, verification_id)
    assert record is not None
    record.bldopt = "--package counter"
    db.commit()
    db.close()

    process_verification(verification_id, use_docker=True)
    assert captured["bldopt"] == "--package counter"


def test_process_verification_mismatch(isolated_env, monkeypatch: pytest.MonkeyPatch) -> None:
    verification_id = _create_pending_record(WASM_HASH_A)

    def fake_build(
        source_dir: Path,
        output_dir: Path,
        image: str | None = None,
        bldopt: str | None = None,
    ) -> BuildResult:
        return BuildResult(
            wasm_bytes=b"\x00asm-other",
            wasm_hash=WASM_HASH_B,
            build_metadata={"docker_image": "test"},
        )

    monkeypatch.setattr("app.worker.build_contract", fake_build)

    process_verification(verification_id, use_docker=True)

    db = database.SessionLocal()
    record = db.get(database.Verification, verification_id)
    assert record is not None
    assert record.status == database.VerificationStatus.MISMATCH.value
    assert record.expected_wasm_hash == WASM_HASH_A
    assert record.built_wasm_hash == WASM_HASH_B
    db.close()


def test_process_verification_build_failed(isolated_env, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.builder import BuildError

    verification_id = _create_pending_record(WASM_HASH_A)

    def fake_build(
        source_dir: Path,
        output_dir: Path,
        image: str | None = None,
        bldopt: str | None = None,
    ) -> BuildResult:
        raise BuildError("compile failed")

    monkeypatch.setattr("app.worker.build_contract", fake_build)

    process_verification(verification_id, use_docker=True)

    db = database.SessionLocal()
    record = db.get(database.Verification, verification_id)
    assert record is not None
    assert record.status == database.VerificationStatus.FAILED.value
    assert "compile failed" in (record.error_message or "")
    db.close()
