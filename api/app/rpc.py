"""Fetch deployed contract Wasm from Stellar Soroban RPC or stellar-cli."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import httpx
from stellar_sdk import Address, xdr

from app.config import settings

logger = logging.getLogger(__name__)


class RpcError(RuntimeError):
    pass


def normalize_hash(value: str) -> str:
    cleaned = value.lower().removeprefix("0x")
    if len(cleaned) != 64 or any(ch not in "0123456789abcdef" for ch in cleaned):
        raise ValueError("wasm_hash must be a 64-character hex SHA-256 digest")
    return cleaned


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _contract_instance_ledger_key(contract_id: str) -> xdr.LedgerKey:
    return xdr.LedgerKey(
        type=xdr.LedgerEntryType.CONTRACT_DATA,
        contract_data=xdr.LedgerKeyContractData(
            contract=Address(contract_id).to_xdr_sc_address(),
            key=xdr.SCVal(xdr.SCValType.SCV_LEDGER_KEY_CONTRACT_INSTANCE),
            durability=xdr.ContractDataDurability.PERSISTENT,
        ),
    )


def _contract_code_ledger_key(wasm_hash: xdr.Hash) -> xdr.LedgerKey:
    return xdr.LedgerKey(
        type=xdr.LedgerEntryType.CONTRACT_CODE,
        contract_code=xdr.LedgerKeyContractCode(hash=wasm_hash),
    )


async def rpc_call(network: str, method: str, params: dict[str, Any] | list[Any]) -> Any:
    rpc_url = settings.rpc_url_for(network)
    if not rpc_url:
        raise RpcError(f"Unsupported network: {network}")

    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(rpc_url, json=payload)
            response.raise_for_status()
            body = response.json()
    except httpx.HTTPError as exc:
        raise RpcError(
            f"Cannot reach Soroban RPC at {rpc_url} ({exc}). "
            "Check network/DNS, or set RPC_URL_TESTNET to another provider."
        ) from exc

    if "error" in body:
        raise RpcError(body["error"].get("message", str(body["error"])))
    return body["result"]


async def fetch_wasm_bytes_via_rpc(network: str, contract_id: str) -> bytes:
    instance_result = await rpc_call(
        network,
        "getLedgerEntries",
        {"keys": [_contract_instance_ledger_key(contract_id).to_xdr()]},
    )
    entries = instance_result.get("entries") if isinstance(instance_result, dict) else None
    if not entries:
        raise RpcError(f"Contract not found on {network}: {contract_id}")

    instance_entry = xdr.LedgerEntryData.from_xdr(entries[0]["xdr"])
    contract_val = instance_entry.contract_data.val
    if contract_val.type != xdr.SCValType.SCV_CONTRACT_INSTANCE or contract_val.instance is None:
        raise RpcError("Unexpected contract instance ledger entry")

    executable = contract_val.instance.executable
    if executable is None or executable.wasm_hash is None:
        raise RpcError("Contract has no Wasm hash on ledger")

    code_result = await rpc_call(
        network,
        "getLedgerEntries",
        {"keys": [_contract_code_ledger_key(executable.wasm_hash).to_xdr()]},
    )
    code_entries = code_result.get("entries") if isinstance(code_result, dict) else None
    if not code_entries:
        raise RpcError("Contract Wasm bytecode not found on ledger")

    code_entry = xdr.LedgerEntryData.from_xdr(code_entries[0]["xdr"])
    if code_entry.contract_code is None or not code_entry.contract_code.code:
        raise RpcError("Contract code entry is empty")
    return bytes(code_entry.contract_code.code)


async def fetch_wasm_bytes_via_cli(network: str, contract_id: str) -> bytes:
    if not shutil.which("stellar"):
        raise RpcError("stellar CLI is not installed (optional fallback)")

    rpc_url = settings.rpc_url_for(network)
    passphrase = settings.network_passphrases[network]

    with tempfile.TemporaryDirectory() as tmp:
        out_file = Path(tmp) / "contract.wasm"
        cmd = [
            "stellar",
            "contract",
            "fetch",
            "--id",
            contract_id,
            "--network",
            network,
            "--rpc-url",
            rpc_url,
            "--network-passphrase",
            passphrase,
            "--out-file",
            str(out_file),
        ]
        completed = await asyncio.to_thread(
            subprocess.run,
            cmd,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            details = completed.stderr or completed.stdout or "stellar contract fetch failed"
            raise RpcError(details.strip())
        if not out_file.exists():
            raise RpcError("stellar contract fetch did not produce wasm output")
        return out_file.read_bytes()


async def fetch_wasm_bytes(network: str, contract_id: str) -> bytes:
    try:
        return await fetch_wasm_bytes_via_rpc(network, contract_id)
    except RpcError as rpc_exc:
        logger.warning("RPC fetch failed, trying stellar-cli: %s", rpc_exc)
        return await fetch_wasm_bytes_via_cli(network, contract_id)


async def fetch_wasm_hash(network: str, contract_id: str | None, wasm_hash: str | None) -> tuple[str, bytes | None]:
    if wasm_hash:
        return normalize_hash(wasm_hash), None

    contract_id = (contract_id or "").strip()
    if not contract_id:
        raise ValueError("contract_id or wasm_hash is required")

    wasm_bytes = await fetch_wasm_bytes(network, contract_id)
    return sha256_hex(wasm_bytes), wasm_bytes
