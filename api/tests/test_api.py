from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.builder import BuildResult
from app.database import SessionLocal, Verification, VerificationStatus
from tests.helpers import WASM_HASH_A, WASM_HASH_B, make_source_tarball


@dataclass
class FakeBuild:
    wasm_hash: str


def _mock_live_wasm(monkeypatch: pytest.MonkeyPatch, wasm_bytes: bytes) -> None:
    async def fake_fetch(network: str, contract_id: str) -> bytes:
        return wasm_bytes

    monkeypatch.setattr("app.main.fetch_wasm_bytes", fake_fetch)


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    from app.main import app

    return TestClient(app)


def test_health(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_submit_requires_identifier(client: TestClient) -> None:
    tarball = make_source_tarball()
    response = client.post(
        "/v1/verify",
        data={"network": "testnet"},
        files={"source": ("source.tar.gz", tarball, "application/gzip")},
    )
    assert response.status_code == 400


def test_submit_rejects_invalid_tarball(client: TestClient) -> None:
    response = client.post(
        "/v1/verify",
        data={"network": "testnet", "wasm_hash": WASM_HASH_A},
        files={"source": ("source.tar.gz", b"not-a-tarball", "application/gzip")},
    )
    assert response.status_code == 400


def test_full_verification_flow_verified(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_build(
        source_dir: Path,
        output_dir: Path,
        image: str | None = None,
        bldopt: str | None = None,
    ) -> BuildResult:
        return BuildResult(
            wasm_bytes=b"\x00asm",
            wasm_hash=WASM_HASH_A,
            build_metadata={"docker_image": "test", "build_profile": "release"},
        )

    monkeypatch.setattr("app.worker.build_contract", fake_build)
    _mock_live_wasm(monkeypatch, b"\x00asm")

    tarball = make_source_tarball()
    submit = client.post(
        "/v1/verify",
        data={
            "network": "testnet",
            "wasm_hash": WASM_HASH_A,
            "contract_id": "CABC123",
            "use_docker": "true",
        },
        files={"source": ("source.tar.gz", tarball, "application/gzip")},
    )
    assert submit.status_code == 202
    body = submit.json()
    verification_id = body["verification_id"]
    assert body["status"] == "pending"
    assert body["source_origin"] == "upload"

    result = client.get(f"/v1/verifications/{verification_id}")
    assert result.status_code == 200
    payload = result.json()
    assert payload["status"] == "verified"
    assert payload["trust_level"] == "sep58_rebuild"
    assert payload["wasm_hash"] == WASM_HASH_A
    assert payload["build_metadata"]["docker_image"] == "test"
    assert payload["source"]["origin"] == "upload"

    contract_lookup = client.get("/v1/testnet/contracts/CABC123")
    assert contract_lookup.status_code == 200
    assert len(contract_lookup.json()["verifications"]) == 1

    wasm_lookup = client.get(f"/v1/wasm/{WASM_HASH_A}")
    assert wasm_lookup.status_code == 200

    source_hash = payload["tarball_content_hash"]
    download = client.get(f"/v1/source/{source_hash}")
    assert download.status_code == 200
    assert download.content == tarball


def test_full_verification_flow_mismatch(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
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

    tarball = make_source_tarball()
    submit = client.post(
        "/v1/verify",
        data={"network": "testnet", "wasm_hash": WASM_HASH_A},
        files={"source": ("source.tar.gz", tarball, "application/gzip")},
    )
    assert submit.status_code == 202
    verification_id = submit.json()["verification_id"]

    result = client.get(f"/v1/verifications/{verification_id}")
    assert result.status_code == 200
    payload = result.json()
    assert payload["status"] == "mismatch"
    assert payload["expected_wasm_hash"] == WASM_HASH_A
    assert payload["built_wasm_hash"] == WASM_HASH_B


def test_contract_lookup_404_when_unverified(client: TestClient) -> None:
    response = client.get("/v1/testnet/contracts/CUNKNOWN")
    assert response.status_code == 404


def test_source_download_rejects_invalid_hash(client: TestClient) -> None:
    response = client.get("/v1/source/not-valid")
    assert response.status_code == 400


def test_submit_treats_blank_contract_id_as_missing(client: TestClient) -> None:
    tarball = make_source_tarball()
    response = client.post(
        "/v1/verify",
        data={"network": "testnet", "contract_id": "   "},
        files={"source": ("source.tar.gz", tarball, "application/gzip")},
    )
    assert response.status_code == 400


def test_verification_not_found(client: TestClient) -> None:
    response = client.get("/v1/verifications/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404


def test_list_verifications(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.builder import BuildResult

    def fake_build(source_dir, output_dir, image=None, bldopt=None):
        return BuildResult(
            wasm_bytes=b"\x00asm",
            wasm_hash=WASM_HASH_A,
            build_metadata={"docker_image": "test"},
        )

    monkeypatch.setattr("app.worker.build_contract", fake_build)

    tarball = make_source_tarball()
    client.post(
        "/v1/verify",
        data={"network": "testnet", "wasm_hash": WASM_HASH_A, "contract_id": "CLIST1"},
        files={"source": ("source.tar.gz", tarball, "application/gzip")},
    )

    response = client.get("/v1/verifications?status=verified&limit=10")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] >= 1
    assert any(v["status"] == "verified" for v in body["verifications"])


def _verify_contract(client: TestClient, monkeypatch: pytest.MonkeyPatch, wasm_bytes: bytes, contract_id: str) -> str:
    wasm_hash = hashlib.sha256(wasm_bytes).hexdigest()

    def fake_build(
        source_dir: Path,
        output_dir: Path,
        image: str | None = None,
        bldopt: str | None = None,
    ) -> BuildResult:
        return BuildResult(
            wasm_bytes=wasm_bytes,
            wasm_hash=wasm_hash,
            build_metadata={"docker_image": "test", "build_profile": "release"},
        )

    monkeypatch.setattr("app.worker.build_contract", fake_build)

    tarball = make_source_tarball()
    submit = client.post(
        "/v1/verify",
        data={"network": "testnet", "wasm_hash": wasm_hash, "contract_id": contract_id},
        files={"source": ("source.tar.gz", tarball, "application/gzip")},
    )
    assert submit.status_code == 202
    return wasm_hash


def test_freshness_current(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    wasm_bytes = b"\x00asm-current-build"
    _verify_contract(client, monkeypatch, wasm_bytes, "CFRESH1")
    _mock_live_wasm(monkeypatch, wasm_bytes)

    lookup = client.get("/v1/testnet/contracts/CFRESH1")
    assert lookup.status_code == 200
    body = lookup.json()
    assert body["verifications"][0]["freshness"] == "current"


def test_freshness_superseded(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    wasm_bytes = b"\x00asm-original-build"
    _verify_contract(client, monkeypatch, wasm_bytes, "CFRESH2")
    # Contract was upgraded: live wasm differs from what we verified.
    _mock_live_wasm(monkeypatch, b"\x00asm-upgraded-build")

    lookup = client.get("/v1/testnet/contracts/CFRESH2")
    assert lookup.status_code == 200
    body = lookup.json()
    v = body["verifications"][0]
    assert v["freshness"] == "superseded"
    assert "current_wasm_hash" in v


def test_verified_record_exposes_build_image(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import settings

    def fake_build(
        source_dir: Path,
        output_dir: Path,
        image: str | None = None,
        bldopt: str | None = None,
    ) -> BuildResult:
        return BuildResult(
            wasm_bytes=b"\x00asm",
            wasm_hash=WASM_HASH_A,
            build_metadata={"docker_image": settings.builder_image, "docker_image_digest": "local"},
        )

    monkeypatch.setattr("app.worker.build_contract", fake_build)

    tarball = make_source_tarball()
    submit = client.post(
        "/v1/verify",
        data={"network": "testnet", "wasm_hash": WASM_HASH_A, "contract_id": "CIMG1"},
        files={"source": ("source.tar.gz", tarball, "application/gzip")},
    )
    verification_id = submit.json()["verification_id"]
    payload = client.get(f"/v1/verifications/{verification_id}").json()
    assert payload["build_image"]["allowlisted"] is True
    assert payload["build_image"]["sdf_trusted"] is True


def test_content_addressed_submission(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
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

    # First store a tarball via a normal upload to populate the content store.
    tarball = make_source_tarball()
    first = client.post(
        "/v1/verify",
        data={"network": "testnet", "wasm_hash": WASM_HASH_A, "contract_id": "CCA1"},
        files={"source": ("source.tar.gz", tarball, "application/gzip")},
    )
    content_hash = first.json().get("verification_id")
    stored = client.get(f"/v1/verifications/{content_hash}").json()["tarball_content_hash"]

    # Now submit hash-only; the source must resolve from the content store.
    second = client.post(
        "/v1/verify",
        data={
            "network": "testnet",
            "wasm_hash": WASM_HASH_A,
            "contract_id": "CCA2",
            "tarball_sha256": f"sha256:{stored}",
        },
    )
    assert second.status_code == 202
    assert second.json()["source_origin"] == "content-addressed"


def test_content_addressed_missing_source_404(client: TestClient) -> None:
    response = client.post(
        "/v1/verify",
        data={
            "network": "testnet",
            "wasm_hash": WASM_HASH_A,
            "contract_id": "CCA3",
            "tarball_sha256": "f" * 64,
        },
    )
    assert response.status_code == 404


def test_hosted_tarball_submission(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.sources import FetchedSource

    tarball = make_source_tarball()

    async def fake_hosted(tarball_url: str, expected: str) -> FetchedSource:
        return FetchedSource(tarball_bytes=tarball, origin="ipfs", repo_url=tarball_url)

    monkeypatch.setattr("app.main.fetch_hosted_tarball", fake_hosted)

    def fake_build(
        source_dir: Path,
        output_dir: Path,
        image: str | None = None,
        bldopt: str | None = None,
    ) -> BuildResult:
        return BuildResult(wasm_bytes=b"\x00asm", wasm_hash=WASM_HASH_A, build_metadata={"docker_image": "test"})

    monkeypatch.setattr("app.worker.build_contract", fake_build)

    submit = client.post(
        "/v1/verify",
        data={
            "network": "testnet",
            "wasm_hash": WASM_HASH_A,
            "contract_id": "CHOST1",
            "tarball_url": "ipfs://bafyTESTcid",
            "tarball_sha256": "a" * 64,
        },
    )
    assert submit.status_code == 202
    assert submit.json()["source_origin"] == "ipfs"


def test_github_input_snapshots_to_tarball(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.sources import FetchedSource

    tarball = make_source_tarball()

    async def fake_github(repo_url: str, ref: str) -> FetchedSource:
        return FetchedSource(
            tarball_bytes=tarball,
            origin="github",
            repo_url="https://github.com/example/demo",
            commit_sha="a" * 40,
        )

    monkeypatch.setattr("app.main.fetch_from_github", fake_github)

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

    submit = client.post(
        "/v1/verify",
        data={
            "network": "testnet",
            "wasm_hash": WASM_HASH_A,
            "contract_id": "CGITHUB1",
            "github_url": "https://github.com/example/demo",
            "git_ref": "v1.0.0",
        },
    )
    assert submit.status_code == 202
    body = submit.json()
    assert body["source_origin"] == "github"
    assert body["source_commit"] == "a" * 40

    result = client.get(f"/v1/verifications/{body['verification_id']}").json()
    assert result["source"]["origin"] == "github"
    assert result["source"]["repo_url"] == "https://github.com/example/demo"
    assert result["source"]["commit_sha"] == "a" * 40


def test_submit_rejects_oversized_tarball(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.config.settings.max_tarball_bytes", 32)
    tarball = make_source_tarball()
    response = client.post(
        "/v1/verify",
        data={"network": "testnet", "wasm_hash": WASM_HASH_A},
        files={"source": ("source.tar.gz", tarball, "application/gzip")},
    )
    assert response.status_code == 413
    assert response.json()["detail"]["code"] == "tarball_too_large"


def test_trust_fields_on_verified_record(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import settings

    def fake_build(
        source_dir: Path,
        output_dir: Path,
        image: str | None = None,
        bldopt: str | None = None,
    ) -> BuildResult:
        return BuildResult(
            wasm_bytes=b"\x00asm",
            wasm_hash=WASM_HASH_A,
            build_metadata={
                "docker_image": settings.builder_image,
                "docker_image_digest": "local",
                "applied_bldopt": bldopt,
            },
        )

    monkeypatch.setattr("app.worker.build_contract", fake_build)

    tarball = make_source_tarball()
    submit = client.post(
        "/v1/verify",
        data={
            "network": "testnet",
            "wasm_hash": WASM_HASH_A,
            "contract_id": "CTRUST1",
            "bldopt": "--package counter",
        },
        files={"source": ("source.tar.gz", tarball, "application/gzip")},
    )
    verification_id = submit.json()["verification_id"]
    payload = client.get(f"/v1/verifications/{verification_id}").json()
    assert payload["metadata_source"] == "supplied"
    assert payload["image_trust"] in {"sdf", "allowlisted"}
    assert payload["source_identity"]["package"] == "counter"


def test_contract_id_only_auto_resolve(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.sources import FetchedSource

    tarball = make_source_tarball()

    async def fake_fetch_hash(network: str, contract_id: str | None, wasm_hash: str | None):
        return WASM_HASH_A, b"\x00asm-meta"

    def fake_parse(_wasm: bytes) -> dict[str, str]:
        return {
            "source_repo": "https://github.com/example/onchain-contract",
            "source_rev": "deadbeef" * 5,
            "bldopt": "--package token",
        }

    async def fake_github(repo_url: str, ref: str) -> FetchedSource:
        return FetchedSource(
            tarball_bytes=tarball,
            origin="github",
            repo_url=repo_url,
            commit_sha=ref,
        )

    def fake_build(
        source_dir: Path,
        output_dir: Path,
        image: str | None = None,
        bldopt: str | None = None,
    ) -> BuildResult:
        return BuildResult(
            wasm_bytes=b"\x00asm",
            wasm_hash=WASM_HASH_A,
            build_metadata={"docker_image": "test", "applied_bldopt": bldopt},
        )

    monkeypatch.setattr("app.main.fetch_wasm_hash", fake_fetch_hash)
    monkeypatch.setattr("app.main.parse_wasm_metadata", fake_parse)
    monkeypatch.setattr("app.main.fetch_from_github", fake_github)
    monkeypatch.setattr("app.worker.build_contract", fake_build)

    submit = client.post(
        "/v1/verify",
        data={"network": "testnet", "contract_id": "CAUTO1"},
    )
    assert submit.status_code == 202
    body = submit.json()
    assert body["source_origin"] == "github"

    record = client.get(f"/v1/verifications/{body['verification_id']}").json()
    assert record["metadata_source"] == "onchain"
    assert record["source_identity"]["package"] == "token"


def test_wasms_json_canonical_lookup(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
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

    tarball = make_source_tarball()
    client.post(
        "/v1/verify",
        data={"network": "testnet", "wasm_hash": WASM_HASH_A, "contract_id": "CWASM1"},
        files={"source": ("source.tar.gz", tarball, "application/gzip")},
    )

    native = client.get(f"/v1/wasm/{WASM_HASH_A}")
    sep = client.get(f"/wasms/{WASM_HASH_A}.json")
    assert native.status_code == 200
    assert sep.status_code == 200
    assert sep.json()["wasm_hash"] == native.json()["wasm_hash"]


def test_idempotent_submit_returns_existing_job(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
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

    tarball = make_source_tarball()
    data = {
        "network": "testnet",
        "wasm_hash": WASM_HASH_A,
        "contract_id": "CIDEM1",
    }
    first = client.post(
        "/v1/verify",
        data=data,
        files={"source": ("source.tar.gz", tarball, "application/gzip")},
    )
    assert first.status_code == 202
    first_id = first.json()["verification_id"]

    second = client.post(
        "/v1/verify",
        data=data,
        files={"source": ("source.tar.gz", tarball, "application/gzip")},
    )
    assert second.status_code == 202
    body = second.json()
    assert body["verification_id"] == first_id
    assert body["idempotent"] is True


def test_structured_error_on_missing_identifier(client: TestClient) -> None:
    response = client.post("/v1/verify", data={"network": "testnet"})
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail["code"] == "missing_identifier"
    assert "message" in detail


def test_structured_error_verification_not_found(client: TestClient) -> None:
    response = client.get("/v1/verifications/does-not-exist")
    assert response.status_code == 404
    detail = response.json()["detail"]
    assert detail["code"] == "verification_not_found"


def test_contract_badge_json_and_svg(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
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

    async def skip_live_wasm(network: str, contract_id: str) -> bytes:
        raise RuntimeError("rpc offline in test")

    monkeypatch.setattr("app.main.fetch_wasm_bytes", skip_live_wasm)

    tarball = make_source_tarball()
    client.post(
        "/v1/verify",
        data={"network": "testnet", "wasm_hash": WASM_HASH_A, "contract_id": "CBADGE1"},
        files={"source": ("source.tar.gz", tarball, "application/gzip")},
    )

    badge_json = client.get("/v1/testnet/contracts/CBADGE1/badge.json")
    assert badge_json.status_code == 200
    payload = badge_json.json()
    assert payload["contract_id"] == "CBADGE1"
    assert payload["consensus"] == "verified"
    assert payload["verified"] is True

    badge_svg = client.get("/v1/testnet/contracts/CBADGE1/badge.svg")
    assert badge_svg.status_code == 200
    assert badge_svg.headers["content-type"].startswith("image/svg+xml")
    assert "Source verified" in badge_svg.text


def test_wasm_contracts_reverse_index(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
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

    tarball = make_source_tarball()
    for cid in ("CREV1", "CREV2"):
        client.post(
            "/v1/verify",
            data={"network": "testnet", "wasm_hash": WASM_HASH_A, "contract_id": cid},
            files={"source": ("source.tar.gz", tarball, "application/gzip")},
        )

    response = client.get(f"/v1/wasm/{WASM_HASH_A}/contracts")
    assert response.status_code == 200
    body = response.json()
    assert body["contract_count"] == 2
    ids = {c["contract_id"] for c in body["contracts"]}
    assert ids == {"CREV1", "CREV2"}
    assert all(c["consensus"] == "verified" for c in body["contracts"])
