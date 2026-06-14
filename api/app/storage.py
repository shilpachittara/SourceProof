from __future__ import annotations

import hashlib
import logging
import tarfile
from io import BytesIO
from pathlib import Path

from app.config import settings

logger = logging.getLogger(__name__)

CONTENT_HASH_PATTERN = frozenset("0123456789abcdef")


class TarballError(ValueError):
    pass


class TarballTooLargeError(TarballError):
    """Raised when an upload exceeds settings.max_tarball_bytes."""


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def validate_content_hash(content_hash: str) -> str:
    cleaned = content_hash.lower().strip()
    if len(cleaned) != 64 or not all(ch in CONTENT_HASH_PATTERN for ch in cleaned):
        raise ValueError("content_hash must be a 64-character hex SHA-256 digest")
    return cleaned


def validate_and_store_tarball(data: bytes) -> tuple[str, Path]:
    if len(data) == 0:
        raise TarballError("Empty tarball upload")
    if len(data) > settings.max_tarball_bytes:
        raise TarballTooLargeError(
            f"Tarball exceeds {settings.max_tarball_bytes} byte limit"
        )

    _validate_tarball_contents(data)

    content_hash = sha256_hex(data)
    storage_root = Path(settings.storage_dir)
    storage_root.mkdir(parents=True, exist_ok=True)
    dest = storage_root / f"{content_hash}.tar.gz"
    if not dest.exists():
        dest.write_bytes(data)

    return content_hash, dest


def _validate_tarball_contents(data: bytes) -> None:
    try:
        with tarfile.open(fileobj=BytesIO(data), mode="r:gz") as archive:
            names = archive.getnames()
            if not names:
                raise TarballError("Tarball contains no files")

            has_cargo = any(name.endswith("Cargo.toml") for name in names)
            if not has_cargo:
                raise TarballError("Tarball must include at least one Cargo.toml")

            for member in archive.getmembers():
                if member.name.startswith("/") or ".." in Path(member.name).parts:
                    raise TarballError(f"Unsafe path in tarball: {member.name}")
                if member.isdir():
                    continue
                if member.size > settings.max_tarball_bytes:
                    raise TarballError(f"File too large in tarball: {member.name}")
    except tarfile.TarError as exc:
        raise TarballError(f"Invalid tarball: {exc}") from exc


def _is_noise(name: str) -> bool:
    """macOS AppleDouble / VCS / build artifacts that are not part of the source."""
    base = name.rsplit("/", 1)[-1]
    if base.startswith("._") or base == ".DS_Store":
        return True
    parts = name.split("/")
    return any(p in ("__MACOSX", ".git", "target") for p in parts)


def list_tarball_entries(content_hash: str, *, max_entries: int = 500) -> list[dict]:
    """Return a listing of files inside a stored source tarball.

    Lets the UI show the *original contract source* that backs a verification —
    including for hash-only / URL / IPFS submissions, where the bytes were
    snapshotted into our content store at submit time.
    """
    data = read_source_tarball(content_hash)
    entries: list[dict] = []
    with tarfile.open(fileobj=BytesIO(data), mode="r:gz") as archive:
        for member in archive.getmembers():
            if member.isdir():
                continue
            if _is_noise(member.name):
                continue
            entries.append({"path": member.name, "size": member.size})
            if len(entries) >= max_entries:
                break
    entries.sort(key=lambda e: e["path"])
    return entries


def read_source_file(content_hash: str, inner_path: str, *, max_bytes: int = 256 * 1024) -> tuple[str, bytes]:
    """Read one file out of a stored source tarball (for in-UI preview)."""
    data = read_source_tarball(content_hash)
    with tarfile.open(fileobj=BytesIO(data), mode="r:gz") as archive:
        try:
            member = archive.getmember(inner_path)
        except KeyError as exc:
            raise FileNotFoundError(inner_path) from exc
        if member.isdir():
            raise FileNotFoundError(inner_path)
        extracted = archive.extractfile(member)
        payload = extracted.read(max_bytes + 1) if extracted else b""
    truncated = len(payload) > max_bytes
    return (member.name, payload[:max_bytes] + (b"\n... (truncated)" if truncated else b""))


def read_source_tarball(content_hash: str) -> bytes:
    normalized = validate_content_hash(content_hash)
    path = Path(settings.storage_dir) / f"{normalized}.tar.gz"
    if not path.exists():
        raise FileNotFoundError(normalized)
    return path.read_bytes()


def load_tarball_by_hash(content_hash: str) -> bytes | None:
    """Return stored tarball bytes for a content hash, or None if not present.

    Used by content-addressed (hash-only) submissions, where the source must
    already be in our store (e.g. auditor-mediated) and there is nothing to fetch.
    """
    try:
        return read_source_tarball(content_hash)
    except (FileNotFoundError, ValueError):
        return None


def _safe_extractall(archive: tarfile.TarFile, destination: Path) -> None:
    if hasattr(tarfile, "data_filter"):
        archive.extractall(path=destination, filter="data")
        return

    for member in archive.getmembers():
        if member.name.startswith("/") or ".." in Path(member.name).parts:
            raise TarballError(f"Unsafe path in tarball: {member.name}")
        target = destination / member.name
        if not str(target.resolve()).startswith(str(destination.resolve())):
            raise TarballError(f"Unsafe path in tarball: {member.name}")
    archive.extractall(path=destination)


def extract_tarball(tarball_path: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(tarball_path, mode="r:gz") as archive:
        for member in archive.getmembers():
            if member.name.startswith("/") or ".." in Path(member.name).parts:
                raise TarballError(f"Unsafe path in tarball: {member.name}")
        _safe_extractall(archive, destination)
