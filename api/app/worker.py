"""Background verification worker."""

from __future__ import annotations

import logging
import shutil
import tempfile
import uuid
from pathlib import Path

from app import database
from app.build_meta import BuildMetaError, require_package_selector
from app.builder import BuildError, build_contract, build_contract_local
from app.config import settings
from app.storage import extract_tarball

logger = logging.getLogger(__name__)


def _session():
    if database.SessionLocal is None:
        database.init_db()
    assert database.SessionLocal is not None
    return database.SessionLocal()


def process_verification(verification_id: str, use_docker: bool = True) -> None:
    db = _session()
    record = db.get(database.Verification, verification_id)
    if not record:
        db.close()
        logger.error("Verification %s not found", verification_id)
        return

    # Build work dirs must live under the shared data volume so the Docker daemon
    # (possibly in a VM) can bind-mount them into the builder container.
    if settings.host_data_dir:
        work_root = Path(settings.container_data_root) / "work"
        work_root.mkdir(parents=True, exist_ok=True)
        workdir = work_root / uuid.uuid4().hex
        workdir.mkdir(parents=True, exist_ok=True)
    else:
        workdir = Path(tempfile.mkdtemp(prefix="verify-"))
    source_dir = workdir / "source"
    output_dir = workdir / "output"

    try:
        expected_hash = record.wasm_hash
        record.expected_wasm_hash = expected_hash
        db.commit()

        tarball_path = Path(record.source_path)
        extract_tarball(tarball_path, source_dir)

        bldarg = database.resolved_bldarg(record)

        try:
            require_package_selector(source_dir, bldarg)
        except BuildMetaError as exc:
            record.status = database.VerificationStatus.FAILED.value
            record.error_message = str(exc)
            record.verified_at = database.utcnow()
            db.commit()
            return

        try:
            if use_docker:
                result = build_contract(
                    source_dir,
                    output_dir,
                    image=record.builder_image,
                    bldopt=record.bldopt,
                    bldarg=bldarg,
                )
            else:
                result = build_contract_local(source_dir, output_dir)
        except BuildError as exc:
            record.status = database.VerificationStatus.FAILED.value
            record.error_message = str(exc)
            record.verified_at = database.utcnow()
            db.commit()
            return

        record.built_wasm_hash = result.wasm_hash
        metadata = dict(result.build_metadata)

        if result.wasm_hash == expected_hash:
            record.status = database.VerificationStatus.VERIFIED.value
        else:
            record.status = database.VerificationStatus.MISMATCH.value
            metadata["mismatch_reason"] = _explain_mismatch(record.onchain_meta, metadata)

        record.build_metadata = metadata

        record.verified_at = database.utcnow()
        db.commit()
        logger.info(
            "Verification %s finished status=%s expected=%s built=%s",
            verification_id,
            record.status,
            expected_hash,
            result.wasm_hash,
        )
    except Exception as exc:
        logger.exception("Verification %s failed", verification_id)
        record.status = database.VerificationStatus.FAILED.value
        record.error_message = str(exc)
        record.verified_at = database.utcnow()
        db.commit()
    finally:
        db.close()
        shutil.rmtree(workdir, ignore_errors=True)


def _explain_mismatch(onchain_meta: dict | None, build_metadata: dict) -> str:
    """Best-effort human reason why a rebuild did not byte-match the on-chain Wasm.

    Same *source* can produce different bytecode when the build environment
    differs. The on-chain Wasm records the toolchain it was built with, so we can
    point at the concrete divergence.
    """
    if not onchain_meta:
        return (
            "Rebuilt bytecode differs from the on-chain Wasm. The deployed contract "
            "did not embed build metadata, so the original toolchain is unknown — the "
            "most common cause is a different rustc / soroban-sdk version or build flags."
        )
    reasons: list[str] = []
    onchain_rsver = onchain_meta.get("rsver")
    onchain_sdk = onchain_meta.get("rssdkver")
    built_rustc = build_metadata.get("rustc_version", "")
    if onchain_rsver and onchain_rsver not in built_rustc:
        reasons.append(f"on-chain rustc {onchain_rsver} vs verifier {built_rustc or 'unknown'}")
    if onchain_sdk:
        reasons.append(f"on-chain soroban-sdk {onchain_sdk}")
    if onchain_meta.get("bldimg_allowlisted") == "false":
        reasons.append("declared bldimg is not on the SDF allowlist")
    if not reasons:
        return (
            "Rebuilt bytecode differs although toolchain metadata matches; check "
            "Cargo.lock, optimization flags, or workspace layout."
        )
    return "Toolchain/source divergence: " + "; ".join(reasons) + "."


def run_verification_task(verification_id: str, use_docker: bool = True) -> None:
    process_verification(verification_id, use_docker=use_docker)
