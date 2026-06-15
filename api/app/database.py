from __future__ import annotations

import hashlib
import re
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Generator, Optional

from sqlalchemy import JSON, DateTime, String, Text, create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from app.allowlist import evaluate_build_image

_BLDOPT_PACKAGE = re.compile(r"--package\s+(\S+)")
_BLDOPT_MANIFEST = re.compile(r"--manifest-path\s+(\S+)")
from app.config import settings

_engine: Optional[Engine] = None
SessionLocal: Any = None


class VerificationStatus(str, Enum):
    PENDING = "pending"
    VERIFIED = "verified"
    MISMATCH = "mismatch"
    FAILED = "failed"


class TrustLevel(str, Enum):
    """Distinct trust levels the API can record and distinguish.

    - SEP58_REBUILD: byte-for-byte rebuild of submitted source matches on-chain
      Wasm in an SDF-allowlisted image (what this service produces).
    - SEP55_ATTESTATION: a signed build attestation (CI provenance) recorded
      alongside, a *different* and weaker/complementary signal. Coexists with,
      and is distinguished from, the rebuild result.
    """

    SEP58_REBUILD = "sep58_rebuild"
    SEP55_ATTESTATION = "sep55_attestation"


# Map our internal source origin to the SEP-58 source identifier mode.
SEP58_MODE = {
    "github": "source_repo",
    "url": "tarball_url",
    "ipfs": "tarball_url",
    "content-addressed": "tarball_sha256",
    "upload": "upload",
}


class Base(DeclarativeBase):
    pass


class Verification(Base):
    __tablename__ = "verifications"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    network: Mapped[str] = mapped_column(String(32), index=True)
    contract_id: Mapped[Optional[str]] = mapped_column(String(128), index=True, nullable=True)
    wasm_hash: Mapped[str] = mapped_column(String(128), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    trust_level: Mapped[str] = mapped_column(String(32), default="sep58_rebuild")
    tarball_content_hash: Mapped[str] = mapped_column(String(128))
    source_path: Mapped[str] = mapped_column(String(512))
    source_origin: Mapped[str] = mapped_column(String(32), default="upload")
    source_repo: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    source_commit: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    build_metadata: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    onchain_meta: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    builder_image: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    bldopt: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    expected_wasm_hash: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    built_wasm_hash: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    verifier_instance_id: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


def make_engine(database_url: str | None = None) -> Engine:
    url = database_url or settings.database_url
    connect_args: dict = {}
    if url.startswith("sqlite"):
        connect_args = {"check_same_thread": False}
    elif "pglite" in url or url.startswith("postgresql"):
        # PGlite / local Postgres do not use SSL
        connect_args = {"sslmode": "disable"}
    return create_engine(url, connect_args=connect_args, pool_pre_ping=True)


def init_db(database_url: str | None = None, *, reset: bool = False) -> None:
    global _engine, SessionLocal

    if reset or _engine is None:
        _engine = make_engine(database_url)
        SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False)

    assert _engine is not None
    Base.metadata.create_all(bind=_engine)


def get_engine() -> Engine:
    if _engine is None:
        init_db()
    assert _engine is not None
    return _engine


def get_db() -> Generator[Session, None, None]:
    if SessionLocal is None:
        init_db()
    assert SessionLocal is not None
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def new_verification_id() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def infer_metadata_source(record: Verification) -> str:
    """Whether SEP-58 build fields were read from chain or supplied by submitter."""
    meta = record.onchain_meta or {}
    if meta.get("bldimg") or meta.get("bldopt") or meta.get("source_repo"):
        return "onchain"
    return "supplied"


def infer_image_trust(record: Verification) -> str:
    """Trust tier for the builder image actually used on rebuild."""
    evaluated = evaluate_build_image(record.build_metadata)
    if not evaluated:
        return "other"
    if evaluated.get("sdf_trusted"):
        return "sdf"
    if evaluated.get("allowlisted"):
        return "allowlisted"
    return "other"


def parse_source_identity(bldopt: Optional[str]) -> Optional[dict[str, str]]:
    """Extract workspace contract identity from a SEP-58 bldopt string."""
    if not bldopt:
        return None
    package = _BLDOPT_PACKAGE.search(bldopt)
    manifest = _BLDOPT_MANIFEST.search(bldopt)
    if not package and not manifest:
        return None
    out: dict[str, str] = {}
    if package:
        out["package"] = package.group(1)
    if manifest:
        out["manifest_path"] = manifest.group(1)
    return out


def _trust_fields(record: Verification) -> dict[str, Any]:
    bldopt = record.bldopt or (record.onchain_meta or {}).get("bldopt")
    fields: dict[str, Any] = {
        "metadata_source": infer_metadata_source(record),
        "image_trust": infer_image_trust(record),
    }
    identity = parse_source_identity(bldopt)
    if identity:
        fields["source_identity"] = identity
    return fields


def _sep58_block(record: Verification, base_url: str) -> dict[str, Any]:
    """SEP-58 source-identifier fields, named per the spec vocabulary.

    The API distinguishes the source mode and surfaces exactly the SEP-58 fields
    that apply to it (the rest are null).
    """
    origin = record.source_origin or "upload"
    mode = SEP58_MODE.get(origin, "upload")
    meta = record.onchain_meta or {}

    is_repo = origin == "github"
    is_hosted = origin in ("url", "ipfs")
    return {
        "mode": mode,
        "channel": origin,  # github / url / ipfs / content-addressed / upload
        # bldimg: SEP-58 declared builder image read from the on-chain Wasm.
        "bldimg": meta.get("bldimg"),
        # The image the verifier actually rebuilt in (allowlisted).
        "builder_image_used": record.builder_image,
        "bldopt": record.bldopt or meta.get("bldopt"),
        "source_repo": record.source_repo if is_repo else None,
        "source_rev": record.source_commit if is_repo else None,
        "tarball_url": record.source_repo if is_hosted else None,
        "tarball_sha256": record.tarball_content_hash,
        "source_artifact_url": f"{base_url}/v1/source/{record.tarball_content_hash}",
    }


def aggregate_verifiers(
    records: list["Verification"], current_wasm_hash: Optional[str] = None
) -> dict[str, Any]:
    """Collapse many verifier records for one contract into a per-verifier signal.

    Hard RFP requirement: multiple independent verifiers each report against the
    deployed Wasm hash, and disagreement surfaces per-verifier — not a single
    "correct" status. Consumers pick a trusted set from `verifiers`.
    """
    latest_by_verifier: dict[str, Verification] = {}
    for r in records:
        key = r.verifier_instance_id or "unknown"
        prev = latest_by_verifier.get(key)
        ts = r.verified_at or r.created_at
        prev_ts = (prev.verified_at or prev.created_at) if prev else None
        if prev is None or (ts and prev_ts and ts > prev_ts):
            latest_by_verifier[key] = r

    verifiers = []
    for vid, r in latest_by_verifier.items():
        meta = r.build_metadata or {}
        matches = None if current_wasm_hash is None else r.wasm_hash == current_wasm_hash
        is_mismatch = r.status == VerificationStatus.MISMATCH.value
        freshness = None
        if r.status == VerificationStatus.VERIFIED.value and matches is not None:
            freshness = "current" if matches else "superseded"
        verifiers.append(
            {
                "verifier_instance_id": vid,
                "status": r.status,
                "trust_level": r.trust_level,
                "wasm_hash": r.wasm_hash,
                "built_wasm_hash": r.built_wasm_hash,
                "matches_current_chain": matches,
                "freshness": freshness,
                **_trust_fields(r),
                "verified_at": r.verified_at.isoformat() if r.verified_at else None,
                # explorer-friendly badge, e.g. "[√] Verified by local-verifier-1"
                "signal": _verifier_signal(r.status, vid),
                # Display-layer detail so a consumer can render the per-verifier
                # divergence panel from this one response (see RFP multi-verifier UX).
                "build_image": evaluate_build_image(r.build_metadata),
                "build_metadata": (
                    {
                        "docker_image": meta.get("docker_image"),
                        "docker_image_digest": meta.get("docker_image_digest"),
                        "stellar_cli_version": meta.get("stellar_cli_version"),
                        "rustc_version": meta.get("rustc_version"),
                        "build_profile": meta.get("build_profile"),
                    }
                    if r.build_metadata
                    else None
                ),
                "mismatch_reason": meta.get("mismatch_reason") if is_mismatch else None,
                "expected_wasm_hash": r.expected_wasm_hash if is_mismatch else None,
                "tarball_content_hash": r.tarball_content_hash,
            }
        )

    statuses = {v["status"] for v in verifiers}
    verified = {v for v in statuses if v == VerificationStatus.VERIFIED.value}
    if statuses == verified and verified:
        consensus = "verified"
    elif VerificationStatus.VERIFIED.value in statuses and (
        VerificationStatus.MISMATCH.value in statuses
    ):
        consensus = "divergent"
    elif statuses == {VerificationStatus.MISMATCH.value}:
        consensus = "mismatch"
    elif statuses <= {VerificationStatus.PENDING.value}:
        consensus = "pending"
    else:
        consensus = "mixed"

    return {
        "consensus": consensus,
        "verifier_count": len(verifiers),
        "verifiers": sorted(verifiers, key=lambda v: v["verifier_instance_id"]),
    }


def _verifier_signal(status: str, verifier_id: str) -> str:
    mark = {
        VerificationStatus.VERIFIED.value: "[\u221a] Verified by",
        VerificationStatus.MISMATCH.value: "[!] Mismatching verification by",
        VerificationStatus.FAILED.value: "[x] Verification failed at",
        VerificationStatus.PENDING.value: "[\u2026] Pending at",
    }.get(status, "[?]")
    return f"{mark} {verifier_id}"


def serialize_verification(
    record: Verification,
    base_url: str,
    *,
    current_wasm_hash: Optional[str] = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "verification_id": record.id,
        "network": record.network,
        "contract_id": record.contract_id,
        "status": record.status,
        "trust_level": record.trust_level,
        **_trust_fields(record),
        "wasm_hash": record.wasm_hash,
        "source": {
            "origin": record.source_origin,
            "repo_url": record.source_repo,
            "commit_sha": record.source_commit,
            "tarball_url": f"{base_url}/v1/source/{record.tarball_content_hash}",
            "tarball_content_hash": record.tarball_content_hash,
        },
        "source_tarball_url": f"{base_url}/v1/source/{record.tarball_content_hash}",
        "tarball_content_hash": record.tarball_content_hash,
        "build_metadata": record.build_metadata,
        "build_image": evaluate_build_image(record.build_metadata),
        "onchain_meta": record.onchain_meta or None,
        "verifier_instance_id": record.verifier_instance_id,
        "created_at": record.created_at.isoformat(),
        "verified_at": record.verified_at.isoformat() if record.verified_at else None,
    }
    payload["sep58"] = _sep58_block(record, base_url)
    if record.status == VerificationStatus.VERIFIED.value and current_wasm_hash is not None:
        if current_wasm_hash == record.wasm_hash:
            payload["freshness"] = "current"
        else:
            payload["freshness"] = "superseded"
            payload["current_wasm_hash"] = current_wasm_hash
    if record.status == VerificationStatus.MISMATCH.value:
        payload["expected_wasm_hash"] = record.expected_wasm_hash
        payload["built_wasm_hash"] = record.built_wasm_hash
    if record.status == VerificationStatus.FAILED.value and record.error_message:
        payload["error_message"] = record.error_message
    return payload
