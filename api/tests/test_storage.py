from __future__ import annotations

import pytest

from app.storage import (
    TarballError,
    TarballTooLargeError,
    read_source_tarball,
    sha256_hex,
    validate_and_store_tarball,
    validate_content_hash,
)
from tests.helpers import make_source_tarball


def test_validate_content_hash_rejects_invalid() -> None:
    with pytest.raises(ValueError):
        validate_content_hash("../etc/passwd")
    with pytest.raises(ValueError):
        validate_content_hash("abc")


def test_validate_and_store_tarball_success(isolated_env) -> None:
    data = make_source_tarball()
    content_hash, path = validate_and_store_tarball(data)
    assert content_hash == sha256_hex(data)
    assert path.exists()
    assert read_source_tarball(content_hash) == data


def test_validate_before_store_on_invalid_tarball(isolated_env) -> None:
    with pytest.raises(TarballError, match="Cargo.toml"):
        validate_and_store_tarball(make_source_tarball(include_cargo=False))

    storage_dir = isolated_env / "sources"
    assert list(storage_dir.glob("*.tar.gz")) == []


def test_rejects_empty_tarball(isolated_env) -> None:
    with pytest.raises(TarballError, match="Empty"):
        validate_and_store_tarball(b"")


def test_rejects_unsafe_paths(isolated_env) -> None:
    with pytest.raises(TarballError, match="Unsafe"):
        validate_and_store_tarball(make_source_tarball(unsafe_path="../escape.txt"))


def test_rejects_oversized_tarball(isolated_env, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.config.settings.max_tarball_bytes", 32)
    with pytest.raises(TarballTooLargeError, match="byte limit"):
        validate_and_store_tarball(make_source_tarball())


def test_read_source_tarball_blocks_path_traversal(isolated_env) -> None:
    data = make_source_tarball()
    validate_and_store_tarball(data)
    with pytest.raises(ValueError):
        read_source_tarball("../" + "a" * 64)
