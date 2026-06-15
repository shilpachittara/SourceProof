from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.builder import BuildResult
from app.storage import extract_tarball, sha256_hex, validate_and_store_tarball
from tests.helpers import WASM_HASH_A, load_example_tarball, make_source_tarball

ROOT = Path(__file__).resolve().parents[2]

EXAMPLE_TARBALL = ROOT / "examples" / "hello-world-source.tar.gz"

requires_example_tarball = pytest.mark.skipif(
    not EXAMPLE_TARBALL.exists(),
    reason="run `make package-example` to generate examples/hello-world-source.tar.gz",
)


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    from app.main import app

    return TestClient(app)


@requires_example_tarball
def test_example_tarball_extracts(isolated_env) -> None:
    tarball_bytes = load_example_tarball(ROOT)
    content_hash, stored_path = validate_and_store_tarball(tarball_bytes)

    dest = isolated_env / "extract"
    extract_tarball(stored_path, dest)

    assert (dest / "Cargo.toml").exists()
    assert (dest / "contracts/hello_world/src/lib.rs").exists()
    assert content_hash == sha256_hex(tarball_bytes)


@requires_example_tarball
def test_end_to_end_with_example_tarball(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    tarball = load_example_tarball(ROOT)
    expected_hash = WASM_HASH_A

    def fake_build(
        source_dir: Path,
        output_dir: Path,
        image: str | None = None,
        bldopt: str | None = None,
    ) -> BuildResult:
        assert (source_dir / "Cargo.toml").exists()
        assert (source_dir / "contracts/hello_world/src/lib.rs").exists()
        return BuildResult(
            wasm_bytes=b"\x00asm-demo",
            wasm_hash=expected_hash,
            build_metadata={
                "docker_image": "soroban-verify-builder:local",
                "build_profile": "release",
            },
        )

    monkeypatch.setattr("app.worker.build_contract", fake_build)

    submit = client.post(
        "/v1/verify",
        data={
            "network": "testnet",
            "wasm_hash": expected_hash,
            "contract_id": "CDEMOCONTRACT",
        },
        files={"source": ("hello-world-source.tar.gz", tarball, "application/gzip")},
    )
    assert submit.status_code == 202
    verification_id = submit.json()["verification_id"]

    result = client.get(f"/v1/verifications/{verification_id}").json()
    assert result["status"] == "verified"
    assert result["contract_id"] == "CDEMOCONTRACT"

    source = client.get(f"/v1/source/{result['tarball_content_hash']}")
    assert source.status_code == 200
    assert source.content == tarball
