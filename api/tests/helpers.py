"""Shared helpers for tests."""

from __future__ import annotations

import io
import tarfile
from pathlib import Path


def make_source_tarball(
    *,
    include_cargo: bool = True,
    extra_files: dict[str, str] | None = None,
    unsafe_path: str | None = None,
) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        if include_cargo:
            cargo = "[package]\nname = \"demo\"\nversion = \"0.1.0\"\nedition = \"2021\"\n"
            _add_text(archive, "Cargo.toml", cargo)
            _add_text(archive, "src/lib.rs", "#![no_std]\n")
        else:
            _add_text(archive, "README.md", "no cargo here\n")

        if extra_files:
            for name, content in extra_files.items():
                _add_text(archive, name, content)

        if unsafe_path:
            info = tarfile.TarInfo(name=unsafe_path)
            payload = b"bad"
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))

    return buffer.getvalue()


def _add_text(archive: tarfile.TarFile, name: str, content: str) -> None:
    encoded = content.encode("utf-8")
    info = tarfile.TarInfo(name=name)
    info.size = len(encoded)
    archive.addfile(info, io.BytesIO(encoded))


def load_example_tarball(root: Path) -> bytes:
    tarball = root / "examples" / "hello-world-source.tar.gz"
    if not tarball.exists():
        raise FileNotFoundError(f"Missing example tarball: {tarball}")
    return tarball.read_bytes()


WASM_HASH_A = "a" * 64
WASM_HASH_B = "b" * 64
