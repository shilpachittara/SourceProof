from __future__ import annotations

import hashlib

import pytest

from app import sources
from app.sources import (
    SourceFetchError,
    fetch_content_addressed,
    fetch_hosted_tarball,
)
from app.storage import validate_and_store_tarball
from tests.helpers import make_source_tarball


class _FakeResp:
    def __init__(self, content: bytes, status_code: int = 200) -> None:
        self.content = content
        self.status_code = status_code


class _FakeClient:
    def __init__(self, content: bytes, status_code: int = 200) -> None:
        self._content = content
        self._status = status_code

    async def __aenter__(self) -> "_FakeClient":
        return self

    async def __aexit__(self, *args: object) -> bool:
        return False

    async def get(self, url: str) -> _FakeResp:
        return _FakeResp(self._content, self._status)


def _patch_http(monkeypatch: pytest.MonkeyPatch, content: bytes, status: int = 200) -> None:
    monkeypatch.setattr(
        sources.httpx,
        "AsyncClient",
        lambda *a, **k: _FakeClient(content, status),
    )


async def test_hosted_tarball_https_success(monkeypatch: pytest.MonkeyPatch) -> None:
    tarball = make_source_tarball()
    digest = hashlib.sha256(tarball).hexdigest()
    _patch_http(monkeypatch, tarball)

    fetched = await fetch_hosted_tarball("https://example.com/src.tar.gz", f"sha256:{digest}")
    assert fetched.origin == "url"
    assert fetched.tarball_bytes == tarball


async def test_hosted_tarball_ipfs_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    tarball = make_source_tarball()
    digest = hashlib.sha256(tarball).hexdigest()
    _patch_http(monkeypatch, tarball)

    fetched = await fetch_hosted_tarball("ipfs://bafyTESTcid", digest)
    assert fetched.origin == "ipfs"


async def test_hosted_tarball_requires_hash() -> None:
    with pytest.raises(SourceFetchError):
        await fetch_hosted_tarball("https://example.com/src.tar.gz", None)


async def test_hosted_tarball_hash_mismatch_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    tarball = make_source_tarball()
    _patch_http(monkeypatch, tarball)
    wrong = "0" * 64
    with pytest.raises(SourceFetchError):
        await fetch_hosted_tarball("https://example.com/src.tar.gz", wrong)


def test_content_addressed_found_after_store() -> None:
    tarball = make_source_tarball()
    content_hash, _ = validate_and_store_tarball(tarball)

    fetched = fetch_content_addressed(f"sha256:{content_hash}")
    assert fetched.origin == "content-addressed"
    assert fetched.tarball_bytes == tarball


def test_content_addressed_missing_raises() -> None:
    with pytest.raises(SourceFetchError):
        fetch_content_addressed("a" * 64)
