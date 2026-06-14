from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Annotated, Optional

from contextlib import asynccontextmanager

import httpx
from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from app.config import settings
from app.database import (
    TrustLevel,
    Verification,
    VerificationStatus,
    aggregate_verifiers,
    get_db,
    init_db,
    new_verification_id,
    serialize_verification,
    utcnow,
)
from app.ratelimit import RateLimiter
from app.rpc import RpcError, fetch_wasm_bytes, fetch_wasm_hash, normalize_hash, sha256_hex
from app.sources import (
    SourceFetchError,
    fetch_content_addressed,
    fetch_from_github,
    fetch_hosted_tarball,
)
from app.storage import (
    TarballError,
    TarballTooLargeError,
    list_tarball_entries,
    read_source_tarball,
    validate_and_store_tarball,
    validate_content_hash,
)
from app.wasm_meta import (
    declared_bldopt,
    declared_build_image,
    declared_source_repo,
    declared_source_rev,
    parse_wasm_metadata,
)
from app import allowlist
from app.worker import run_verification_task

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def _demo_ui_dir() -> Path | None:
    api_root = Path(__file__).resolve().parent.parent
    for candidate in (api_root / "demo" / "ui", api_root.parent / "demo" / "ui"):
        if candidate.is_dir():
            return candidate
    return None


def _init_db_with_retry(max_attempts: int = 30, delay_seconds: float = 1.0) -> None:
    last_error: Exception | None = None
    for attempt in range(max_attempts):
        try:
            init_db(reset=True)
            logger.info("Database ready (attempt %s)", attempt + 1)
            return
        except Exception as exc:
            last_error = exc
            logger.warning("Database not ready (%s/%s): %s", attempt + 1, max_attempts, exc)
            time.sleep(delay_seconds)
    if last_error:
        raise last_error


@asynccontextmanager
async def lifespan(app: FastAPI):
    _init_db_with_retry()
    if settings.seed_demo_divergence:
        try:
            from app.seed import seed_demo_divergence

            seed_demo_divergence()
        except Exception as exc:  # noqa: BLE001 - demo seed must never block startup
            logger.warning("Demo divergence seed skipped: %s", exc)
    yield


FAVICON_URL = "/demo/logo.svg"

app = FastAPI(
    title=settings.app_name,
    version="0.2.0",
    description="SourceProof — Soroban contract source verification (sep58_rebuild)",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


_verify_limiter = RateLimiter(
    settings.verify_rate_limit, settings.verify_rate_window_seconds
)


def base_url(request: Request) -> str:
    return str(request.base_url).rstrip("/")


def _enforce_rate_limit(request: Request) -> None:
    client = request.client.host if request.client else "unknown"
    if not _verify_limiter.allow(client):
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded for verification submissions. Try again shortly.",
            headers={"Retry-After": str(_verify_limiter.retry_after(client))},
        )


def _optional(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


_demo_dir = _demo_ui_dir()
if _demo_dir is not None:
    app.mount("/demo", StaticFiles(directory=str(_demo_dir), html=True), name="demo-ui")
    logger.info("Demo UI mounted at /demo from %s", _demo_dir)


def _openapi_url(request: Request) -> str:
    root = request.scope.get("root_path", "").rstrip("/")
    return f"{root}{app.openapi_url}"


@app.get("/docs", include_in_schema=False)
async def swagger_docs(request: Request) -> HTMLResponse:
    return get_swagger_ui_html(
        openapi_url=_openapi_url(request),
        title=f"{settings.app_name} API",
        swagger_favicon_url=FAVICON_URL,
        swagger_ui_parameters=app.swagger_ui_parameters,
    )


@app.get("/redoc", include_in_schema=False)
async def redoc_docs(request: Request) -> HTMLResponse:
    return get_redoc_html(
        openapi_url=_openapi_url(request),
        title=f"{settings.app_name} API",
        redoc_favicon_url=FAVICON_URL,
    )


@app.get("/")
async def root() -> RedirectResponse:
    return RedirectResponse(url="/demo/")


@app.get("/health")
async def health() -> dict[str, str]:
    return {
        "status": "ok",
        "service": settings.app_name,
        "database": "pglite" if "pglite" in settings.database_url else "other",
    }


@app.get("/v1/verifications")
async def list_verifications(
    request: Request,
    status: Annotated[Optional[str], Query()] = None,
    network: Annotated[Optional[str], Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    db: Session = Depends(get_db),
) -> dict:
    query = db.query(Verification).order_by(Verification.created_at.desc())
    if status:
        query = query.filter(Verification.status == status.lower().strip())
    if network:
        query = query.filter(Verification.network == network.lower().strip())
    total = query.count()
    records = query.offset(offset).limit(limit).all()
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "verifications": [serialize_verification(r, base_url(request)) for r in records],
    }


@app.post("/v1/verify", status_code=202)
async def submit_verification(
    request: Request,
    background_tasks: BackgroundTasks,
    network: Annotated[str, Form()],
    source: Annotated[Optional[UploadFile], File()] = None,
    contract_id: Annotated[Optional[str], Form()] = None,
    wasm_hash: Annotated[Optional[str], Form()] = None,
    github_url: Annotated[Optional[str], Form()] = None,
    git_ref: Annotated[Optional[str], Form()] = None,
    # SEP-58 vocabulary aliases (integrates cleanly with stellar-cli / SEP-58):
    source_repo: Annotated[Optional[str], Form()] = None,
    source_rev: Annotated[Optional[str], Form()] = None,
    tarball_url: Annotated[Optional[str], Form()] = None,
    tarball_sha256: Annotated[Optional[str], Form()] = None,
    bldopt: Annotated[Optional[str], Form()] = None,
    use_docker: Annotated[bool, Form()] = True,
    db: Session = Depends(get_db),
) -> dict:
    _enforce_rate_limit(request)
    network = network.lower().strip()
    if network not in settings.rpc_urls:
        raise HTTPException(status_code=400, detail=f"Unsupported network: {network}")

    contract_id = _optional(contract_id)
    wasm_hash = _optional(wasm_hash)
    # Accept SEP-58 `source_repo`/`source_rev` as synonyms for github_url/git_ref.
    github_url = _optional(github_url) or _optional(source_repo)
    git_ref = _optional(git_ref) or _optional(source_rev) or "HEAD"
    tarball_url = _optional(tarball_url)
    tarball_sha256 = _optional(tarball_sha256)
    bldopt = _optional(bldopt)

    if not contract_id and not wasm_hash:
        raise HTTPException(status_code=400, detail="Provide contract_id or wasm_hash")

    # Resolve source via any SEP-58 mode, normalizing to one stored tarball.
    source_origin = "upload"
    source_repo = None
    source_commit = None
    tarball_bytes: bytes | None = None
    onchain_wasm: bytes | None = None
    expected_hash: str | None = None
    onchain_meta: dict[str, str] = {}

    has_explicit_source = bool(
        github_url or tarball_url or source is not None or tarball_sha256
    )

    if not has_explicit_source:
        if not contract_id:
            raise HTTPException(
                status_code=400,
                detail="Provide a source input or contract_id with on-chain source_repo metadata",
            )
        try:
            expected_hash, onchain_wasm = await fetch_wasm_hash(network, contract_id, wasm_hash)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RpcError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=502,
                detail=f"Cannot reach Soroban RPC for {network}: {exc}",
            ) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        onchain_meta = parse_wasm_metadata(onchain_wasm)
        auto_repo = declared_source_repo(onchain_meta)
        auto_rev = declared_source_rev(onchain_meta) or "HEAD"
        if not auto_repo:
            raise HTTPException(
                status_code=400,
                detail="No source input and contract Wasm has no on-chain source_repo pointer",
            )
        try:
            fetched = await fetch_from_github(auto_repo, auto_rev)
        except SourceFetchError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"GitHub fetch failed: {exc}") from exc
        tarball_bytes = fetched.tarball_bytes
        source_origin = fetched.origin
        source_repo = fetched.repo_url
        source_commit = fetched.commit_sha
        if not bldopt:
            bldopt = declared_bldopt(onchain_meta)
    elif github_url:
        try:
            fetched = await fetch_from_github(github_url, git_ref)
        except SourceFetchError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"GitHub fetch failed: {exc}") from exc
        tarball_bytes = fetched.tarball_bytes
        source_origin = fetched.origin
        source_repo = fetched.repo_url
        source_commit = fetched.commit_sha
    elif tarball_url:
        try:
            fetched = await fetch_hosted_tarball(tarball_url, tarball_sha256)
        except SourceFetchError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Hosted tarball fetch failed: {exc}") from exc
        tarball_bytes = fetched.tarball_bytes
        source_origin = fetched.origin
        source_repo = fetched.repo_url
    elif source is not None:
        tarball_bytes = await source.read()
    elif tarball_sha256:
        try:
            fetched = fetch_content_addressed(tarball_sha256)
        except SourceFetchError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        tarball_bytes = fetched.tarball_bytes
        source_origin = fetched.origin

    assert tarball_bytes is not None

    try:
        content_hash, stored_path = validate_and_store_tarball(tarball_bytes)
    except TarballTooLargeError as exc:
        raise HTTPException(
            status_code=413,
            detail={"code": "tarball_too_large", "message": str(exc)},
        ) from exc
    except TarballError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if expected_hash is None or onchain_wasm is None:
        try:
            expected_hash, onchain_wasm = await fetch_wasm_hash(network, contract_id, wasm_hash)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RpcError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=502,
                detail=f"Cannot reach Soroban RPC for {network}: {exc}",
            ) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        onchain_meta = parse_wasm_metadata(onchain_wasm)
    elif not onchain_meta:
        onchain_meta = parse_wasm_metadata(onchain_wasm)

    if not bldopt:
        bldopt = declared_bldopt(onchain_meta)

    # Read the toolchain metadata the deployer embedded in the on-chain Wasm
    # (rustc / soroban-sdk versions, and any SEP-58 `bldimg`). This both explains
    # mismatches and lets us honor a declared, allowlisted builder image.
    declared_image = declared_build_image(onchain_meta)
    if declared_image and allowlist.is_allowed(declared_image):
        chosen_image = declared_image
    else:
        chosen_image = settings.builder_image
    if declared_image and not allowlist.is_allowed(declared_image):
        onchain_meta = {**onchain_meta, "bldimg_allowlisted": "false"}

    verification_id = new_verification_id()
    record = Verification(
        id=verification_id,
        network=network,
        contract_id=contract_id,
        wasm_hash=expected_hash,
        status=VerificationStatus.PENDING.value,
        trust_level=TrustLevel.SEP58_REBUILD.value,
        tarball_content_hash=content_hash,
        source_path=str(stored_path),
        source_origin=source_origin,
        source_repo=source_repo,
        source_commit=source_commit,
        onchain_meta=onchain_meta or None,
        builder_image=chosen_image,
        bldopt=bldopt,
        verifier_instance_id=settings.verifier_instance_id,
        created_at=utcnow(),
    )
    db.add(record)
    db.commit()

    background_tasks.add_task(run_verification_task, verification_id, use_docker)

    return {
        "verification_id": verification_id,
        "status": VerificationStatus.PENDING.value,
        "source_origin": source_origin,
        "source_commit": source_commit,
        "poll_url": f"{base_url(request)}/v1/verifications/{verification_id}",
    }


@app.get("/v1/verifications/{verification_id}")
async def get_verification(
    verification_id: str,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    record = db.get(Verification, verification_id)
    if not record:
        raise HTTPException(status_code=404, detail="Verification not found")
    return serialize_verification(record, base_url(request))


@app.get("/v1/{network}/contracts/{contract_id}")
async def get_contract_verification(
    network: str,
    contract_id: str,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    network = network.lower().strip()
    all_records = (
        db.query(Verification)
        .filter(
            Verification.network == network,
            Verification.contract_id == contract_id,
        )
        .order_by(Verification.verified_at.desc(), Verification.created_at.desc())
        .all()
    )

    if not all_records:
        raise HTTPException(status_code=404, detail="No verification on record for this contract")

    # Live freshness check: does the Wasm we verified still match what is
    # deployed on chain right now? (Matters for upgradeable contracts.)
    current_wasm_hash: Optional[str] = None
    try:
        wasm_bytes = await fetch_wasm_bytes(network, contract_id)
        current_wasm_hash = sha256_hex(wasm_bytes)
    except Exception as exc:  # noqa: BLE001 - freshness is best-effort
        logger.warning("Could not fetch live wasm for %s: %s", contract_id, exc)

    verified_records = [r for r in all_records if r.status == VerificationStatus.VERIFIED.value]
    verifications = [
        serialize_verification(record, base_url(request), current_wasm_hash=current_wasm_hash)
        for record in verified_records
    ]
    # Multi-verifier signal: per-verifier latest result + divergence (RFP hard req).
    multi = aggregate_verifiers(all_records, current_wasm_hash=current_wasm_hash)
    return {
        "contract_id": contract_id,
        "network": network,
        "current_wasm_hash": current_wasm_hash,
        "consensus": multi["consensus"],
        "verifier_count": multi["verifier_count"],
        "verifiers": multi["verifiers"],
        "verifications": verifications,
    }


def _wasm_lookup_payload(
    normalized: str,
    all_records: list[Verification],
    request: Request,
) -> dict:
    verified = [r for r in all_records if r.status == VerificationStatus.VERIFIED.value]
    verifications = [serialize_verification(record, base_url(request)) for record in verified]
    multi = aggregate_verifiers(all_records, current_wasm_hash=normalized)
    return {
        "wasm_hash": normalized,
        "consensus": multi["consensus"],
        "verifier_count": multi["verifier_count"],
        "verifiers": multi["verifiers"],
        "verifications": verifications,
    }


async def _lookup_by_wasm_hash(wasm_hash: str, request: Request, db: Session) -> dict:
    try:
        normalized = normalize_hash(wasm_hash)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    all_records = (
        db.query(Verification)
        .filter(Verification.wasm_hash == normalized)
        .order_by(Verification.verified_at.desc(), Verification.created_at.desc())
        .all()
    )
    if not all_records:
        raise HTTPException(status_code=404, detail="No verification on record for this wasm hash")

    return _wasm_lookup_payload(normalized, all_records, request)


@app.get("/v1/wasm/{wasm_hash}")
async def get_wasm_verification(
    wasm_hash: str,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    return await _lookup_by_wasm_hash(wasm_hash, request, db)


@app.get("/wasms/{wasm_hash}.json")
async def get_wasm_verification_sep(
    wasm_hash: str,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    """Verifier-API SEP canonical lookup path (alias of GET /v1/wasm/{hash})."""
    return await _lookup_by_wasm_hash(wasm_hash, request, db)


@app.get("/v1/source/{content_hash}/files")
async def list_source_files(content_hash: str) -> dict:
    try:
        validate_content_hash(content_hash)
        entries = list_tarball_entries(content_hash)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Source tarball not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"content_hash": content_hash, "files": entries, "count": len(entries)}


@app.get("/v1/source/{content_hash}/file")
async def preview_source_file(content_hash: str, path: str = Query(...)) -> Response:
    from app.storage import read_source_file

    try:
        validate_content_hash(content_hash)
        _name, payload = read_source_file(content_hash, path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="File not found in source tarball") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return Response(content=payload, media_type="text/plain; charset=utf-8")


@app.get("/v1/source/{content_hash}")
async def download_source(content_hash: str) -> Response:
    try:
        validate_content_hash(content_hash)
        data = read_source_tarball(content_hash)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Source tarball not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return Response(
        content=data,
        media_type="application/gzip",
        headers={"Content-Disposition": f'attachment; filename="{content_hash}.tar.gz"'},
    )
