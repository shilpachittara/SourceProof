from __future__ import annotations

import pytest
from stellar_sdk import xdr

from app.rpc import (
    RpcError,
    _contract_instance_ledger_key,
    fetch_wasm_hash,
    normalize_hash,
    sha256_hex,
)


def test_normalize_hash_accepts_0x_prefix() -> None:
    raw = "a" * 64
    assert normalize_hash("0x" + raw) == raw


def test_normalize_hash_rejects_invalid() -> None:
    with pytest.raises(ValueError):
        normalize_hash("not-a-hash")


@pytest.mark.asyncio
async def test_fetch_wasm_hash_from_explicit_hash() -> None:
    expected = "c" * 64
    wasm_hash, wasm_bytes = await fetch_wasm_hash("testnet", None, expected)
    assert wasm_hash == expected
    assert wasm_bytes is None


@pytest.mark.asyncio
async def test_fetch_wasm_hash_requires_identifier() -> None:
    with pytest.raises(ValueError):
        await fetch_wasm_hash("testnet", None, None)


@pytest.mark.asyncio
async def test_fetch_wasm_hash_from_rpc(monkeypatch: pytest.MonkeyPatch) -> None:
    wasm = b"\x00asm\x01\x02\x03"
    contract_id = "CBCJGHKTKSTWQQ43Z7YZIMEIYGJWOPFCBJAAHUWG5SLUJPWQ6TBDF4BW"

    async def fake_fetch_rpc(network: str, cid: str) -> bytes:
        assert network == "testnet"
        assert cid == contract_id
        return wasm

    monkeypatch.setattr("app.rpc.fetch_wasm_bytes_via_rpc", fake_fetch_rpc)

    wasm_hash, wasm_bytes = await fetch_wasm_hash("testnet", contract_id, None)
    assert wasm_hash == sha256_hex(wasm)
    assert wasm_bytes == wasm


def test_contract_instance_ledger_key_roundtrip() -> None:
    contract_id = "CBCJGHKTKSTWQQ43Z7YZIMEIYGJWOPFCBJAAHUWG5SLUJPWQ6TBDF4BW"
    key = _contract_instance_ledger_key(contract_id)
    assert key.type == xdr.LedgerEntryType.CONTRACT_DATA
    assert key.contract_data is not None


@pytest.mark.asyncio
async def test_fetch_wasm_hash_rpc_error(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_rpc_call(network: str, method: str, params):  # noqa: ANN001
        raise RpcError("rpc down")

    async def fake_cli(network: str, contract_id: str) -> bytes:
        raise RpcError("cli down")

    monkeypatch.setattr("app.rpc.rpc_call", fake_rpc_call)
    monkeypatch.setattr("app.rpc.fetch_wasm_bytes_via_cli", fake_cli)

    with pytest.raises(RpcError):
        await fetch_wasm_hash("testnet", "CBCJGHKTKSTWQQ43Z7YZIMEIYGJWOPFCBJAAHUWG5SLUJPWQ6TBDF4BW", None)
