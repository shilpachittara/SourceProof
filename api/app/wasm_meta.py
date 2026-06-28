"""Read Soroban contract metadata embedded in on-chain Wasm.

`stellar contract build` records metadata in a Wasm custom section named
`contractmetav0` as a stream of XDR `SCMetaEntry` (key/value strings). Standard
keys include:
  - rsver     : rustc version used to build the contract
  - rssdkver  : soroban-sdk version (+ git hash)
  - bldimg    : (SEP-58) the builder image the deployer declares was used
  - bldopt    : (SEP-58) repeating build flags (draft → ordered bldarg in #1965)
  - bldarg    : (SEP-58 draft) ordered build arguments for replay

We use this for two things:
  1. Explain mismatches ("on-chain built with rustc 1.90; verifier uses 1.89").
  2. Honor a declared `bldimg` when selecting the build environment.

This is best-effort: any parse error returns an empty dict and never blocks
verification (the byte-for-byte hash comparison is the source of truth).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

_WASM_MAGIC = b"\x00asm"
META_SECTION = "contractmetav0"
ENV_META_SECTION = "contractenvmetav0"


@dataclass
class WasmMeta:
    """Parsed contractmetav0 entries, preserving repeating SEP-58 keys."""

    scalars: dict[str, str] = field(default_factory=dict)
    bldopt: list[str] = field(default_factory=list)
    bldarg: list[str] = field(default_factory=list)


def _read_uleb128(data: bytes, pos: int) -> tuple[int, int]:
    result = 0
    shift = 0
    while True:
        if pos >= len(data):
            raise ValueError("truncated LEB128")
        byte = data[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        if (byte & 0x80) == 0:
            break
        shift += 7
    return result, pos


def _iter_custom_sections(wasm: bytes):
    """Yield (name, content_bytes) for each Wasm custom section (id 0)."""
    if wasm[:4] != _WASM_MAGIC:
        return
    pos = 8  # skip magic (4) + version (4)
    n = len(wasm)
    while pos < n:
        section_id = wasm[pos]
        pos += 1
        size, pos = _read_uleb128(wasm, pos)
        end = pos + size
        if end > n:
            break
        if section_id == 0:  # custom section
            name_len, name_pos = _read_uleb128(wasm, pos)
            name = wasm[name_pos:name_pos + name_len].decode("utf-8", "replace")
            content = wasm[name_pos + name_len:end]
            yield name, content
        pos = end


def _decode_meta_stream(content: bytes) -> list[tuple[str, str]]:
    """Decode a stream of XDR SCMetaEntry preserving duplicate keys."""
    out: list[tuple[str, str]] = []
    try:
        from xdrlib3 import Unpacker
        from stellar_sdk.xdr import SCMetaEntry

        up = Unpacker(content)
        while up.get_position() < len(content):
            entry = SCMetaEntry.unpack(up)
            v0 = getattr(entry, "v0", None)
            if v0 is None:
                continue
            key = v0.key
            val = v0.val
            key_s = key.decode("utf-8", "replace") if isinstance(key, (bytes, bytearray)) else str(key)
            val_s = val.decode("utf-8", "replace") if isinstance(val, (bytes, bytearray)) else str(val)
            out.append((key_s, val_s))
    except Exception as exc:  # noqa: BLE001 - best effort
        logger.debug("Could not decode contract meta entries: %s", exc)
    return out


def _decode_meta_entries(content: bytes) -> dict[str, str]:
    """Decode meta entries; last value wins (legacy scalar view)."""
    out: dict[str, str] = {}
    for key, val in _decode_meta_stream(content):
        out[key] = val
    return out


def parse_wasm_meta(wasm_bytes: Optional[bytes]) -> WasmMeta:
    """Return full wasm metadata including repeating bldopt/bldarg entries."""
    if not wasm_bytes:
        return WasmMeta()
    try:
        meta = WasmMeta()
        for name, content in _iter_custom_sections(wasm_bytes):
            if name != META_SECTION:
                continue
            for key, val in _decode_meta_stream(content):
                if key == "bldopt":
                    meta.bldopt.append(val)
                elif key == "bldarg":
                    meta.bldarg.append(val)
                else:
                    meta.scalars[key] = val
        return meta
    except Exception as exc:  # noqa: BLE001
        logger.debug("Wasm metadata parse failed: %s", exc)
        return WasmMeta()


def parse_wasm_metadata(wasm_bytes: Optional[bytes]) -> dict[str, str]:
    """Return scalar wasm metadata (last value per key) for legacy callers."""
    parsed = parse_wasm_meta(wasm_bytes)
    out = dict(parsed.scalars)
    if parsed.bldopt:
        out["bldopt"] = parsed.bldopt[-1]
    if parsed.bldarg:
        out["bldarg"] = parsed.bldarg[-1]
    return out


def wasm_meta_to_storage_dict(parsed: WasmMeta) -> dict[str, str | list[str]]:
    """Serialize parsed meta for JSON storage on Verification.onchain_meta."""
    out: dict[str, str | list[str]] = dict(parsed.scalars)
    if parsed.bldopt:
        out["bldopt_list"] = list(parsed.bldopt)
        out["bldopt"] = parsed.bldopt[-1]
    if parsed.bldarg:
        out["bldarg_list"] = list(parsed.bldarg)
        out["bldarg"] = parsed.bldarg[-1]
    return out


def declared_build_image(meta: dict[str, str]) -> Optional[str]:
    """Return the SEP-58 declared builder image (`bldimg`) if present."""
    if not meta:
        return None
    for key in ("bldimg", "build_image", "buildimg"):
        if meta.get(key):
            return meta[key]
    return None


def declared_bldopt(meta: dict[str, str]) -> Optional[str]:
    if not meta:
        return None
    return meta.get("bldopt")


def declared_bldarg(meta: dict[str, str | list[str]]) -> list[str]:
    if not meta:
        return []
    listed = meta.get("bldarg_list")
    if isinstance(listed, list) and listed:
        return [str(v) for v in listed]
    single = meta.get("bldarg")
    if isinstance(single, str) and single:
        return [single]
    return []


def declared_bldopt_list(meta: dict[str, str | list[str]]) -> list[str]:
    if not meta:
        return []
    listed = meta.get("bldopt_list")
    if isinstance(listed, list) and listed:
        return [str(v) for v in listed]
    single = meta.get("bldopt")
    if isinstance(single, str) and single:
        return [single]
    return []


def declared_source_repo(meta: dict[str, str]) -> Optional[str]:
    if not meta:
        return None
    for key in ("source_repo", "sourcerepo"):
        if meta.get(key):
            return meta[key]
    return None


def declared_source_rev(meta: dict[str, str]) -> Optional[str]:
    if not meta:
        return None
    for key in ("source_rev", "sourcerev", "source_commit"):
        if meta.get(key):
            return meta[key]
    return None
